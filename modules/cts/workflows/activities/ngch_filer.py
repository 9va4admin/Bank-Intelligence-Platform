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

    return NGCHFilerResult(
        acknowledgement_id=response.get("acknowledgement_id", ""),
        status=response.get("status", ""),
        filed_decision=inp.decision,
    )
