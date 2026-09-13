"""
CXFParser — parse inward CXF XML received from NGCH.

The drawee bank receives the CXF that the presentee bank submitted (passed
through by NGCH unmodified). This parser extracts:
  - File-level header: session_id, cibf_filename, presenting_bank_rout_no
  - FileSummary totals
  - Per-instrument fields (attributes on <Item>) + CIBF byte offsets from
    the three <ImageViewDetail> child blocks

The byte offsets are the key output: they are required by CIBFParser to slice
individual cheque images out of the binary CIBF bundle.

Namespace-tolerant parsing: accepts CXF with or without the namespace prefix.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List

import structlog

log = structlog.get_logger()

_CXF_NS = "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005"


class CXFParseError(ValueError):
    """Raised when CXF XML is malformed or missing required fields."""


@dataclass
class ParsedCXFItem:
    """One instrument parsed from CXF <Item> element."""
    item_seq_no: str
    payor_bank_rout_no: str
    serial_no: str
    trans_code: str
    micr_line: str
    drawee_ifsc: str
    amount_paise: int
    doc_type: str
    micrds_fingerprint: str
    micrds_signature: str
    # CIBF byte offsets (from <ImageViewDetail> blocks)
    front_bw_ds_offset: int
    front_bw_image_offset: int
    front_bw_image_length: int
    back_bw_ds_offset: int
    back_bw_image_offset: int
    back_bw_image_length: int
    front_gray_ds_offset: int
    front_gray_image_offset: int
    front_gray_image_length: int
    # IQA user fields
    iqa_user_field_front_bw: str
    iqa_user_field_back_bw: str
    iqa_user_field_front_gray: str


@dataclass
class ParsedCXFFile:
    """Full parsed CXF file."""
    session_id: str
    cibf_filename: str
    presenting_bank_rout_no: str
    total_item_count: int
    total_amount_paise: int
    items: List[ParsedCXFItem]


def _ns(tag: str) -> str:
    return f"{{{_CXF_NS}}}{tag}"


def _attr(element: ET.Element, name: str, required: bool = True) -> str:
    """Read attribute from element, trying namespaced form first."""
    v = element.get(name)
    if v is None and required:
        raise CXFParseError(f"Missing required attribute '{name}' on <{element.tag}>")
    return (v or "").strip()


def _find_child(parent: ET.Element, local: str) -> ET.Element | None:
    """Find direct child by local name, namespace-tolerant."""
    child = parent.find(_ns(local))
    if child is None:
        child = parent.find(local)
    if child is None:
        # Any-namespace fallback: match on local name only
        for el in list(parent):
            el_local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if el_local == local:
                return el
    return child


def _require_child(parent: ET.Element, local: str) -> ET.Element:
    child = _find_child(parent, local)
    if child is None:
        raise CXFParseError(f"Missing required child element <{local}> in <{parent.tag}>")
    return child


class CXFParser:
    """Parses CXF XML bytes into ParsedCXFFile.

    Namespace-tolerant: works with or without the CXF XML namespace.
    """

    def parse(self, xml_bytes: bytes) -> ParsedCXFFile:
        if not xml_bytes:
            raise CXFParseError("CXF XML bytes are empty")
        try:
            root = ET.fromstring(xml_bytes.strip())
        except ET.ParseError as exc:
            raise CXFParseError(f"Invalid CXF XML: {exc}") from exc

        session_id           = _attr(root, "SessionID")
        presenting_bank_rout = _attr(root, "PresentingBankRoutNo")
        cibf_filename        = _attr(root, "CIBFFileName")

        file_summary = _find_child(root, "FileSummary")
        if file_summary is None:
            raise CXFParseError("CXF XML missing <FileSummary>")
        total_item_count   = int(_attr(file_summary, "TotalItemCount"))
        total_amount_paise = int(_attr(file_summary, "TotalAmountPaise"))

        # Locate Batch — one per CXF in ASTRA's implementation
        batch = _find_child(root, "Batch")
        if batch is None:
            raise CXFParseError("CXF XML missing <Batch>")

        items = []
        for item_el in list(batch):
            local = item_el.tag.split("}")[-1] if "}" in item_el.tag else item_el.tag
            if local != "Item":
                continue
            items.append(self._parse_item(item_el))

        log.info(
            "cxf_parser.parsed",
            session_id=session_id,
            instrument_count=len(items),
        )
        return ParsedCXFFile(
            session_id=session_id,
            cibf_filename=cibf_filename,
            presenting_bank_rout_no=presenting_bank_rout,
            total_item_count=total_item_count,
            total_amount_paise=total_amount_paise,
            items=items,
        )

    def _parse_item(self, item_el: ET.Element) -> ParsedCXFItem:
        item_seq_no      = _attr(item_el, "ItemSeqNo")
        payor_bank_rout  = _attr(item_el, "PayorBankRoutNo")
        serial_no        = _attr(item_el, "SerialNo")
        trans_code       = _attr(item_el, "TransCode")
        micr_line        = _attr(item_el, "MICRLine")
        drawee_ifsc      = _attr(item_el, "DraweeIFSC")
        amount_paise     = int(_attr(item_el, "Amount"))
        doc_type         = _attr(item_el, "DocType")

        micrds_el = _require_child(item_el, "MICRDS")
        micrds_fp  = _attr(micrds_el, "MICRFingerPrint")
        micrds_sig = _attr(micrds_el, "SignatureData")

        # Parse 3 ImageViewDetail blocks in order: Front BW, Back BW, Front Gray
        ivd_offsets = {}  # ViewSideIndicator → (ds_offset, img_offset, img_length, user_field)
        for ivd_el in list(item_el):
            local = ivd_el.tag.split("}")[-1] if "}" in ivd_el.tag else ivd_el.tag
            if local != "ImageViewDetail":
                continue
            view_side = _attr(ivd_el, "ViewSideIndicator")
            ids_el  = _require_child(ivd_el, "ImageDS")
            ivdata  = _require_child(ivd_el, "ImageViewData")
            iva_el  = _require_child(ivd_el, "ImageViewAnalysis")
            ivd_offsets[view_side] = (
                int(_attr(ids_el,  "DigitalSignatureDataOffset")),
                int(_attr(ivdata,  "ImageDataOffset")),
                int(_attr(ivdata,  "ImageDataLength")),
                _attr(iva_el, "UserField"),
            )

        def _off(view: str) -> tuple:
            if view not in ivd_offsets:
                raise CXFParseError(
                    f"Item {item_seq_no}: missing <ImageViewDetail "
                    f"ViewSideIndicator='{view}'>"
                )
            return ivd_offsets[view]

        fbw  = _off("Front BW")
        bbw  = _off("Back BW")
        fgry = _off("Front Gray")

        return ParsedCXFItem(
            item_seq_no=item_seq_no,
            payor_bank_rout_no=payor_bank_rout,
            serial_no=serial_no,
            trans_code=trans_code,
            micr_line=micr_line,
            drawee_ifsc=drawee_ifsc,
            amount_paise=amount_paise,
            doc_type=doc_type,
            micrds_fingerprint=micrds_fp,
            micrds_signature=micrds_sig,
            front_bw_ds_offset=fbw[0],
            front_bw_image_offset=fbw[1],
            front_bw_image_length=fbw[2],
            back_bw_ds_offset=bbw[0],
            back_bw_image_offset=bbw[1],
            back_bw_image_length=bbw[2],
            front_gray_ds_offset=fgry[0],
            front_gray_image_offset=fgry[1],
            front_gray_image_length=fgry[2],
            iqa_user_field_front_bw=fbw[3],
            iqa_user_field_back_bw=bbw[3],
            iqa_user_field_front_gray=fgry[3],
        )
