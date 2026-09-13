"""
CXFBuilder — Capture eXchange Format XML per CHI Spec Rev 3.00.

Builds the outward clearing XML (CXF) submitted to CCH by the presentee bank.

Key spec requirements (CHI Spec Rev 3.00):
  - Root element: <FileHeader> (NOT <PresentmentExchangeFile>)
  - All item fields as XML ATTRIBUTES on <Item> (NOT child text elements)
  - ItemSeqNo: exactly 14 chars
  - MICRDS: <MICRDS MICRFingerPrint="..." SignatureData="..."/> (attributes)
  - <AddendA> element per item (BOFD/truncation endorsement data)
  - <FileSummary> at document level (TotalItemCount, TotalAmount)
  - <ImageViewData> per image view with byte offsets from CIBF assembler
  - <ImageDS> per image view referencing DS byte offset in CIBF
  - ViewSideIndicator values: "Front BW", "Back BW", "Front Gray"
  - IQA UserField: 21 chars ("BFB:"/"BBB:"/"BFG:" + 17 codes)
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List

import structlog

log = structlog.get_logger()

_CXF_NS = "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005"
_MICRDS_SIG_LENGTH = 344
_IQA_USER_FIELD_LENGTH = 21

_IQA_VIEW_SPECS = [
    ("Front BW", "BFB:"),
    ("Back BW",  "BBB:"),
    ("Front Gray", "BFG:"),
]


class CXFValidationError(ValueError):
    """Raised when a CXFItem fails pre-build validation."""


@dataclass
class CXFItem:
    """One cheque instrument for inclusion in the CXF outward submission.

    All item fields become XML attributes on <Item> per CHI Spec Rev 3.00.
    """
    item_seq_no: str                   # exactly 14 chars
    payor_bank_rout_no: str            # 9-digit NPCI routing no of drawee bank
    account_no: str                    # masked last-4 for log; hashed in DB
    serial_no: str                     # MICR cheque serial number
    trans_code: str                    # MICR transaction code
    micr_line: str
    micrds_fingerprint: str            # semicolon-delimited field names
    micrds_signature: str              # 344-char Base64 RSA-SHA256
    iqa_user_field_front_bw: str       # "BFB:" + 17 codes = 21 chars
    iqa_user_field_back_bw: str        # "BBB:" + 17 codes = 21 chars
    iqa_user_field_front_gray: str     # "BFG:" + 17 codes = 21 chars
    amount_paise: int
    drawee_ifsc: str
    doc_type: str                      # e.g. "01" (cheque)
    presenting_bank_rout_no: str
    cycle_no: str
    presentment_date: str              # DDMMYYYY
    batch_id: str
    # CIBF byte offsets for ImageViewData + ImageDS elements
    front_bw_ds_offset: int
    front_bw_image_offset: int
    front_bw_image_length: int
    back_bw_ds_offset: int
    back_bw_image_offset: int
    back_bw_image_length: int
    front_gray_ds_offset: int
    front_gray_image_offset: int
    front_gray_image_length: int

    def __post_init__(self) -> None:
        if len(self.item_seq_no) != 14:
            raise CXFValidationError(
                f"ItemSeqNo must be exactly 14 chars, got {len(self.item_seq_no)}: "
                f"{self.item_seq_no!r}"
            )
        if len(self.micrds_signature) != _MICRDS_SIG_LENGTH:
            raise CXFValidationError(
                f"micrds_signature must be {_MICRDS_SIG_LENGTH} chars (Base64 RSA-SHA256), "
                f"got {len(self.micrds_signature)}"
            )
        for field_attr, (_, prefix) in zip(
            (self.iqa_user_field_front_bw,
             self.iqa_user_field_back_bw,
             self.iqa_user_field_front_gray),
            _IQA_VIEW_SPECS,
        ):
            if len(field_attr) != _IQA_USER_FIELD_LENGTH or not field_attr.startswith(prefix):
                raise CXFValidationError(
                    f"IQA UserField for '{prefix}' view must be '{prefix}' + 17 codes "
                    f"(total {_IQA_USER_FIELD_LENGTH} chars), got: {field_attr!r}"
                )


def _el(tag: str, **attrs) -> ET.Element:
    """Create an element with given attributes."""
    e = ET.Element(tag)
    for k, v in attrs.items():
        e.set(k, str(v))
    return e


def _sub(parent: ET.Element, tag: str, **attrs) -> ET.Element:
    """Append a child element with given attributes."""
    child = ET.SubElement(parent, tag)
    for k, v in attrs.items():
        child.set(k, str(v))
    return child


class CXFBuilder:
    """Builds a spec-compliant CXF XML document from a list of CXFItem objects."""

    def build(
        self,
        items: List[CXFItem],
        *,
        session_id: str,
        cibf_filename: str,
    ) -> bytes:
        """Build CXF XML and return UTF-8 encoded bytes with XML declaration.

        Args:
            items:          Non-empty list of CXFItem (max 150 per NPCI rules).
            session_id:     Clearing session identifier.
            cibf_filename:  The companion CIBF filename (referenced in FileHeader).

        Returns:
            UTF-8 XML bytes starting with <?xml version="1.0" encoding="UTF-8"?>.

        Raises:
            CXFValidationError: If items list is empty.
        """
        if not items:
            raise CXFValidationError("CXF items list must not be empty")

        # Root: <FileHeader> with namespace
        root = ET.Element("FileHeader")
        root.set("xmlns", _CXF_NS)
        root.set("SessionID", session_id)
        root.set("PresentingBankRoutNo", items[0].presenting_bank_rout_no)
        root.set("CIBFFileName", cibf_filename)

        # <FileSummary> — document-level totals
        total_amount = sum(i.amount_paise for i in items)
        _sub(root, "FileSummary",
             TotalItemCount=str(len(items)),
             TotalAmountPaise=str(total_amount))

        # Batch — one per builder call (items are pre-grouped by caller)
        batch = _sub(root, "Batch",
                     BatchID=items[0].batch_id,
                     PresentingBankRoutNo=items[0].presenting_bank_rout_no,
                     PresentmentDate=items[0].presentment_date,
                     CycleNo=items[0].cycle_no)

        for item in items:
            self._add_item(batch, item)

        ET.indent(ET.ElementTree(root), space="  ")
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            root, encoding="unicode", xml_declaration=False
        )
        result = xml_str.encode("utf-8")

        log.info(
            "cxf_builder.built",
            session_id=session_id,
            item_count=len(items),
            byte_count=len(result),
        )
        return result

    def _add_item(self, batch: ET.Element, item: CXFItem) -> None:
        """Append one <Item> with all fields as XML attributes, plus child elements."""
        item_el = _sub(
            batch, "Item",
            ItemSeqNo=item.item_seq_no,
            PayorBankRoutNo=item.payor_bank_rout_no,
            SerialNo=item.serial_no,
            TransCode=item.trans_code,
            MICRLine=item.micr_line,
            DraweeIFSC=item.drawee_ifsc,
            Amount=str(item.amount_paise),
            DocType=item.doc_type,
        )

        # <MICRDS> — digital signature over MICR field values
        _sub(item_el, "MICRDS",
             MICRFingerPrint=item.micrds_fingerprint,
             SignatureData=item.micrds_signature)

        # <AddendA> — BOFD/truncating bank endorsement data
        _sub(item_el, "AddendA",
             TruncatingRoutNo=item.presenting_bank_rout_no,
             TruncatingBusDate=item.presentment_date)

        # Three <ImageViewDetail> blocks — one per image view
        views = [
            ("Front BW",   item.iqa_user_field_front_bw,
             item.front_bw_ds_offset, item.front_bw_image_offset, item.front_bw_image_length),
            ("Back BW",    item.iqa_user_field_back_bw,
             item.back_bw_ds_offset, item.back_bw_image_offset, item.back_bw_image_length),
            ("Front Gray", item.iqa_user_field_front_gray,
             item.front_gray_ds_offset, item.front_gray_image_offset, item.front_gray_image_length),
        ]
        for view_side, user_field, ds_offset, img_offset, img_length in views:
            ivd = _sub(item_el, "ImageViewDetail",
                       ViewSideIndicator=view_side)
            # ImageDS — references byte offset of the 256-byte DS within the CIBF
            _sub(ivd, "ImageDS",
                 DigitalSignatureDataOffset=str(ds_offset))
            # ImageViewData — byte offset + length of the image within the CIBF
            _sub(ivd, "ImageViewData",
                 ImageDataOffset=str(img_offset),
                 ImageDataLength=str(img_length))
            # ImageViewAnalysis — IQA result codes
            _sub(ivd, "ImageViewAnalysis",
                 UserField=user_field)
