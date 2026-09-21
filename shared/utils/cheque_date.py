"""Shared cheque-date parser (inward + outward workflows).

Indian cheques print an 8-box DDMMYYYY date, so OCR usually returns it with no
separators ("09102026"). Pure and deterministic — safe inside a Temporal workflow.
"""
import re
from datetime import date, datetime
from typing import Optional

_SEPARATED = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d/%m/%y", "%d-%m-%y")
_ONLY_DIGITS_AND_SPACES = re.compile(r"^[\d\s]+$")


def parse_cheque_date(raw: Optional[str]) -> Optional[date]:
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    if _ONLY_DIGITS_AND_SPACES.match(text):
        digits = re.sub(r"\s", "", text)
        fmt = {8: "%d%m%Y", 6: "%d%m%y"}.get(len(digits))
        if fmt is None:
            return None
        try:
            return datetime.strptime(digits, fmt).date()
        except ValueError:
            return None

    for fmt in _SEPARATED:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
