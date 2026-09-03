"""
Cheque leaf validity activity — verifies a cheque number was legitimately issued
to the account and has not been reported lost, stolen, cancelled, or already used.

Source mode (from config_service — cts.cheque_series.source):
  VAULT (default) — Redis-backed ChequeLeafVault; sub-5ms, no CBS round-trip.
  CBS             — Live CBS call; used when vault is not yet populated.

Vault mode outcomes:
  ACTIVE    → PROCEED
  LOST      → STP_RETURN, URRBCH 86 (FORGED_INSTRUMENT)
  STOLEN    → STP_RETURN, URRBCH 86
  CANCELLED → STP_RETURN, URRBCH 20 (STOP_PAYMENT)
  USED      → HUMAN_REVIEW (possible re-presentation)
  NOT_FOUND → HUMAN_REVIEW (leaf absent from vault)
  ERROR     → HUMAN_REVIEW (Redis unavailable, degraded=True)

CBS mode outcomes: same routing; data source is live CBS.

Graceful degradation:
  VAULT mode + vault not wired → falls back to CBS with warning log.
  CBS unavailable → HUMAN_REVIEW (never blocks clearing on infra failure).

Placement in ChequeProcessingWorkflow:
  Stage D — first check before check_cbs_balance. Cheap Redis lookup (VAULT mode)
  exits early on LOST/STOLEN before balance / account status are attempted.
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)

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
    reason: Optional[str] = None
    return_reason_code: Optional[str] = None
    degraded: bool = False


@activity.defn
async def validate_cheque_series(
    inp: ChequeSeriesActivityInput,
    cbs_connector=None,
    cheque_leaf_vault=None,
    config_service=None,
) -> ChequeSeriesActivityResult:
    """
    Verify the cheque leaf status via vault (default) or live CBS.

    Never raises. Degrades to HUMAN_REVIEW on any infrastructure failure.
    """
    with tracer.start_as_current_span("activity.validate_cheque_series") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        mode = await _resolve_mode(inp.bank_id, config_service)

        if mode == "VAULT" and cheque_leaf_vault is not None:
            return await _validate_via_vault(inp, cheque_leaf_vault)

        if mode == "VAULT" and cheque_leaf_vault is None:
            log.warning(
                "cheque_series.vault_mode_not_wired_falling_back_to_cbs",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            )

        return await _validate_via_cbs(inp, cbs_connector)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_mode(bank_id: str, config_service) -> str:
    if config_service is None:
        return "VAULT"
    try:
        cfg = await config_service.get_cts_config(bank_id)
        return str(cfg.get("cheque_series.source", "VAULT")).upper()
    except Exception:
        return "VAULT"


async def _validate_via_vault(
    inp: ChequeSeriesActivityInput,
    vault,
) -> ChequeSeriesActivityResult:
    vault_result = await vault.lookup(inp.account_number, inp.cheque_number)

    if vault_result.outcome == "NOT_FOUND":
        log.info(
            "cheque_series.vault_miss",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            bank_id=inp.bank_id,
        )
        return ChequeSeriesActivityResult(
            outcome="HUMAN_REVIEW",
            reason="LEAF_NOT_IN_VAULT",
        )

    if vault_result.outcome == "ERROR":
        return ChequeSeriesActivityResult(
            outcome="HUMAN_REVIEW",
            reason="VAULT_ERROR",
            degraded=True,
        )

    # FOUND — route by status
    status_upper = (vault_result.status or "UNKNOWN").upper()
    return _route_by_status(inp, status_upper)


async def _validate_via_cbs(
    inp: ChequeSeriesActivityInput,
    cbs_connector,
) -> ChequeSeriesActivityResult:
    if cbs_connector is None:
        log.warning(
            "cheque_series.no_cbs_connector",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )
        return ChequeSeriesActivityResult(
            outcome="HUMAN_REVIEW",
            reason="CBS_UNAVAILABLE",
            degraded=True,
        )

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
        return ChequeSeriesActivityResult(
            outcome="HUMAN_REVIEW",
            reason="CBS_UNAVAILABLE",
            degraded=True,
        )
    except Exception as exc:
        log.error(
            "cheque_series.unexpected_error",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return ChequeSeriesActivityResult(
            outcome="HUMAN_REVIEW",
            reason="CBS_UNAVAILABLE",
            degraded=True,
        )

    return _route_by_status(inp, str(status).upper())


def _route_by_status(
    inp: ChequeSeriesActivityInput,
    status_upper: str,
) -> ChequeSeriesActivityResult:
    if status_upper == _ACTIVE_STATUS:
        log.info("cheque_series.active", instrument_id=inp.instrument_id, bank_id=inp.bank_id)
        return ChequeSeriesActivityResult(outcome="PROCEED")

    if status_upper in _STOLEN_LOST_STATUSES:
        reason = "CHEQUE_STOLEN" if status_upper == "STOLEN" else "CHEQUE_LOST"
        log.warning(
            "cheque_series.stolen_or_lost",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            status=status_upper,
        )
        return ChequeSeriesActivityResult(
            outcome="STP_RETURN",
            reason=reason,
            return_reason_code="86",
        )

    if status_upper == _CANCELLED_STATUS:
        log.info("cheque_series.cancelled", instrument_id=inp.instrument_id, bank_id=inp.bank_id)
        return ChequeSeriesActivityResult(
            outcome="STP_RETURN",
            reason="CHEQUE_CANCELLED",
            return_reason_code="20",
        )

    if status_upper == _USED_STATUS:
        log.info("cheque_series.already_used", instrument_id=inp.instrument_id, bank_id=inp.bank_id)
        return ChequeSeriesActivityResult(outcome="HUMAN_REVIEW", reason="CHEQUE_ALREADY_USED")

    log.warning(
        "cheque_series.unknown_status",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        status=status_upper,
    )
    return ChequeSeriesActivityResult(
        outcome="HUMAN_REVIEW",
        reason=f"UNKNOWN_CBS_STATUS:{status_upper}",
    )
