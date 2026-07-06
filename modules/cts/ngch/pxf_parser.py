"""
PXF Parser — full inward instrument parser per CTS Spec Rev 3.0.

Parses the Presentment Exchange File (PXF) sent by NGCH to the drawee bank.
Each <Item> element becomes one InwardInstrument. The per-item ItemExpiryTime
is parsed to a UTC Unix timestamp via pxf_iet_parser.

UDK (Unique Document Key) = PresentmentDate(8) + PresentingBankRoutNo(9)
                           + CycleNo(2) + ItemSeqNo(5) = 24 chars total.

PPS_Flag values (per CTS Spec Rev 3.0):
  P = Positive Pay match confirmed
  D = Drawee to verify
  Y = PPS registered, date/amount not checked
  Z = PPS inactive/cancelled
  N = No PPS instruction exists
  R = Refer to drawee
  U = Unknown
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from typing import List

import structlog

from modules.cts.ngch.pxf_iet_parser import IETParseError, iet_to_unix_timestamp

log = structlog.get_logger()

_PXF_NS = "urn:schemas-ncr-com:ECPIX:PXF:FileStructure:010003"


class PXFParseError(ValueError):
    """Raised when the PXF XML cannot be parsed or is missing required fields."""


class ClearingType(str, Enum):
    NORMAL         = "01"   # Standard CTS clearing
    ON_REALIZATION = "14"   # On-realization clearing (new in Rev 3.0)


class PPSFlagMeaning(str, Enum):
    CONFIRMED  = "P"  # PPS match confirmed by CCH
    VERIFY     = "D"  # Drawee to verify
    REGISTERED = "Y"  # PPS registered, drawee must verify amount/date
    CANCELLED  = "Z"  # PPS inactive/cancelled — treat as stop payment
    NO_PPS     = "N"  # No PPS instruction exists
    REFER      = "R"  # Refer to drawee
    UNKNOWN    = "U"  # Unknown / unable to determine


_PPS_FLAG_MAP = {e.value: e for e in PPSFlagMeaning}


@dataclass
class InwardInstrument:
    """One parsed inward cheque from a PXF file."""

    # IET deadline (UTC Unix timestamp) — from ItemExpiryTime in PXF
    iet_deadline: float

    # PPS status
    pps_flag: str
    pps_flag_meaning: PPSFlagMeaning

    # Clearing session type
    clearing_type: ClearingType

    # UDK = PresentmentDate + PresentingBankRoutNo + CycleNo + ItemSeqNo
    udk: str

    # Instrument data
    micr_line: str
    drawee_ifsc: str
    drawee_account: str
    amount_paise: int
    item_seq_no: str

    @property
    def is_on_realization(self) -> bool:
        return self.clearing_type == ClearingType.ON_REALIZATION


def _tag(local: str) -> str:
    """Build a namespace-qualified tag name."""
    return f"{{{_PXF_NS}}}{local}"


def _find_text(element, local_name: str, *, required: bool = True) -> str:
    """Find child element text, with or without namespace."""
    # Try namespaced first, then non-namespaced (tolerant parsing)
    child = element.find(_tag(local_name))
    if child is None:
        child = element.find(local_name)
    if child is None or child.text is None:
        if required:
            raise PXFParseError(f"Missing required PXF element: <{local_name}>")
        return ""
    return child.text.strip()


class PXFParser:
    """Parses PXF XML bytes into a list of InwardInstrument objects."""

    def parse(self, xml_bytes: bytes) -> List[InwardInstrument]:
        """Parse PXF XML and return one InwardInstrument per <Item>.

        Raises PXFParseError if the XML is malformed or missing required elements.
        """
        if not xml_bytes:
            raise PXFParseError("PXF XML bytes are empty")

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise PXFParseError(f"Invalid PXF XML: {exc}") from exc

        # Locate BatchGroup (may or may not be namespaced)
        batch_group = root.find(_tag("BatchGroup"))
        if batch_group is None:
            batch_group = root.find("BatchGroup")
        if batch_group is None:
            raise PXFParseError("PXF XML missing required <BatchGroup> element")

        # Extract batch-level fields (shared across all items in the batch)
        batch_header = batch_group.find(_tag("BatchHeader"))
        if batch_header is None:
            batch_header = batch_group.find("BatchHeader")
        if batch_header is None:
            raise PXFParseError("PXF XML missing <BatchHeader>")

        presenting_bank_rout_no = _find_text(batch_header, "PresentingBankRoutNo")
        presentment_date        = _find_text(batch_header, "PresentmentDate")
        cycle_no                = _find_text(batch_header, "CycleNo")

        # Locate FileHeader for session-level ClearingType
        file_header = root.find(_tag("FileHeader"))
        if file_header is None:
            file_header = root.find("FileHeader")
        if file_header is None:
            raise PXFParseError("PXF XML missing <FileHeader>")

        clearing_type_raw = _find_text(file_header, "ClearingType")
        try:
            clearing_type = ClearingType(clearing_type_raw)
        except ValueError:
            raise PXFParseError(
                f"Unknown ClearingType '{clearing_type_raw}' in PXF — "
                "expected '01' (normal) or '14' (On Realization)"
            )

        # Parse each <Item>
        instruments: List[InwardInstrument] = []
        items = batch_group.findall(_tag("Item"))
        if not items:
            items = batch_group.findall("Item")

        for item in items:
            instruments.append(
                self._parse_item(
                    item,
                    clearing_type=clearing_type,
                    presentment_date=presentment_date,
                    presenting_bank_rout_no=presenting_bank_rout_no,
                    cycle_no=cycle_no,
                )
            )

        log.info(
            "pxf_parser.parsed",
            instrument_count=len(instruments),
            clearing_type=clearing_type_raw,
        )
        return instruments

    def _parse_item(
        self,
        item: ET.Element,
        *,
        clearing_type: ClearingType,
        presentment_date: str,
        presenting_bank_rout_no: str,
        cycle_no: str,
    ) -> InwardInstrument:
        """Parse one <Item> element into an InwardInstrument."""
        item_seq_no       = _find_text(item, "ItemSeqNo")
        iet_raw           = _find_text(item, "ItemExpiryTime")
        pps_flag_raw      = _find_text(item, "PPS_Flag")
        micr_line         = _find_text(item, "MICRLine")
        drawee_ifsc       = _find_text(item, "DraweeIFSC")
        drawee_account    = _find_text(item, "DraweeAccount")
        amount_paise_str  = _find_text(item, "AmountPaise")

        # Parse IET (P0 — safety critical)
        try:
            iet_deadline = iet_to_unix_timestamp(iet_raw)
        except IETParseError as exc:
            raise PXFParseError(
                f"Item {item_seq_no}: invalid ItemExpiryTime {iet_raw!r}: {exc}"
            ) from exc

        # PPS flag
        pps_flag_meaning = _PPS_FLAG_MAP.get(pps_flag_raw, PPSFlagMeaning.UNKNOWN)

        # Amount
        try:
            amount_paise = int(amount_paise_str)
        except ValueError as exc:
            raise PXFParseError(
                f"Item {item_seq_no}: invalid AmountPaise '{amount_paise_str}'"
            ) from exc

        # UDK = PresentmentDate(8) + PresentingBankRoutNo(9) + CycleNo(2) + ItemSeqNo(5)
        udk = presentment_date + presenting_bank_rout_no + cycle_no + item_seq_no

        return InwardInstrument(
            iet_deadline=iet_deadline,
            pps_flag=pps_flag_raw,
            pps_flag_meaning=pps_flag_meaning,
            clearing_type=clearing_type,
            udk=udk,
            micr_line=micr_line,
            drawee_ifsc=drawee_ifsc,
            drawee_account=drawee_account,
            amount_paise=amount_paise,
            item_seq_no=item_seq_no,
        )
