"""Shared cheque amount-in-figures parser (inward + outward workflows).

Indian cheques write amounts like '10,00,000/-', 'Rs. 5,800/-', '15000=' or '₹12,202.00'.
Pure and deterministic — safe inside a Temporal workflow. Returns None when unparseable
(callers must handle None; a bare float() on OCR text crashes the workflow task and
Temporal retries it forever).
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

_PREFIX = re.compile(r"^(?:rs\.?|inr|₹)\s*", re.I)
_TRAILER = re.compile(r"[\s/\-=.]+$")          # trailing '/-', '=', '-', spaces, stray dots


def parse_amount_figures(raw: Optional[str]) -> Optional[Decimal]:
    if not raw or not raw.strip():
        return None
    text = _PREFIX.sub("", raw.strip())
    text = _TRAILER.sub("", text)
    text = text.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None
