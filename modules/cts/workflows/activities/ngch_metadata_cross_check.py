"""
NGCH metadata cross-check activity (Item 6).

Cross-validates MICR band fields extracted by GOT-OCR2 against the registered
instrument presentment metadata before the lot/NGCH pipeline.

Mismatches caught:
  CHEQUE_SERIAL — MICR first-6 digits ≠ registered cheque_number
  DRAWEE_IFSC   — IFSC printed on cheque face (from OCR) ≠ registered drawee IFSC
  AMOUNT        — OCR amount_figures ≠ registered amount (> 1 paisa tolerance)

Outcomes:
  PROCEED       — all checked fields agree (or no registered data to check against)
  HUMAN_REVIEW  — ≥ 1 mismatch detected; mismatch_fields lists which fields
  DEGRADED      — MICR line absent, empty, or too short to parse (never blocks clearing)

Design: pure computation, no external I/O, no DI required → NO_DI_ACTIVITIES.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.ngch_metadata_cross_check")

_MIN_MICR_LENGTH = 6   # need at least 6 chars to extract cheque serial


class NGCHMetadataCrossCheckInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    bank_id: str
    micr_line: Optional[str]                    # raw MICR line from GOT-OCR2 (may be None)
    registered_cheque_number: Optional[str] = None  # cheque_number entered at deposit
    ifsc_from_ocr: Optional[str] = None         # IFSC code printed on cheque face (from OCR)
    registered_drawee_ifsc: Optional[str] = None    # IFSC from instrument record
    registered_amount_str: Optional[str] = None     # amount entered at deposit (decimal string)
    amount_from_ocr: Optional[str] = None           # amount_figures from OCR


class NGCHMetadataCrossCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str                                # "PROCEED" | "HUMAN_REVIEW" | "DEGRADED"
    mismatch_fields: list[str] = []             # e.g. ["CHEQUE_SERIAL", "AMOUNT"]
    details: dict[str, Any] = {}               # per-field {micr_value, registered_value}
    degraded: bool = False


def _parse_amount(s: Optional[str]) -> Optional[float]:
    """Parse amount string to float; returns None on parse failure."""
    if not s:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


@activity.defn
async def cross_check_ngch_metadata(
    inp: NGCHMetadataCrossCheckInput,
) -> NGCHMetadataCrossCheckResult:
    """
    Pure-computation NGCH metadata cross-check.

    Parses MICR line, compares to registered instrument metadata, flags
    mismatches. Never raises — returns DEGRADED on unparseable MICR.
    """
    with tracer.start_as_current_span("activity.cross_check_ngch_metadata") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)

        micr = (inp.micr_line or "").strip()

        # Degraded if MICR is absent or too short
        if len(micr) < _MIN_MICR_LENGTH:
            log.warning(
                "ngch_cross_check.micr_absent",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                micr_len=len(micr),
            )
            span.set_attribute("cross_check.degraded", True)
            return NGCHMetadataCrossCheckResult(outcome="DEGRADED", degraded=True)

        mismatch_fields: list[str] = []
        details: dict[str, Any] = {}

        # Check 1: Cheque serial — MICR positions 0–5 (first 6 digits)
        try:
            micr_serial = micr[:6].strip()
            reg_serial = (inp.registered_cheque_number or "").strip().lstrip("0")
            micr_serial_norm = micr_serial.lstrip("0")

            if (
                inp.registered_cheque_number is not None
                and micr_serial.isdigit()  # skip check if OCR gave non-numeric garbage
                and reg_serial != micr_serial_norm
            ):
                mismatch_fields.append("CHEQUE_SERIAL")
                details["CHEQUE_SERIAL"] = {
                    "micr_value": micr_serial,
                    "registered_value": inp.registered_cheque_number,
                }
                log.info(
                    "ngch_cross_check.serial_mismatch",
                    instrument_id=inp.instrument_id,
                    micr_serial=micr_serial,
                )
        except Exception:
            # Parsing glitch — degrade only the serial check, continue others
            pass

        # Check 2: Drawee IFSC — OCR-extracted vs registered
        if inp.ifsc_from_ocr and inp.registered_drawee_ifsc:
            ocr_ifsc = inp.ifsc_from_ocr.strip().upper()
            reg_ifsc = inp.registered_drawee_ifsc.strip().upper()
            if ocr_ifsc != reg_ifsc:
                mismatch_fields.append("DRAWEE_IFSC")
                details["DRAWEE_IFSC"] = {
                    "micr_value": ocr_ifsc,        # from OCR (printed IFSC)
                    "registered_value": reg_ifsc,
                }
                log.info(
                    "ngch_cross_check.ifsc_mismatch",
                    instrument_id=inp.instrument_id,
                    ocr_ifsc=ocr_ifsc,
                )

        # Check 3: Amount — OCR vs registered (both sides must be present)
        if inp.amount_from_ocr and inp.registered_amount_str:
            ocr_amount = _parse_amount(inp.amount_from_ocr)
            reg_amount = _parse_amount(inp.registered_amount_str)
            if ocr_amount is not None and reg_amount is not None:
                # Allow ±1 paisa tolerance to absorb decimal formatting differences
                if abs(ocr_amount - reg_amount) > 0.01:
                    mismatch_fields.append("AMOUNT")
                    details["AMOUNT"] = {
                        "micr_value": inp.amount_from_ocr,
                        "registered_value": inp.registered_amount_str,
                    }
                    log.info(
                        "ngch_cross_check.amount_mismatch",
                        instrument_id=inp.instrument_id,
                        ocr_amount=mask_amount_range(ocr_amount),
                        reg_amount=mask_amount_range(reg_amount),
                    )

        outcome = "HUMAN_REVIEW" if mismatch_fields else "PROCEED"
        span.set_attribute("cross_check.outcome", outcome)
        span.set_attribute("cross_check.mismatch_count", len(mismatch_fields))

        log.info(
            "ngch_cross_check.result",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            outcome=outcome,
            mismatches=mismatch_fields,
        )
        return NGCHMetadataCrossCheckResult(
            outcome=outcome,
            mismatch_fields=mismatch_fields,
            details=details,
        )


def mask_amount_range(amount: float) -> str:
    """Bucket amount for safe logging — never log exact value."""
    if amount < 100_000:
        return "₹[<1L]"
    elif amount < 500_000:
        return "₹[1L-5L]"
    elif amount < 1_000_000:
        return "₹[5L-10L]"
    elif amount < 10_000_000:
        return "₹[10L-1Cr]"
    return "₹[>1Cr]"
