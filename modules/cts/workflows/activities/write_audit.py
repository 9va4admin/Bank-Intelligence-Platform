"""
write_audit activity — append a CTS decision event to the immutable audit trail.

Every write to YugabyteDB that modifies a cheque record must be followed by
an Immudb audit write. This activity enforces that invariant for CTS decisions.

Uses AUDIT_RETRY policy (unlimited retries) — audit write must eventually succeed.
The event is HSM-signed before Immudb write (handled inside ImmudbClient).
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()

_VALID_EVENT_TYPES = {
    "CTS_STP_CONFIRM",
    "CTS_STP_RETURN",
    "CTS_HUMAN_REVIEW_QUEUED",
    "CTS_HUMAN_REVIEW_DECIDED",
    "CTS_IET_EMERGENCY_FILED",
    "CTS_NGCH_FILED",
    "CTS_VAULT_SYNC_COMPLETE",
    "CTS_VAULT_SYNC_FAILED",
}


class WriteAuditInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_type: str
    bank_id: str
    instrument_id: Optional[str] = None
    payload: dict[str, Any]


class WriteAuditResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    success: bool
    immudb_tx_id: Optional[str] = None


@activity.defn
async def write_audit(
    inp: WriteAuditInput,
    immudb_client=None,
) -> WriteAuditResult:
    """
    Write a CTS audit event to Immudb.

    Uses AUDIT_RETRY policy (caller's responsibility in Temporal workflow).
    Validates event_type against known set — unknown types log a warning but still write.
    """
    if inp.event_type not in _VALID_EVENT_TYPES:
        log.warning(
            "write_audit.unknown_event_type",
            event_type=inp.event_type,
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )

    try:
        tx_id = await immudb_client.write(
            collection=f"cts_{inp.bank_id}",
            event_type=inp.event_type,
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            payload=inp.payload,
        )
    except Exception as exc:
        log.error(
            "write_audit.immudb_error",
            event_type=inp.event_type,
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        raise   # re-raise so Temporal retries with AUDIT_RETRY policy

    log.info(
        "write_audit.written",
        event_type=inp.event_type,
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        immudb_tx_id=tx_id,
    )
    return WriteAuditResult(success=True, immudb_tx_id=tx_id)
