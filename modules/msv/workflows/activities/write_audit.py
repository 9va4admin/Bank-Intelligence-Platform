"""
write_audit activity for MSV — appends an MSV event to the immutable audit trail.

Every MSV decision and enrollment event must be written to Immudb.
Uses AUDIT_RETRY policy (unlimited retries) — audit writes must eventually succeed.
The event is HSM-signed before Immudb write (handled inside ImmudbClient).

PII rules:
  - instrument_id: safe to include (internal reference, not customer PII)
  - account number: NEVER included — only account_hash in payload
  - amount: NEVER included — only amount_range bucket
  - customer name: NEVER included — only name_masked ("P***")
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()

_VALID_EVENT_TYPES = {
    "MSV_VALIDATED",
    "MSV_VALIDATION_DEGRADED",
    "MSV_ENROLLMENT_COMPLETE",
    "MSV_ENROLLMENT_FAILED",
    "MSV_ENROLLMENT_SKIPPED",
    "MSV_CBS_SYNC_COMPLETE",
    "MSV_CBS_SYNC_DEGRADED",
    "MSV_SIGNATORY_REVOKED",
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
    Write an MSV audit event to Immudb.

    Uses AUDIT_RETRY policy (caller's responsibility in Temporal workflow).
    Validates event_type against known set — unknown types log a warning but still write.
    Re-raises on Immudb failure so Temporal can retry.
    """
    if inp.event_type not in _VALID_EVENT_TYPES:
        log.warning(
            "msv.write_audit.unknown_event_type",
            event_type=inp.event_type,
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )

    try:
        tx_id = await immudb_client.write(
            collection=f"msv_{inp.bank_id}",
            event_type=inp.event_type,
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            payload=inp.payload,
        )
    except Exception as exc:
        log.error(
            "msv.write_audit.immudb_error",
            event_type=inp.event_type,
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        raise   # re-raise so Temporal retries with AUDIT_RETRY policy

    log.info(
        "msv.write_audit.written",
        event_type=inp.event_type,
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        immudb_tx_id=tx_id,
    )
    return WriteAuditResult(success=True, immudb_tx_id=tx_id)
