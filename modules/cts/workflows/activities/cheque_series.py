"""
Cheque leaf validity activity — verifies a cheque number was legitimately issued
to the account and has not been reported lost, stolen, cancelled, or already used.

Uses CBSConnector.get_cheque_status() which returns:
  ACTIVE    — legitimately issued and unpresented → PROCEED
  LOST      — reported lost → STP_RETURN, URRBCH 86 (FORGED_INSTRUMENT)
  STOLEN    — reported stolen → STP_RETURN, URRBCH 86
  CANCELLED — drawer cancelled this leaf → STP_RETURN, URRBCH 20 (STOP_PAYMENT)
  USED      — already presented → HUMAN_REVIEW (possible duplicate or re-presentation)
  <unknown> — unrecognised status → HUMAN_REVIEW (conservative default)

Graceful degradation:
  CBS unavailable → HUMAN_REVIEW (never blocks clearing on infrastructure failure)
  NotImplementedError → HUMAN_REVIEW (connector not yet built for this CBS type)
  No CBS connector → HUMAN_REVIEW

Placement in ChequeProcessingWorkflow:
  After check_stop_payment (which checks for explicit stop orders),
  before lookup_pps — so a lost/stolen cheque exits before PPS/signature work.

Note: get_cheque_status() is distinct from check_stop_payment():
  stop_payment — drawer placed a specific stop order on this cheque
  cheque_series — cheque was never issued, or was reported lost/stolen/cancelled
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError

log = structlog.get_logger()

_STOLEN_LOST_STATUSES = {"LOST", "STOLEN"}
_CANCELLED_STATUS = "CANCELLED"
_ACTIVE_STATUS = "ACTIVE"
_USED_STATUS = "USED"


class ChequeSeriesActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    account_number: str
    cheque_number: str


class ChequeSeriesActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                           # "PROCEED" | "STP_RETURN" | "HUMAN_REVIEW"
    reason: Optional[str] = None           # human-readable reason code for audit
    return_reason_code: Optional[str] = None  # URRBCH code — set only on STP_RETURN
    degraded: bool = False


@activity.defn
async def validate_cheque_series(
    inp: ChequeSeriesActivityInput,
    cbs_connector=None,
) -> ChequeSeriesActivityResult:
    """
    Verify the cheque leaf status with CBS.

    Never raises. Degrades to HUMAN_REVIEW on any CBS failure so that clearing
    is not blocked by infrastructure unavailability.
    """
    if cbs_connector is None:
        log.warning(
            "cheque_series.no_cbs_connector",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )
        return ChequeSeriesActivityResult(outcome="HUMAN_REVIEW", reason="CBS_UNAVAILABLE", degraded=True)

    try:
        status = await cbs_connector.get_cheque_status(
            inp.account_number, inp.cheque_number, inp.bank_id
        )
    except AccountNotFoundError:
        log.info(
            "cheque_series.account_not_found",
            instrument_id=inp.instrument_id,
            account_last4=inp.account_number[-4:],
            bank_id=inp.bank_id,
        )
        return ChequeSeriesActivityResult(
            outcome="STP_RETURN",
            reason="ACCOUNT_NOT_FOUND",
            return_reason_code="52",
        )
    except (CBSUnavailableError, NotImplementedError) as exc:
        log.warning(
            "cheque_series.cbs_unavailable",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return ChequeSeriesActivityResult(outcome="HUMAN_REVIEW", reason="CBS_UNAVAILABLE", degraded=True)
    except Exception as exc:
        log.error(
            "cheque_series.unexpected_error",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return ChequeSeriesActivityResult(outcome="HUMAN_REVIEW", reason="CBS_UNAVAILABLE", degraded=True)

    status_upper = str(status).upper()

    if status_upper == _ACTIVE_STATUS:
        log.info(
            "cheque_series.active",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )
        return ChequeSeriesActivityResult(outcome="PROCEED")

    if status_upper in _STOLEN_LOST_STATUSES:
        reason = "CHEQUE_STOLEN" if status_upper == "STOLEN" else "CHEQUE_LOST"
        log.warning(
            "cheque_series.stolen_or_lost",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            cbs_status=status_upper,
        )
        return ChequeSeriesActivityResult(
            outcome="STP_RETURN",
            reason=reason,
            return_reason_code="86",
        )

    if status_upper == _CANCELLED_STATUS:
        log.info(
            "cheque_series.cancelled",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )
        return ChequeSeriesActivityResult(
            outcome="STP_RETURN",
            reason="CHEQUE_CANCELLED",
            return_reason_code="20",
        )

    if status_upper == _USED_STATUS:
        log.info(
            "cheque_series.already_used",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )
        return ChequeSeriesActivityResult(outcome="HUMAN_REVIEW", reason="CHEQUE_ALREADY_USED")

    # Unknown CBS status — conservative default: escalate rather than accept
    log.warning(
        "cheque_series.unknown_status",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        cbs_status=status_upper,
    )
    return ChequeSeriesActivityResult(outcome="HUMAN_REVIEW", reason=f"UNKNOWN_CBS_STATUS:{status_upper}")
