"""
CXF Builder — Cheque Exchange Format XML per CTS CHI Spec Rev 3.0.

Builds the outward clearing XML submitted to NGCH by the presentee bank.
Namespace: urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005

Per CHI Spec Rev 3.0, each item has THREE ImageViewDetail blocks — one per
image view. Each block contains a UserField with IQA result codes:
  BFB: + 16 codes  ← Front B/W (ViewType="FrontBlackAndWhite")
  BBB: + 16 codes  ← Back B/W  (ViewType="BackBlackAndWhite")
  BFG: + 16 codes  ← Front Gray (ViewType="FrontGrayscale")

Key fields per item:
  <MICRDS>  — RSA-SHA256 over MICR line, Base64-encoded (344 chars)
  <ImageViewDetail ViewType="..."><ImageViewAnalysis><UserField> — IQA result (20 chars)
  <AmountPaise>  — cheque amount in paise (integer)
  <ItemSeqNo>    — 5-digit item sequence number within the batch

Input validation enforces:
  - MICRDS must be exactly 344 characters
  - Each of the 3 IQA UserFields must be exactly 20 chars with correct prefix
  - Item list must not be empty
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List

import structlog

log = structlog.get_logger()

_CXF_NS = "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005"
_MICRDS_LENGTH = 344
_IQA_USER_FIELD_LENGTH = 20

# (ViewType attribute value, required prefix)
_IQA_VIEW_SPECS = [
    ("FrontBlackAndWhite", "BFB:"),
    ("BackBlackAndWhite",  "BBB:"),
    ("FrontGrayscale",     "BFG:"),
]


class CXFValidationError(ValueError):
    """Raised when a CXFItem fails pre-build validation."""


@dataclass
class CXFItem:
    """One cheque instrument in the CXF outward submission.

    Three IQA user fields are required per CHI Spec Rev 3.0:
      iqa_user_field_front_bw  — "BFB:" + 16 codes (Front B/W view)
      iqa_user_field_back_bw   — "BBB:" + 16 codes (Back B/W view)
      iqa_user_field_front_gray— "BFG:" + 16 codes (Front Grayscale view)
    """

    item_seq_no:                str    # 5 digits
    micr_line:                  str
    micrds:                     str    # 344-char Base64 RSA-SHA256 signature
    iqa_user_field_front_bw:    str    # "BFB:" + 16 codes = 20 chars
    iqa_user_field_back_bw:     str    # "BBB:" + 16 codes = 20 chars
    iqa_user_field_front_gray:  str    # "BFG:" + 16 codes = 20 chars
    amount_paise:               int
    drawee_ifsc:                str
    drawee_account:             str
    presenting_bank_rout_no:    str
    cycle_no:                   str
    presentment_date:           str
    batch_id:                   str

    def __post_init__(self) -> None:
        if len(self.micrds) != _MICRDS_LENGTH:
            raise CXFValidationError(
                f"MICRDS must be exactly {_MICRDS_LENGTH} characters, "
                f"got {len(self.micrds)}"
            )
        for field_name, (view_type, prefix) in zip(
            ("iqa_user_field_front_bw", "iqa_user_field_back_bw", "iqa_user_field_front_gray"),
            _IQA_VIEW_SPECS,
        ):
            value = getattr(self, field_name)
            if len(value) != _IQA_USER_FIELD_LENGTH or not value.startswith(prefix):
                raise CXFValidationError(
                    f"{field_name} must be '{prefix}' + 16 chars "
                    f"(total {_IQA_USER_FIELD_LENGTH}), got: {value!r}"
                )


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    """Append a child element to parent, optionally with text content."""
    child = ET.SubElement(parent, tag)
    if text is not None:
        child.text = text
    return child


class CXFBuilder:
    """Builds CXF XML from a list of CXFItem objects."""

    def build(self, items: List[CXFItem], *, session_id: str) -> bytes:
        """Build a CXF XML document and return UTF-8 encoded bytes.

        Raises CXFValidationError if items list is empty.
        """
        if not items:
            raise CXFValidationError("CXF items list must not be empty")

        # Root element with namespace
        root = ET.Element("PresentmentExchangeFile")
        root.set("xmlns", _CXF_NS)

        # FileHeader
        fh = _sub(root, "FileHeader")
        _sub(fh, "SessionID", session_id)
        _sub(fh, "PresentingBankRoutNo", items[0].presenting_bank_rout_no)

        # BatchGroup — one per call (items are pre-grouped by caller)
        batch_group = _sub(root, "BatchGroup")
        bh = _sub(batch_group, "BatchHeader")
        _sub(bh, "BatchID", items[0].batch_id)
        _sub(bh, "PresentingBankRoutNo", items[0].presenting_bank_rout_no)
        _sub(bh, "PresentmentDate", items[0].presentment_date)
        _sub(bh, "CycleNo", items[0].cycle_no)

        for item in items:
            self._add_item(batch_group, item)

        # Serialize with XML declaration
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
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

    def _add_item(self, batch_group: ET.Element, item: CXFItem) -> None:
        """Append one <Item> element to <BatchGroup>.

        Per CHI Spec Rev 3.0, three <ImageViewDetail> blocks are emitted —
        one per image view (Front B/W, Back B/W, Front Gray).
        """
        item_el = _sub(batch_group, "Item")
        _sub(item_el, "ItemSeqNo", item.item_seq_no)
        _sub(item_el, "MICRLine", item.micr_line)
        _sub(item_el, "MICRDS", item.micrds)
        _sub(item_el, "DraweeIFSC", item.drawee_ifsc)
        _sub(item_el, "DraweeAccount", item.drawee_account)
        _sub(item_el, "AmountPaise", str(item.amount_paise))

        # Three ImageViewDetail blocks — one per view type (CHI Spec Rev 3.0)
        view_fields = [
            ("FrontBlackAndWhite", item.iqa_user_field_front_bw),
            ("BackBlackAndWhite",  item.iqa_user_field_back_bw),
            ("FrontGrayscale",     item.iqa_user_field_front_gray),
        ]
        for view_type, user_field in view_fields:
            ivd = _sub(item_el, "ImageViewDetail")
            ivd.set("ViewType", view_type)
            iva = _sub(ivd, "ImageViewAnalysis")
            _sub(iva, "UserField", user_field)
