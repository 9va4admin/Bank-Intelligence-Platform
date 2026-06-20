"""Tests for SubMemberKafkaBridge."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from modules.cts.sub_member.models import (
    SubMemberBank, SubMemberBatchLedger, SubMemberReturn, ClearingBucket
)
from modules.cts.sub_member.kafka_bridge import SubMemberKafkaBridge


@pytest.fixture
def producer():
    return MagicMock()


@pytest.fixture
def smb():
    return SubMemberBank(
        sub_member_id="SMB-MH-001",
        bank_name="Vasavi Co-op Bank",
        sponsor_bank_id="SVCB-DIRECT-001",
        micr_prefix="400053",
        ifsc_prefix="VASB",
        branch_manager_email="bm@vasavi.bank",
        ops_head_email="ops@vasavi.bank",
        gm_email="gm@vasavi.bank",
        return_rate_threshold=0.15,
        soft_hold_threshold=0.25,
    )


@pytest.fixture
def ledger(smb):
    l = SubMemberBatchLedger(
        sub_member_id=smb.sub_member_id,
        session_date="2026-06-19",
        clearing_session="MORNING",
    )
    l.total_received = 100
    l.stp_pass = 70
    l.stp_return = 30
    return l


@pytest.fixture
def return_item(smb):
    return SubMemberReturn(
        instrument_id="CHQ-IN-20260619-0042",
        sub_member_id=smb.sub_member_id,
        return_reason="SIGNATURE_MISMATCH",
        bucket=ClearingBucket.STP_RETURN,
        amount_range="₹[1L-5L]",
        cheque_number_suffix="7890",
        returned_at=datetime(2026, 6, 19, 11, 30),
    )


@pytest.fixture
def bridge(producer):
    return SubMemberKafkaBridge(producer)


class TestSubMemberKafkaBridge:
    def test_publish_return_event_calls_producer(self, bridge, producer, smb, return_item):
        bridge.publish_return_event(smb, return_item, "BANK-001")
        producer.send.assert_called_once()

    def test_return_event_uses_correct_topic(self, bridge, producer, smb, return_item):
        bridge.publish_return_event(smb, return_item, "BANK-001")
        args = producer.send.call_args
        assert args[0][0] == "cts.sub_member.return_notification"

    def test_return_event_envelope_has_schema_version(self, bridge, smb, return_item):
        env = bridge.publish_return_event(smb, return_item, "BANK-001")
        assert env["schema_version"] == "1.0"

    def test_return_event_has_no_exact_amount(self, bridge, smb, return_item):
        env = bridge.publish_return_event(smb, return_item, "BANK-001")
        payload = env["payload"]
        assert "amount_range" in payload
        assert "₹[" in payload["amount_range"]
        assert "amount_paise" not in payload
        assert "exact" not in str(payload).lower()

    def test_return_event_uses_template_return_immediate(self, bridge, smb, return_item):
        env = bridge.publish_return_event(smb, return_item, "BANK-001")
        assert env["payload"]["notification_template"] == "RETURN_IMMEDIATE"

    def test_publish_batch_complete_uses_correct_template(self, bridge, smb, ledger):
        env = bridge.publish_batch_complete(smb, ledger, "BANK-001")
        assert env["payload"]["notification_template"] == "BATCH_SUMMARY"

    def test_batch_complete_has_return_rate_not_raw_counts_only(self, bridge, smb, ledger):
        env = bridge.publish_batch_complete(smb, ledger, "BANK-001")
        assert "return_rate_pct" in env["payload"]
        assert env["payload"]["return_rate_pct"] == 30.0

    def test_batch_complete_no_exact_amounts(self, bridge, smb, ledger):
        env = bridge.publish_batch_complete(smb, ledger, "BANK-001")
        payload_str = str(env["payload"])
        assert "amount_paise" not in payload_str

    def test_publish_risk_event_uses_threshold_alert_template(self, bridge, smb, ledger):
        env = bridge.publish_risk_event(smb, ledger, "BANK-001", "SOFT_HOLD")
        assert env["payload"]["notification_template"] == "THRESHOLD_ALERT"

    def test_risk_event_includes_shield_status(self, bridge, smb, ledger):
        env = bridge.publish_risk_event(smb, ledger, "BANK-001", "HARD_STOP")
        assert env["payload"]["shield_status"] == "HARD_STOP"

    def test_envelope_has_event_id(self, bridge, smb, return_item):
        env = bridge.publish_return_event(smb, return_item, "BANK-001")
        assert "event_id" in env
        assert len(env["event_id"]) > 0

    def test_key_format_is_bank_sub_member(self, bridge, producer, smb, return_item):
        bridge.publish_return_event(smb, return_item, "BANK-001")
        call_kwargs = producer.send.call_args[1]
        assert call_kwargs["key"] == "BANK-001:SMB-MH-001"
