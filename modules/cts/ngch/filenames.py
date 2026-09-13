"""
CTS NGCH filename generators — CHI Spec Rev 3.00 Appendix 4.1.1 (CXF) and 4.2.1 (CIBF).

CXF:  CXF_{RoutingNo}_{DDMMYYYY}_{HHMMSS}_{ClearingType}_{FileID}.XML
CIBF: CIBF_{RoutingNo}_{DDMMYYYY}_{HHMMSS}_{ClearingType}_{FileID}_{nn}.img

Valid clearing types (per Sep 2024 spec update — types 01/02/03/11 removed):
  "14" — On-Realization Session
  "99" — Special Clearing
"""

_VALID_CLEARING_TYPES = frozenset({"14", "99"})


def _validate_clearing_type(clearing_type: str) -> None:
    if clearing_type not in _VALID_CLEARING_TYPES:
        raise ValueError(
            f"clearing_type must be '14' or '99' "
            f"(types 01/02/03/11 removed Sep 2024); got {clearing_type!r}"
        )


def make_cxf_filename(
    routing_no: str,
    date_ddmmyyyy: str,
    time_hhmmss: str,
    clearing_type: str,
    file_id: str,
) -> str:
    """Return a spec-compliant CXF filename.

    Format: CXF_{RoutingNo}_{DDMMYYYY}_{HHMMSS}_{ClearingType}_{FileID}.XML
    """
    _validate_clearing_type(clearing_type)
    return f"CXF_{routing_no}_{date_ddmmyyyy}_{time_hhmmss}_{clearing_type}_{file_id}.XML"


def make_cibf_filename(
    routing_no: str,
    date_ddmmyyyy: str,
    time_hhmmss: str,
    clearing_type: str,
    file_id: str,
    modifier: str,
) -> str:
    """Return a spec-compliant CIBF filename.

    Format: CIBF_{RoutingNo}_{DDMMYYYY}_{HHMMSS}_{ClearingType}_{FileID}_{nn}.img
    Modifier is a 2-digit counter ("01", "02", …) unique per CXF session.
    """
    _validate_clearing_type(clearing_type)
    return f"CIBF_{routing_no}_{date_ddmmyyyy}_{time_hhmmss}_{clearing_type}_{file_id}_{modifier}.img"
