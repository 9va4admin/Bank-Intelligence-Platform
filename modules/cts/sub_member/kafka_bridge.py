"""
Kafka bridge for sub-member return notifications.
Publishes to topic: cts.sub_member.return_notification

PII rules enforced here:
- amount_range only — no exact paise amounts
- cheque_number_suffix (last 4) — no full cheque number
- No customer names, no full account numbers
"""
import uuid
from datetime import datetime, timezone

from .models import SubMemberBank, SubMemberBatchLedger, SubMemberReturn


class SubMemberKafkaBridge:
    """
    Builds and publishes Kafka event envelopes for sub-member clearing events.
    The injected producer is the shared event_bus producer from shared/event_bus/producer.py.
    Constructor injection keeps this testable without real Kafka.
    """

    TOPIC = "cts.sub_member.return_notification"
    SCHEMA_VERSION = "1.0"

    def __init__(self, producer):
        self._producer = producer

    def publish_return_event(
        self,
        sub_member: SubMemberBank,
        return_item: SubMemberReturn,
        bank_id: str,
    ) -> dict:
        """
        Tier 1 trigger — fired immediately after each STP_RETURN decision.
        Downstream: notification-service reads this and dispatches Tier 1 email.
        """
        envelope = self._envelope(
            event_type="SUB_MEMBER_CHEQUE_RETURN",
            bank_id=bank_id,
            payload={
                "sub_member_id": sub_member.sub_member_id,
                "bank_name": sub_member.bank_name,
                "instrument_id": return_item.instrument_id,
                "cheque_number_suffix": return_item.cheque_number_suffix,
                "return_reason": return_item.return_reason,
                "bucket": return_item.bucket.value,
                "amount_range": return_item.amount_range,       # never exact amount
                "returned_at": return_item.returned_at.isoformat(),
                "notification_template": "RETURN_IMMEDIATE",
                "recipient_email": sub_member.branch_manager_email,
            },
        )
        key = f"{bank_id}:{sub_member.sub_member_id}"
        self._producer.send(self.TOPIC, key=key, value=envelope)
        return envelope

    def publish_batch_complete(
        self,
        sub_member: SubMemberBank,
        ledger: SubMemberBatchLedger,
        bank_id: str,
    ) -> dict:
        """
        End-of-session signal — triggers Tier 2 batch summary email with CSV.
        """
        envelope = self._envelope(
            event_type="SUB_MEMBER_SESSION_COMPLETE",
            bank_id=bank_id,
            payload={
                "sub_member_id": sub_member.sub_member_id,
                "bank_name": sub_member.bank_name,
                "session_date": ledger.session_date,
                "clearing_session": ledger.clearing_session,
                "total_received": ledger.total_received,
                "stp_pass": ledger.stp_pass,
                "stp_return": ledger.stp_return,
                "eyeball": ledger.eyeball,
                "fraud_hold": ledger.fraud_hold,
                "iet_emergency": ledger.iet_emergency,
                "return_rate_pct": round(ledger.return_rate * 100, 4),
                "notification_template": "BATCH_SUMMARY",
                "recipient_email": sub_member.branch_manager_email,
                "cc_email": sub_member.ops_head_email,
            },
        )
        key = f"{bank_id}:{sub_member.sub_member_id}"
        self._producer.send(self.TOPIC, key=key, value=envelope)
        return envelope

    def publish_risk_event(
        self,
        sub_member: SubMemberBank,
        ledger: SubMemberBatchLedger,
        bank_id: str,
        shield_status: str,
    ) -> dict:
        """
        Emitted when ReturnRateShield detects SOFT_HOLD or HARD_STOP.
        Triggers Tier 3 GM escalation + Immudb SubMemberRiskEvent audit write.
        """
        envelope = self._envelope(
            event_type="SUB_MEMBER_RISK_EVENT",
            bank_id=bank_id,
            payload={
                "sub_member_id": sub_member.sub_member_id,
                "bank_name": sub_member.bank_name,
                "shield_status": shield_status,
                "return_rate_pct": round(ledger.return_rate * 100, 4),
                "return_rate_threshold_pct": round(sub_member.return_rate_threshold * 100, 4),
                "soft_hold_threshold_pct": round(sub_member.soft_hold_threshold * 100, 4),
                "total_received": ledger.total_received,
                "stp_return": ledger.stp_return,
                "session_date": ledger.session_date,
                "clearing_session": ledger.clearing_session,
                "notification_template": "THRESHOLD_ALERT",
                "recipient_email": sub_member.gm_email,
                "cc_email": sub_member.ops_head_email,
            },
        )
        key = f"{bank_id}:{sub_member.sub_member_id}"
        self._producer.send(self.TOPIC, key=key, value=envelope)
        return envelope

    # ── Private ──────────────────────────────────────────────────────────────

    def _envelope(self, event_type: str, bank_id: str, payload: dict) -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "schema_version": self.SCHEMA_VERSION,
            "event_type": event_type,
            "bank_id": bank_id,
            "topic": self.TOPIC,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
