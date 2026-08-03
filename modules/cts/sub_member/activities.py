"""
Temporal activities for Sub-Member Bank clearing notifications and risk monitoring.
These activities are called from SMBChequeProcessingWorkflow after any decision on a
SUB_MEMBER-tagged instrument.

Integration points:
- notify_sub_member_return   → called after STP_RETURN bucket decision
- emit_batch_ledger_update   → called after EVERY decision on sub-member instrument
- check_return_rate_shield   → called by ReturnRateMonitor on a periodic schedule

All activities are async to match Temporal's asyncio worker model.
Config (thresholds, email addresses) comes from config_service — never hardcoded.

db and event_producer are worker-level DI (see modules/cts/worker_activities.py),
matching modules/cts/crl/service.py's CRLService convention for db (asyncpg
pool/connection). Both degrade gracefully when absent — logged at WARNING,
never raised, since Temporal's retry policy has nothing meaningful to retry
against a dependency that was never configured at worker startup.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from temporalio import activity

import structlog

log = structlog.get_logger()

_RETURN_NOTIFICATION_TOPIC = "cts.sub_member.return_notification"
_RISK_EVENT_TOPIC = "cts.sub_member.return_notification"  # same topic, different event_type

# bucket -> ledger column mapping, allowlisted (never build column names from
# unvalidated input — bucket is already checked against this exact key set
# below before any SQL is constructed)
_BUCKET_COLUMNS = {
    "STP_PASS": "stp_pass",
    "STP_RETURN": "stp_return",
    "EYEBALL": "eyeball",
    "FRAUD_HOLD": "fraud_hold",
    "IET_EMERGENCY": "iet_emergency",
}

_LEDGER_READ_SQL = """
SELECT total_received, stp_return
FROM cts.sub_member_batch_ledgers
WHERE bank_id = $1 AND sub_member_id = $2 AND session_date = $3 AND clearing_session = $4
"""

_THRESHOLDS_READ_SQL = """
SELECT return_rate_threshold, soft_hold_threshold
FROM cts.sub_member_banks
WHERE sub_member_id = $1 AND bank_id = $2
"""


@activity.defn
async def notify_sub_member_return(
    instrument_id: str,
    bank_id: str,
    sub_member_id: str,
    return_reason: str,
    bucket: str,
    amount_range: str,
    cheque_number_suffix: str,
    event_producer: Any = None,
) -> dict:
    """
    Tier 1 notification activity — called after STP_RETURN or FRAUD_HOLD decision.

    Publishes to Kafka cts.sub_member.return_notification via the real
    shared/event_bus/producer.py EventProducer. Actual email dispatch is
    handled by notification-service consuming this topic — this activity
    only enqueues the event.

    Returns notification envelope (notification_id, tier, status).
    """
    if len(cheque_number_suffix) > 4:
        raise ValueError(
            f"cheque_number_suffix must be ≤ 4 chars (PII rule): got {len(cheque_number_suffix)}"
        )

    notification_id = f"SMB-NOTIF-{uuid.uuid4().hex[:8].upper()}"
    envelope = {
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

    if event_producer is not None:
        try:
            await event_producer.publish(
                topic=_RETURN_NOTIFICATION_TOPIC,
                event_type="SMB_RETURN_NOTIFICATION",
                payload=envelope,
                schema_version="1.0",
            )
        except Exception as exc:
            log.warning(
                "sub_member.notify_return_degraded",
                sub_member_id=sub_member_id,
                instrument_id=instrument_id,
                error=str(exc),
            )
            envelope["status"] = "PUBLISH_DEGRADED"

    return envelope


@activity.defn
async def emit_batch_ledger_update(
    bank_id: str,
    sub_member_id: str,
    session_date: str,
    clearing_session: str,
    bucket: str,
    db: Any = None,
) -> dict:
    """
    Increments the appropriate bucket counter in sub_member_batch_ledgers.
    Called after every cheque decision for a sub-member-tagged instrument.

    Upserts the ledger row: the first cheque of a (bank, sub-member, date,
    session) combination has no pre-existing row, so INSERT ... ON CONFLICT
    DO UPDATE is used rather than a plain UPDATE.

    Valid bucket values: STP_PASS, STP_RETURN, EYEBALL, FRAUD_HOLD, IET_EMERGENCY
    """
    if bucket not in _BUCKET_COLUMNS:
        raise ValueError(f"Invalid bucket '{bucket}'. Must be one of {set(_BUCKET_COLUMNS)}")

    column = _BUCKET_COLUMNS[bucket]  # allowlisted — safe to interpolate as an identifier
    now = datetime.now(timezone.utc)
    status = "LEDGER_UPDATED"

    if db is not None:
        try:
            upsert_sql = f"""
                INSERT INTO cts.sub_member_batch_ledgers
                    (bank_id, sub_member_id, session_date, clearing_session,
                     total_received, {column})
                VALUES ($1, $2, $3, $4, 1, 1)
                ON CONFLICT (bank_id, sub_member_id, session_date, clearing_session)
                DO UPDATE SET
                    total_received = cts.sub_member_batch_ledgers.total_received + 1,
                    {column} = cts.sub_member_batch_ledgers.{column} + 1,
                    updated_at = $5
            """
            await db.execute(upsert_sql, bank_id, sub_member_id, session_date, clearing_session, now)
        except Exception as exc:
            log.warning(
                "sub_member.ledger_update_degraded",
                sub_member_id=sub_member_id,
                bucket=bucket,
                error=str(exc),
            )
            status = "LEDGER_UPDATE_DEGRADED"

    return {
        "bank_id": bank_id,
        "sub_member_id": sub_member_id,
        "session_date": session_date,
        "clearing_session": clearing_session,
        "bucket_incremented": bucket,
        "status": status,
        "updated_at": now.isoformat(),
    }


@activity.defn
async def check_return_rate_shield(
    bank_id: str,
    sub_member_id: str,
    session_date: str,
    clearing_session: str,
    mock_shield_status: Optional[str] = None,
    db: Any = None,
    event_producer: Any = None,
    immudb_client: Any = None,
) -> dict:
    """
    ReturnRateMonitor activity — called periodically during clearing session,
    and inline from SMBChequeProcessingWorkflow on every STP_RETURN.

    Reads the current sub_member_batch_ledgers row, computes return rate, and
    checks against the sub-member's configured thresholds (from
    sub_member_banks: return_rate_threshold < soft_hold_threshold, enforced
    by a DB CHECK constraint).

    return_rate < return_rate_threshold          -> SAFE
    return_rate_threshold <= rate < soft_hold     -> SOFT_HOLD
    return_rate >= soft_hold_threshold            -> HARD_STOP

    If SOFT_HOLD or HARD_STOP:
    - Publishes SubMemberRiskEvent to Kafka (cts.sub_member.return_notification)
    - Emits Immudb audit event: CTS_SMB_CHEQUE_FORWARDED (risk_event payload)

    Returns shield assessment. Caller (workflow) uses shield_status to gate
    further STP auto-decisions for this sub-member in this session.

    Args:
        mock_shield_status: When provided, overrides the computed shield status
            entirely (skips the DB read). Used in tests to exercise SOFT_HOLD
            and HARD_STOP paths without a DB.
    """
    return_rate = 0.0

    if mock_shield_status is not None:
        shield_status = mock_shield_status
    elif db is not None:
        try:
            ledger_row = await db.fetchrow(
                _LEDGER_READ_SQL, bank_id, sub_member_id, session_date, clearing_session,
            )
            thresholds_row = await db.fetchrow(_THRESHOLDS_READ_SQL, sub_member_id, bank_id)

            if ledger_row is None or thresholds_row is None:
                shield_status = "SAFE"  # no data yet this session — nothing to flag
            else:
                total_received = ledger_row["total_received"]
                stp_return = ledger_row["stp_return"]
                return_rate = (stp_return / total_received) if total_received > 0 else 0.0

                return_rate_threshold = float(thresholds_row["return_rate_threshold"])
                soft_hold_threshold = float(thresholds_row["soft_hold_threshold"])

                if return_rate >= soft_hold_threshold:
                    shield_status = "HARD_STOP"
                elif return_rate >= return_rate_threshold:
                    shield_status = "SOFT_HOLD"
                else:
                    shield_status = "SAFE"
        except Exception as exc:
            log.warning(
                "sub_member.shield_check_degraded",
                sub_member_id=sub_member_id,
                error=str(exc),
            )
            shield_status = "SAFE"  # DB outage must never itself trigger a hold
    else:
        shield_status = "SAFE"

    result: dict = {
        "bank_id": bank_id,
        "sub_member_id": sub_member_id,
        "session_date": session_date,
        "clearing_session": clearing_session,
        "shield_status": shield_status,   # SAFE | SOFT_HOLD | HARD_STOP
        "return_rate": return_rate,
        "action_required": shield_status != "SAFE",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "immudb_event_written": False,
        "escalation_queued": False,
    }

    if shield_status in ("SOFT_HOLD", "HARD_STOP"):
        risk_event_id = f"RISK-{uuid.uuid4().hex[:8].upper()}"
        result["risk_event_id"] = risk_event_id

        if event_producer is not None:
            try:
                await event_producer.publish(
                    topic=_RISK_EVENT_TOPIC,
                    event_type="SUB_MEMBER_RISK_EVENT",
                    payload={
                        "risk_event_id": risk_event_id,
                        "bank_id": bank_id,
                        "sub_member_id": sub_member_id,
                        "shield_status": shield_status,
                        "return_rate": return_rate,
                    },
                    schema_version="1.0",
                )
            except Exception as exc:
                log.warning(
                    "sub_member.risk_event_publish_degraded",
                    sub_member_id=sub_member_id,
                    error=str(exc),
                )

        if immudb_client is not None:
            try:
                from shared.audit.audit_event import AuditEvent, AuditEventType

                event = AuditEvent(
                    event_type=AuditEventType.CTS_SMB_CHEQUE_FORWARDED,
                    bank_id=bank_id,
                    payload={
                        "risk_event_id": risk_event_id,
                        "sub_member_id": sub_member_id,
                        "shield_status": shield_status,
                        "return_rate": return_rate,
                    },
                )
                immudb_client.write_event(event.model_dump())
                result["immudb_event_written"] = True
            except Exception as exc:
                log.warning(
                    "sub_member.risk_event_audit_degraded",
                    sub_member_id=sub_member_id,
                    error=str(exc),
                )

    if shield_status == "HARD_STOP":
        result["escalation_queued"] = True

    return result
