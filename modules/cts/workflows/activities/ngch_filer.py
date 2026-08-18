"""
NGCH filer activity — the ONLY place in ASTRA that calls NGCHAdapter.file_decision().

Exactly-once: workflow_id is the idempotency key passed to NGCH.
Audit event published to cts.decisions.{bank_id} after every successful filing.
DuplicateFilingError propagates to Temporal as non-retryable.
NGCHUnavailableError propagates to Temporal for retry with backoff.
"""
from typing import Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from temporalio import activity

from modules.cts.mcp.ngch_adapter import DuplicateFilingError, NGCHUnavailableError

log = structlog.get_logger()


class NGCHFilerInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    workflow_id: str
    decision: Literal["CONFIRM", "RETURN"]
    # URRBCH return reason code — required when decision == "RETURN"
    return_reason_code: Optional[str] = None
    # False = CBS must suppress return charge for this instrument
    is_customer_fault: Optional[bool] = None
    # For leaf lifecycle writes — set by ChequeProcessingWorkflow
    account_number: Optional[str] = None
    cheque_number: Optional[str] = None


class NGCHFilerResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    acknowledgement_id: str
    status: str
    filed_decision: str


@activity.defn
async def file_to_ngch(
    inp: NGCHFilerInput,
    ngch_adapter,
    event_producer,
    cheque_leaf_vault=None,
) -> NGCHFilerResult:
    """
    File cheque decision to NGCH. Exactly-once via idempotency_key = workflow_id.

    Raises DuplicateFilingError (non-retryable): already filed with this key.
    Raises NGCHUnavailableError (retryable): Temporal retries with NGCH_FILING_RETRY policy.
    """
    try:
        response = await ngch_adapter.file_decision(
            instrument_id=inp.instrument_id,
            decision=inp.decision,
            workflow_id=inp.workflow_id,
        )
    except DuplicateFilingError:
        log.warning(
            "ngch_filer.duplicate_detected",
            instrument_id=inp.instrument_id,
            workflow_id=inp.workflow_id,
        )
        raise
    except NGCHUnavailableError:
        log.error(
            "ngch_filer.ngch_unavailable",
            instrument_id=inp.instrument_id,
            workflow_id=inp.workflow_id,
        )
        raise

    log.info(
        "ngch_filer.filed",
        instrument_id=inp.instrument_id,
        decision=inp.decision,
        acknowledgement_id=response.get("acknowledgement_id"),
    )

    await event_producer.publish(
        topic=f"cts.decisions.{inp.bank_id}",
        event_type="CTS_NGCH_FILED",
        payload={
            "instrument_id": inp.instrument_id,
            "decision": inp.decision,
            "acknowledgement_id": response.get("acknowledgement_id"),
            "workflow_id": inp.workflow_id,
        },
        schema_version="1.0",
    )

    # Update cheque leaf vault — fire-and-forget; never blocks the return value
    if cheque_leaf_vault is not None and inp.account_number and inp.cheque_number:
        try:
            if inp.decision == "CONFIRM":
                await cheque_leaf_vault.mark_paid(
                    account_number=inp.account_number,
                    cheque_number=inp.cheque_number,
                    instrument_id=inp.instrument_id,
                )
            else:
                await cheque_leaf_vault.mark_returned(
                    account_number=inp.account_number,
                    cheque_number=inp.cheque_number,
                    instrument_id=inp.instrument_id,
                    return_reason_code=inp.return_reason_code,
                )
        except Exception as _leaf_exc:
            log.warning(
                "ngch_filer.leaf_status_update_failed",
                instrument_id=inp.instrument_id,
                decision=inp.decision,
                error=str(_leaf_exc),
            )

    return NGCHFilerResult(
        acknowledgement_id=response.get("acknowledgement_id", ""),
        status=response.get("status", ""),
        filed_decision=inp.decision,
    )
