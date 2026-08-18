"""Cheque date validation — stale (RBI > 90 days → return reason 38) and post-dated.

The stale window is configurable (stale_days) so banks can apply a stricter policy.
Caller must source stale_days from:
    config_service.get("cts.stale_cheque_days", bank_id)  # default 90
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

DateDecision = Literal["VALID", "STALE", "POST_DATED", "INVALID_FORMAT"]

# ── Date format patterns (ordered: try most common first) ──────────────────
_SEPARATORS = re.compile(r"[\s/\-.]")

_DATE_FORMATS: list[tuple[str, str]] = [
    # (regex pattern without separators, strptime format)
    (r"^\d{2}\d{2}\d{4}$", "%d%m%Y"),  # DDMMYYYY
    (r"^\d{2}\d{2}\d{2}$",  "%d%m%y"),  # DDMMYY
]


def _parse_date(date_str: str) -> date | None:
    """Parse common Indian cheque date formats. Returns None on failure."""
    # Strip leading/trailing whitespace
    raw = date_str.strip()
    if not raw:
        return None

    # Collapse separator characters to uniform slash
    normalised = _SEPARATORS.sub("", raw)

    for _, fmt in _DATE_FORMATS:
        try:
            return date(*__import__("time").strptime(normalised, fmt)[:3])
        except (ValueError, OverflowError):
            continue

    # Last resort: split on separators and try D/M/Y ordering
    parts = _SEPARATORS.split(raw)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) == 3:
        d_str, m_str, y_str = parts
        try:
            d = int(d_str)
            m = int(m_str)
            y = int(y_str)
            if y < 100:  # 2-digit year
                y += 2000 if y < 50 else 1900
            return date(y, m, d)
        except (ValueError, OverflowError):
            pass

    return None


@dataclass(frozen=True)
class DateValidationResult:
    decision: DateDecision
    cheque_date: date | None
    days_old: int | None        # negative = future (post-dated)
    return_reason_code: str | None  # "38" for stale; None otherwise


def validate_cheque_date(
    date_str: str,
    stale_days: int = 90,
    reference_date: date | None = None,
) -> DateValidationResult:
    """Validate a cheque date string against RBI CTS staleness and post-dating rules.

    Args:
        date_str:       Raw date string extracted by OCR (e.g. "07/08/2026").
        stale_days:     Days after which a cheque is considered stale.
                        Default 90 per RBI CTS circular; pass from config_service.
        reference_date: The date to compare against. Defaults to today.
                        Injected in tests to make assertions deterministic.
    """
    ref = reference_date or date.today()
    cheque_date = _parse_date(date_str)

    if cheque_date is None:
        return DateValidationResult(
            decision="INVALID_FORMAT",
            cheque_date=None,
            days_old=None,
            return_reason_code=None,
        )

    days_old: int = (ref - cheque_date).days  # negative if future

    if days_old < 0:
        # Post-dated: goes to hold queue — NOT a return
        return DateValidationResult(
            decision="POST_DATED",
            cheque_date=cheque_date,
            days_old=days_old,
            return_reason_code=None,
        )

    if days_old > stale_days:
        # Stale: return reason 38 per CTS-2010 return reason schedule
        return DateValidationResult(
            decision="STALE",
            cheque_date=cheque_date,
            days_old=days_old,
            return_reason_code="38",
        )

    return DateValidationResult(
        decision="VALID",
        cheque_date=cheque_date,
        days_old=days_old,
        return_reason_code=None,
    )
