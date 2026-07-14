"""
Temporal activity stubs for Sub-Member Bank clearing notifications and risk monitoring.
These activities are called from ChequeProcessingWorkflow after any decision on a
SUB_MEMBER-tagged instrument.

Integration points:
- notify_sub_member_return   → called after STP_RETURN bucket decision
- emit_batch_ledger_update   → called after EVERY decision on sub-member instrument
- check_return_rate_shield   → called by ReturnRateMonitor on a periodic schedule

All activities are async to match Temporal's asyncio worker model.
Config (thresholds, email addresses) comes from config_service — never hardcoded.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from temporalio import activity


@activity.defn
async def notify_sub_member_return(
    instrument_id: str,
    bank_id: str,
    sub_member_id: str,
    return_reason: str,
    bucket: str,
    amount_range: str,
    cheque_number_suffix: str,
) -> dict:
    """
    Tier 1 notification activity — called after STP_RETURN or FRAUD_HOLD decision.

    Builds the Tier 1 email payload and publishes to Kafka
    cts.sub_member.return_notification. Actual email dispatch is handled by
    notification-service — this activity only enqueues the event.

    Returns notification envelope (notification_id, tier, status).
    """
    if len(cheque_number_suffix) > 4:
        raise ValueError(
            f"cheque_number_suffix must be ≤ 4 chars (PII rule): got {len(cheque_number_suffix)}"
        )

    notification_id = f"SMB-NOTIF-{uuid.uuid4().hex[:8].upper()}"
    return {
        "notification_id": notification_id,
        "tier": "TIER1_IMMEDIATE",
        "template": "RETURN_IMMEDIATE",
        "bank_id": bank_id,
        "sub_member_id": sub_member_id,
        "instrument_id": instrument_id,
        "cheque_number_suffix": cheque_number_suffix,
        "return_reason": return_reason,
        "bucket": bucket,
        "amount_range": amount_range,
        "status": "QUEUED",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }


@activity.defn
async def emit_batch_ledger_update(
    bank_id: str,
    sub_member_id: str,
    session_date: str,
    clearing_session: str,
    bucket: str,
) -> dict:
    """
    Increments the appropriate bucket counter in sub_member_batch_ledgers.
    Called after every cheque decision for a sub-member-tagged instrument.

    In production this performs an atomic UPDATE ... SET stp_return = stp_return + 1
    via pgbouncer-cts pool. Here we return the increment confirmation for testability.

    Valid bucket values: STP_PASS, STP_RETURN, EYEBALL, FRAUD_HOLD, IET_EMERGENCY
    """
    valid_buckets = {"STP_PASS", "STP_RETURN", "EYEBALL", "FRAUD_HOLD", "IET_EMERGENCY"}
    if bucket not in valid_buckets:
        raise ValueError(f"Invalid bucket '{bucket}'. Must be one of {valid_buckets}")

    return {
        "bank_id": bank_id,
        "sub_member_id": sub_member_id,
        "session_date": session_date,
        "clearing_session": clearing_session,
        "bucket_incremented": bucket,
        "status": "LEDGER_UPDATED",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@activity.defn
async def check_return_rate_shield(
    bank_id: str,
    sub_member_id: str,
    session_date: str,
    clearing_session: str,
    mock_shield_status: Optional[str] = None,
) -> dict:
    """
    ReturnRateMonitor activity — called periodically during clearing session.

    Reads current sub_member_batch_ledgers row, computes return rate, and
    checks against the sub-member's configured thresholds (from sub_member_banks row).

    If SOFT_HOLD or HARD_STOP:
    - Sets soft_hold_active = TRUE on the ledger row
    - Sets risk_event_emitted = TRUE
    - Publishes SubMemberRiskEvent to Kafka (cts.sub_member.return_notification)
    - Emits Immudb audit event: SUB_MEMBER_RISK_EVENT

    Returns shield assessment. Caller (workflow) uses shield_status to gate
    further STP auto-decisions for this sub-member in this session.

    Args:
        mock_shield_status: When provided, overrides the computed shield status.
            Used in tests to exercise SOFT_HOLD and HARD_STOP paths without a DB.
    """
    # Stub implementation — production reads from YugabyteDB via config-aware DB client.
    # Return structure is the contract that callers depend on.
    shield_status = mock_shield_status if mock_shield_status is not None else "SAFE"

    result: dict = {
        "bank_id": bank_id,
        "sub_member_id": sub_member_id,
        "session_date": session_date,
        "clearing_session": clearing_session,
        "shield_status": shield_status,   # SAFE | SOFT_HOLD | HARD_STOP
        "return_rate": 0.0,
        "action_required": shield_status != "SAFE",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "immudb_event_written": False,
        "escalation_queued": False,
    }

    if shield_status in ("SOFT_HOLD", "HARD_STOP"):
        result["risk_event_id"] = f"RISK-{uuid.uuid4().hex[:8].upper()}"
        result["immudb_event_written"] = True

    if shield_status == "HARD_STOP":
        result["escalation_queued"] = True

    return result
