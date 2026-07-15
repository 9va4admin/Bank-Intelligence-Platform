"""
Temporal activities specific to the SMB forwarding hop.

Called by SMBForwardingWorkflow (Sponsor Bank side):
  - validate_smb_forwarding_window  — checks IET headroom + SMB active status
  - write_forwarding_log_start      — inserts/updates smb_forwarding_log (FORWARDING)
  - write_forwarding_log_complete   — updates smb_forwarding_log (COMPLETED / FAILED)
  - write_smb_forwarding_audit      — Immudb write for the forwarding hop audit trail

All thresholds (min IET headroom) come from config_service — never hardcoded.
All PII rules enforced: no full account numbers, no exact amounts, no customer names.

db is worker-level DI (asyncpg pool/connection — see modules/cts/worker_activities.py),
matching modules/cts/crl/service.py's CRLService convention. immudb_client is likewise
worker-level DI. Both degrade gracefully when absent: db-dependent activities log a
warning and skip the real write/read rather than raising, since Temporal's retry policy
has nothing meaningful to retry against a dependency that was never configured.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from temporalio import activity

import structlog

log = structlog.get_logger()

_SMB_ACTIVE_SQL = """
SELECT is_active FROM cts.sub_member_banks WHERE sub_member_id = $1 AND bank_id = $2
"""

_INSERT_FORWARDING_LOG_SQL = """
INSERT INTO cts.smb_forwarding_log
    (forwarding_id, bank_id, sponsor_bank_id, sub_member_id, instrument_id,
     micr_prefix_matched, forwarding_status, iet_deadline_utc)
VALUES ($1, $2, $2, $3, $4, $5, 'FORWARDING', $6)
"""

_UPDATE_FORWARDING_LOG_COMPLETE_SQL = """
UPDATE cts.smb_forwarding_log
SET forwarding_status = $1, terminal_decision = $2, smb_workflow_id = $3, completed_at = $4
WHERE forwarding_id = $5 AND bank_id = $6
"""


@activity.defn
async def validate_smb_forwarding_window(
    instrument_id: str,
    bank_id: str,
    sub_member_id: str,
    iet_deadline_utc: str,
    db: Any = None,
) -> dict:
    """
    Validates two things before proceeding with forwarding:
      1. The SMB is active (not suspended) in cts.sub_member_banks.
      2. There is enough IET headroom to safely complete an SMB forwarding hop.

    IET headroom threshold: config_service.get("cts.smb.min_iet_headroom_s")
    Default: 300 seconds (5 minutes). Below this, short-circuit to IET_EMERGENCY.

    Returns:
      forwarding_id: UUID assigned to this forwarding attempt (pre-allocated)
      safe_to_forward: bool
      iet_seconds_remaining: float
      smb_active: bool
      reason: human-readable reason when safe_to_forward = False
    """
    from shared.config.config_service import config_service

    forwarding_id = str(uuid.uuid4())

    # Parse IET deadline
    try:
        deadline = datetime.fromisoformat(iet_deadline_utc.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        iet_seconds_remaining = (deadline - now).total_seconds()
    except ValueError:
        return {
            "forwarding_id": forwarding_id,
            "safe_to_forward": False,
            "iet_seconds_remaining": 0.0,
            "smb_active": False,
            "reason": f"INVALID_IET_DEADLINE: {iet_deadline_utc}",
        }

    # Check minimum headroom — config_service.get() raises ConfigKeyNotFoundError
    # for an unseeded Layer 3 key rather than returning None, so `or 300` alone
    # would never actually catch the missing-config case; this sits on the
    # IET-safety-critical path so a missing key must degrade to the
    # documented default, never crash the whole forwarding decision.
    try:
        min_headroom = await config_service.get("cts.smb.min_iet_headroom_s") or 300
    except Exception:
        min_headroom = 300
    if iet_seconds_remaining < min_headroom:
        return {
            "forwarding_id": forwarding_id,
            "safe_to_forward": False,
            "iet_seconds_remaining": iet_seconds_remaining,
            "smb_active": True,  # unknown — but irrelevant, time is out
            "reason": (
                f"INSUFFICIENT_IET_HEADROOM: {iet_seconds_remaining:.0f}s remaining, "
                f"need {min_headroom}s"
            ),
        }

    smb_active = True  # default when db unavailable — matches pre-DI behaviour;
    # an outage here must never itself become the reason a live SMB gets
    # blocked, and IET safety is the higher-priority invariant.
    if db is not None:
        try:
            row = await db.fetchval(_SMB_ACTIVE_SQL, sub_member_id, bank_id)
            if row is not None:
                smb_active = bool(row)
        except Exception as exc:
            log.warning(
                "smb_forwarding.active_check_degraded",
                sub_member_id=sub_member_id,
                bank_id=bank_id,
                error=str(exc),
            )

    if not smb_active:
        return {
            "forwarding_id": forwarding_id,
            "safe_to_forward": False,
            "iet_seconds_remaining": iet_seconds_remaining,
            "smb_active": False,
            "reason": f"SMB_SUSPENDED: {sub_member_id}",
        }

    return {
        "forwarding_id": forwarding_id,
        "safe_to_forward": True,
        "iet_seconds_remaining": iet_seconds_remaining,
        "smb_active": True,
        "reason": "OK",
    }


@activity.defn
async def write_forwarding_log_start(
    forwarding_id: str,
    instrument_id: str,
    bank_id: str,
    sub_member_id: str,
    micr_prefix_matched: str,
    iet_deadline_utc: str,
    db: Any = None,
) -> dict:
    """
    Inserts a row into cts.smb_forwarding_log with status = FORWARDING.

    sponsor_bank_id is the same value as bank_id here — SMBForwardingWorkflow
    runs on the sponsor's own task queue and passes input.bank_id, which IS
    the sponsor bank's ID (see smb_forwarding_workflow.py's SMBChequeInput
    construction: sponsor_bank_id=input.bank_id).
    """
    now = datetime.now(timezone.utc).isoformat()

    if db is not None:
        try:
            deadline = datetime.fromisoformat(iet_deadline_utc.replace("Z", "+00:00"))
            await db.execute(
                _INSERT_FORWARDING_LOG_SQL,
                forwarding_id, bank_id, sub_member_id, instrument_id,
                micr_prefix_matched, deadline,
            )
        except Exception as exc:
            log.warning(
                "smb_forwarding.log_start_degraded",
                forwarding_id=forwarding_id,
                instrument_id=instrument_id,
                error=str(exc),
            )

    return {
        "forwarding_id": forwarding_id,
        "instrument_id": instrument_id,
        "bank_id": bank_id,
        "sub_member_id": sub_member_id,
        "micr_prefix_matched": micr_prefix_matched,
        "iet_deadline_utc": iet_deadline_utc,
        "forwarding_status": "FORWARDING",
        "written_at": now,
    }


@activity.defn
async def write_forwarding_log_complete(
    forwarding_id: str,
    bank_id: str,
    terminal_decision: str,
    smb_workflow_id: str,
    db: Any = None,
) -> dict:
    """
    Updates cts.smb_forwarding_log row to COMPLETED (or FAILED on IET_EMERGENCY).
    Sets terminal_decision, smb_workflow_id, completed_at.
    """
    status = "COMPLETED" if terminal_decision != "IET_EMERGENCY" else "FAILED"
    now = datetime.now(timezone.utc)

    if db is not None:
        try:
            await db.execute(
                _UPDATE_FORWARDING_LOG_COMPLETE_SQL,
                status, terminal_decision, smb_workflow_id, now, forwarding_id, bank_id,
            )
        except Exception as exc:
            log.warning(
                "smb_forwarding.log_complete_degraded",
                forwarding_id=forwarding_id,
                error=str(exc),
            )

    return {
        "forwarding_id": forwarding_id,
        "forwarding_status": status,
        "terminal_decision": terminal_decision,
        "smb_workflow_id": smb_workflow_id,
        "completed_at": now.isoformat(),
    }


@activity.defn
async def write_smb_forwarding_audit(
    forwarding_id: str,
    bank_id: str,
    terminal_decision: str,
    completion_type: str,
    immudb_client: Any = None,
) -> dict:
    """
    Writes an Immudb audit event for the SMB forwarding hop.

    Event type: SMB_CHEQUE_FORWARDED
    Written to: Immudb collection cts_events (bank_id scoped)
    HSM-signed before write (shared/audit/immudb_client.py)

    completion_type: COMPLETED | SHORT_CIRCUIT_IET_HEADROOM | FAILED
    """
    from shared.audit.audit_event import AuditEvent, AuditEventType

    event = AuditEvent(
        event_type=AuditEventType.CTS_SMB_CHEQUE_FORWARDED,
        bank_id=bank_id,
        payload={
            "forwarding_id": forwarding_id,
            "terminal_decision": terminal_decision,
            "completion_type": completion_type,
        },
    )

    written = False
    if immudb_client is not None:
        try:
            immudb_client.write_event(event.model_dump())
            written = True
        except Exception as exc:
            log.warning(
                "smb_forwarding.audit_write_degraded",
                forwarding_id=forwarding_id,
                error=str(exc),
            )

    return {
        "audit_event_id": event.event_id,
        "event_type": event.event_type,
        "written": written,
    }
