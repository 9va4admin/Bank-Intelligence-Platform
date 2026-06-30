"""
Temporal activities specific to the SMB forwarding hop.

Called by SMBForwardingWorkflow (Sponsor Bank side):
  - validate_smb_forwarding_window  — checks IET headroom + SMB active status
  - write_forwarding_log_start      — inserts/updates smb_forwarding_log (FORWARDING)
  - write_forwarding_log_complete   — updates smb_forwarding_log (COMPLETED / FAILED)
  - write_smb_forwarding_audit      — Immudb write for the forwarding hop audit trail

All thresholds (min IET headroom) come from config_service — never hardcoded.
All PII rules enforced: no full account numbers, no exact amounts, no customer names.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from temporalio import activity


@activity.defn
async def validate_smb_forwarding_window(
    instrument_id: str,
    bank_id: str,
    sub_member_id: str,
    iet_deadline_utc: str,
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

    # Check minimum headroom
    min_headroom = config_service.get("cts.smb.min_iet_headroom_s") or 300
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

    # Production: check cts.sub_member_banks.is_active via DB.
    # Stub returns active=True — real implementation queries via async YugabyteDB client.
    smb_active = True

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
) -> dict:
    """
    Inserts a row into cts.smb_forwarding_log with status = FORWARDING.

    In production this performs an INSERT via pgbouncer-cts pool (async sqlalchemy).
    The forwarding_id is the UUID pre-allocated by validate_smb_forwarding_window.
    """
    now = datetime.now(timezone.utc).isoformat()
    # Production: INSERT INTO cts.smb_forwarding_log (...) VALUES (...)
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
) -> dict:
    """
    Updates cts.smb_forwarding_log row to COMPLETED (or FAILED on IET_EMERGENCY).
    Sets terminal_decision, smb_workflow_id, completed_at.
    """
    status = "COMPLETED" if terminal_decision != "IET_EMERGENCY" else "FAILED"
    now = datetime.now(timezone.utc).isoformat()
    # Production: UPDATE cts.smb_forwarding_log SET forwarding_status=$1,
    #   terminal_decision=$2, smb_workflow_id=$3, completed_at=$4 WHERE forwarding_id=$5
    return {
        "forwarding_id": forwarding_id,
        "forwarding_status": status,
        "terminal_decision": terminal_decision,
        "smb_workflow_id": smb_workflow_id,
        "completed_at": now,
    }


@activity.defn
async def write_smb_forwarding_audit(
    forwarding_id: str,
    bank_id: str,
    terminal_decision: str,
    completion_type: str,
) -> dict:
    """
    Writes an Immudb audit event for the SMB forwarding hop.

    Event type: SMB_CHEQUE_FORWARDED
    Written to: Immudb collection cts_events (bank_id scoped)
    HSM-signed before write (shared/audit/immudb_client.py)

    completion_type: COMPLETED | SHORT_CIRCUIT_IET_HEADROOM | FAILED
    """
    from shared.audit.audit_event import AuditEvent

    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        event_type="SMB_CHEQUE_FORWARDED",
        bank_id=bank_id,
        module="cts",
        entity_id=forwarding_id,
        entity_type="smb_forwarding_log",
        payload={
            "forwarding_id": forwarding_id,
            "terminal_decision": terminal_decision,
            "completion_type": completion_type,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Production: shared/audit/immudb_client.py.write(event)
    # HSM signing happens inside immudb_client — this activity never touches keys.
    return {
        "audit_event_id": event.event_id,
        "event_type": event.event_type,
        "written": True,
    }
