"""MICR line integrity validator for CTS-2010 cheque instruments.

CTS-2010 MICR line structure:
  ⑆ [cheque_no: 6 digits] ⑈ [MICR_code: 9 digits] [account_field: variable] ⑉ ⑆

Special characters:
  ⑆  U+2446  MICR transit     — field separator
  ⑈  U+2448  MICR amount      — separates cheque_no from MICR bank code
  ⑉  U+2449  MICR on-us       — separates account field from remainder

Validation detects:
  1. Format violations (wrong digit count, non-numeric fields)
  2. City code 000 (unassigned — indicates possible tampering)
  3. Account number suffix mismatch (cross-check against vault-stored last-4)

Caller responsibility: source expected_account_suffix from the signature vault
hashed key, NOT from the raw OCR text (which could be tampered).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MICRDecision = Literal["VALID", "SUSPICIOUS", "INVALID_FORMAT"]

_TRANSIT   = "⑆"  # ⑆
_AMOUNT    = "⑈"  # ⑈
_ONUS      = "⑉"  # ⑉

# Transaction codes assigned by RBI / NPCI for Indian clearing
_VALID_TX_CODES: frozenset[str] = frozenset({
    "05",  # savings account
    "10",  # current account
    "13",  # NRE savings
    "17",  # overdraft / cash credit
    "37",  # loan / CC account
    "50",  # government / institutional
})


@dataclass
class MICRValidationResult:
    decision: MICRDecision
    cheque_number: str | None
    micr_code: str | None
    account_field: str | None
    transaction_code: str | None
    flags: list[str] = field(default_factory=list)


def _strip_transit(s: str) -> str:
    return s.replace(_TRANSIT, "").strip()


def validate_micr_line(
    micr_str: str,
    expected_account_suffix: str | None = None,
) -> MICRValidationResult:
    """Parse and validate a MICR line extracted from a cheque image.

    Args:
        micr_str:                 Raw MICR string from OCR.
        expected_account_suffix:  Last 4 digits we expect in the account field,
                                  derived from the signature vault (not from OCR).
                                  If None, account cross-check is skipped.
    """
    flags: list[str] = []

    if not micr_str or not micr_str.strip():
        return MICRValidationResult(
            decision="INVALID_FORMAT",
            cheque_number=None, micr_code=None,
            account_field=None, transaction_code=None,
            flags=["empty_micr_string"],
        )

    # Normalise: remove outer ⑆, collapse spaces within fields
    raw = micr_str.strip()

    # ── Split on ⑈ (amount symbol) — left = cheque number, right = rest ──
    if _AMOUNT not in raw:
        return MICRValidationResult(
            decision="INVALID_FORMAT",
            cheque_number=None, micr_code=None,
            account_field=None, transaction_code=None,
            flags=["missing_amount_symbol"],
        )

    left, right = raw.split(_AMOUNT, 1)
    cheque_number = _strip_transit(left).replace(" ", "")

    # ── Validate cheque number ──────────────────────────────────────────────
    if not cheque_number.isdigit() or len(cheque_number) != 6:
        return MICRValidationResult(
            decision="INVALID_FORMAT",
            cheque_number=cheque_number or None, micr_code=None,
            account_field=None, transaction_code=None,
            flags=[f"cheque_number_invalid:{cheque_number!r}"],
        )

    # ── Split right side on ⑉ (on-us) — left = MICR code + account, right = tx ──
    right = right.strip()
    if _ONUS in right:
        mid, tx_part = right.split(_ONUS, 1)
    else:
        mid = right
        tx_part = ""

    mid = _strip_transit(mid).replace(" ", "")

    # ── Extract MICR code (first 9 digits) and account field (remainder) ──
    if len(mid) < 9 or not mid[:9].isdigit():
        return MICRValidationResult(
            decision="INVALID_FORMAT",
            cheque_number=cheque_number, micr_code=None,
            account_field=None, transaction_code=None,
            flags=["micr_code_invalid"],
        )

    micr_code    = mid[:9]
    account_field = mid[9:] if len(mid) > 9 else _strip_transit(tx_part).replace(" ", "")
    # If account field was after ⑉, pick it from tx_part if mid had no remainder
    if not account_field:
        account_field = _strip_transit(tx_part).replace(" ", "")

    # Transaction code: last 2 digits of account_field if present and numeric
    transaction_code: str | None = None
    if len(account_field) >= 2 and account_field[-2:].isdigit():
        transaction_code = account_field[-2:]

    # ── Validate MICR code ─────────────────────────────────────────────────
    city_code = micr_code[:3]
    if city_code == "000":
        flags.append("city_code_000_invalid")

    # ── Account suffix cross-check ─────────────────────────────────────────
    if expected_account_suffix is not None:
        n = len(expected_account_suffix)
        actual_suffix = account_field[-n:] if len(account_field) >= n else account_field
        if actual_suffix != expected_account_suffix:
            flags.append(f"account_suffix_mismatch:expected={expected_account_suffix}")

    decision: MICRDecision = "VALID" if not flags else "SUSPICIOUS"

    return MICRValidationResult(
        decision=decision,
        cheque_number=cheque_number,
        micr_code=micr_code,
        account_field=account_field,
        transaction_code=transaction_code,
        flags=flags,
    )
