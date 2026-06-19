"""
Consolidated tests for CTS Sub-Member Bank framework.
Covers: models, MICR router, notifications, risk shield.
"""
import pytest
from datetime import datetime, date

from modules.cts.sub_member.models import (
    PrincipalTag,
    ClearingBucket,
    SubMemberBank,
    SubMemberBatchLedger,
    SubMemberReturn,
)
from modules.cts.sub_member.router import MICRPrefixRouter
from modules.cts.sub_member.notifications import BatchRejectionEmailer, NotificationTier
from modules.cts.sub_member.risk_shield import ReturnRateShield, ShieldStatus


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def smb_vasavi():
    return SubMemberBank(
        sub_member_id="SMB-MH-001",
        bank_name="Vasavi Co-op Bank",
        sponsor_bank_id="SVCB-DIRECT-001",
        micr_prefix="400053",
        ifsc_prefix="VASB",
        branch_manager_email="bm.andheri@vasavi.bank",
        ops_head_email="ops@vasavi.bank",
        gm_email="gm@vasavi.bank",
        return_rate_threshold=0.15,
        soft_hold_threshold=0.25,
    )


@pytest.fixture
def smb_saraswat():
    return SubMemberBank(
        sub_member_id="SMB-MH-002",
        bank_name="Saraswat Co-op Bank",
        sponsor_bank_id="SVCB-DIRECT-001",
        micr_prefix="400083",
        ifsc_prefix="SRCB",
        branch_manager_email="bm.fort@saraswat.bank",
        ops_head_email="ops@saraswat.bank",
        gm_email="gm@saraswat.bank",
        return_rate_threshold=0.12,
        soft_hold_threshold=0.20,
    )


@pytest.fixture
def routing_table(smb_vasavi, smb_saraswat):
    return {
        smb_vasavi.micr_prefix: smb_vasavi,
        smb_saraswat.micr_prefix: smb_saraswat,
    }


@pytest.fixture
def router(routing_table):
    return MICRPrefixRouter(routing_table)


@pytest.fixture
def sample_return(smb_vasavi):
    return SubMemberReturn(
        instrument_id="CHQ-IN-20260619-0042",
        sub_member_id=smb_vasavi.sub_member_id,
        return_reason="SIGNATURE_MISMATCH",
        bucket=ClearingBucket.STP_RETURN,
        amount_range="₹[1L-5L]",
        cheque_number_suffix="7890",
        returned_at=datetime(2026, 6, 19, 11, 30, 0),
    )


@pytest.fixture
def ledger_normal(smb_vasavi):
    ledger = SubMemberBatchLedger(
        sub_member_id=smb_vasavi.sub_member_id,
        session_date="2026-06-19",
        clearing_session="MORNING",
    )
    ledger.total_received = 100
    ledger.stp_pass = 88
    ledger.stp_return = 10
    ledger.eyeball = 2
    return ledger


@pytest.fixture
def ledger_high_return(smb_vasavi):
    ledger = SubMemberBatchLedger(
        sub_member_id=smb_vasavi.sub_member_id,
        session_date="2026-06-19",
        clearing_session="MORNING",
    )
    ledger.total_received = 100
    ledger.stp_pass = 60
    ledger.stp_return = 30
    ledger.eyeball = 10
    return ledger


# ── Model Tests ──────────────────────────────────────────────────────────────

class TestPrincipalTag:
    def test_enum_values(self):
        assert PrincipalTag.DIRECT.value == "DIRECT"
        assert PrincipalTag.SUB_MEMBER.value == "SUB_MEMBER"

    def test_all_members(self):
        assert len(PrincipalTag) == 2


class TestClearingBucket:
    def test_five_buckets_exist(self):
        assert len(ClearingBucket) == 5

    def test_bucket_values(self):
        assert ClearingBucket.STP_PASS.value == "STP_PASS"
        assert ClearingBucket.STP_RETURN.value == "STP_RETURN"
        assert ClearingBucket.EYEBALL.value == "EYEBALL"
        assert ClearingBucket.FRAUD_HOLD.value == "FRAUD_HOLD"
        assert ClearingBucket.IET_EMERGENCY.value == "IET_EMERGENCY"


class TestSubMemberBank:
    def test_frozen(self, smb_vasavi):
        with pytest.raises((AttributeError, TypeError)):
            smb_vasavi.bank_name = "Changed"

    def test_fields_set_correctly(self, smb_vasavi):
        assert smb_vasavi.sub_member_id == "SMB-MH-001"
        assert smb_vasavi.micr_prefix == "400053"
        assert smb_vasavi.return_rate_threshold == 0.15
        assert smb_vasavi.soft_hold_threshold == 0.25

    def test_email_fields_present(self, smb_vasavi):
        assert "@" in smb_vasavi.branch_manager_email
        assert "@" in smb_vasavi.ops_head_email
        assert "@" in smb_vasavi.gm_email


class TestSubMemberBatchLedger:
    def test_return_rate_zero_when_empty(self):
        ledger = SubMemberBatchLedger(
            sub_member_id="SMB-MH-001",
            session_date="2026-06-19",
            clearing_session="MORNING",
        )
        assert ledger.return_rate == 0.0

    def test_return_rate_calculated(self, ledger_normal):
        assert abs(ledger_normal.return_rate - 0.10) < 1e-6

    def test_return_rate_high(self, ledger_high_return):
        assert abs(ledger_high_return.return_rate - 0.30) < 1e-6

    def test_soft_hold_default_false(self, ledger_normal):
        assert ledger_normal.soft_hold_active is False

    def test_bucket_counts_sum(self, ledger_normal):
        total_classified = (
            ledger_normal.stp_pass
            + ledger_normal.stp_return
            + ledger_normal.eyeball
            + ledger_normal.fraud_hold
            + ledger_normal.iet_emergency
        )
        assert total_classified <= ledger_normal.total_received

    def test_total_returns_property(self, ledger_normal):
        assert ledger_normal.total_returns == 10

    def test_stp_rate_property(self, ledger_normal):
        assert abs(ledger_normal.stp_rate - 0.88) < 1e-6


class TestSubMemberReturn:
    def test_cheque_suffix_max_four_chars(self):
        with pytest.raises(ValueError, match="cheque_number_suffix"):
            SubMemberReturn(
                instrument_id="CHQ-IN-20260619-0042",
                sub_member_id="SMB-MH-001",
                return_reason="SIGNATURE_MISMATCH",
                bucket=ClearingBucket.STP_RETURN,
                amount_range="₹[1L-5L]",
                cheque_number_suffix="12345",  # 5 chars — violates PII rule
                returned_at=datetime(2026, 6, 19, 11, 30),
            )

    def test_valid_return(self, sample_return):
        assert sample_return.cheque_number_suffix == "7890"
        assert sample_return.bucket == ClearingBucket.STP_RETURN

    def test_amount_range_not_exact(self, sample_return):
        # Must be a range bucket, not an exact rupee amount
        assert "₹" in sample_return.amount_range
        assert "[" in sample_return.amount_range


# ── Router Tests ─────────────────────────────────────────────────────────────

class TestMICRPrefixRouter:
    def test_identifies_sub_member(self, router, smb_vasavi):
        # MICR band format: <routing_number>⑆<cheque_number>⑈<account>⑉
        micr_band = "400053⑆001234⑈12345678901234⑉"
        tag, smb = router.identify(micr_band)
        assert tag == PrincipalTag.SUB_MEMBER
        assert smb is not None
        assert smb.sub_member_id == smb_vasavi.sub_member_id

    def test_identifies_direct_member(self, router):
        micr_band = "400002⑆001234⑈12345678901234⑉"
        tag, smb = router.identify(micr_band)
        assert tag == PrincipalTag.DIRECT
        assert smb is None

    def test_tag_principal_sub_member(self, router):
        micr_band = "400083⑆001234⑈12345678901234⑉"
        assert router.tag_principal(micr_band) == PrincipalTag.SUB_MEMBER

    def test_tag_principal_direct(self, router):
        micr_band = "400001⑆001234⑈12345678901234⑉"
        assert router.tag_principal(micr_band) == PrincipalTag.DIRECT

    def test_lookup_by_prefix_returns_bank(self, router, smb_saraswat):
        result = router.lookup("400083")
        assert result is not None
        assert result.bank_name == smb_saraswat.bank_name

    def test_lookup_unknown_prefix_returns_none(self, router):
        assert router.lookup("999999") is None

    def test_empty_routing_table(self):
        empty_router = MICRPrefixRouter({})
        tag, smb = empty_router.identify("400053⑆001234⑈12345678901234⑉")
        assert tag == PrincipalTag.DIRECT
        assert smb is None


# ── Notification Tests ───────────────────────────────────────────────────────

class TestBatchRejectionEmailer:
    def setup_method(self):
        self.emailer = BatchRejectionEmailer()

    def test_tier1_returns_notification_dict(self, smb_vasavi, sample_return):
        result = self.emailer.send_tier1_immediate(smb_vasavi, sample_return)
        assert isinstance(result, dict)
        assert result["tier"] == NotificationTier.TIER1_IMMEDIATE.value
        assert result["to"] == smb_vasavi.branch_manager_email
        assert result["status"] == "QUEUED"

    def test_tier1_subject_contains_bank_name(self, smb_vasavi, sample_return):
        result = self.emailer.send_tier1_immediate(smb_vasavi, sample_return)
        assert smb_vasavi.bank_name in result["subject"]

    def test_tier1_body_contains_return_reason(self, smb_vasavi, sample_return):
        result = self.emailer.send_tier1_immediate(smb_vasavi, sample_return)
        assert sample_return.return_reason in result["body"]

    def test_tier1_body_has_no_exact_amount(self, smb_vasavi, sample_return):
        result = self.emailer.send_tier1_immediate(smb_vasavi, sample_return)
        # Must contain range bucket not exact amount
        assert "₹[" in result["body"]

    def test_tier2_batch_summary(self, smb_vasavi, ledger_normal, sample_return):
        result = self.emailer.send_tier2_batch_summary(
            smb_vasavi, ledger_normal, [sample_return]
        )
        assert result["tier"] == NotificationTier.TIER2_BATCH_SUMMARY.value
        assert result["to"] == smb_vasavi.branch_manager_email
        assert smb_vasavi.ops_head_email in result["cc"]
        assert result["attachment_type"] == "CSV"

    def test_tier2_body_contains_return_rate(self, smb_vasavi, ledger_normal, sample_return):
        result = self.emailer.send_tier2_batch_summary(
            smb_vasavi, ledger_normal, [sample_return]
        )
        assert "10.00%" in result["body"] or "10%" in result["body"]

    def test_tier2_body_contains_bucket_summary(self, smb_vasavi, ledger_normal, sample_return):
        result = self.emailer.send_tier2_batch_summary(
            smb_vasavi, ledger_normal, [sample_return]
        )
        assert "STP_PASS" in result["body"] or "STP Pass" in result["body"]

    def test_tier3_gm_alert(self, smb_vasavi, ledger_high_return):
        result = self.emailer.send_tier3_gm_alert(smb_vasavi, ledger_high_return)
        assert result["tier"] == NotificationTier.TIER3_GM_ESCALATION.value
        assert result["to"] == smb_vasavi.gm_email
        assert result["priority"] == "HIGH"

    def test_tier3_mentions_threshold_breach(self, smb_vasavi, ledger_high_return):
        result = self.emailer.send_tier3_gm_alert(smb_vasavi, ledger_high_return)
        assert "30.00%" in result["body"] or "30%" in result["body"]

    def test_tier3_no_customer_data(self, smb_vasavi, ledger_high_return):
        result = self.emailer.send_tier3_gm_alert(smb_vasavi, ledger_high_return)
        # GM alert is aggregate only — no individual cheque details
        assert "CHQ-" not in result["body"]


# ── Risk Shield Tests ────────────────────────────────────────────────────────

class TestReturnRateShield:
    def setup_method(self):
        self.shield = ReturnRateShield()

    def test_safe_when_below_threshold(self, smb_vasavi, ledger_normal):
        # 10% return rate, threshold 15% → SAFE
        status = self.shield.check(ledger_normal, smb_vasavi)
        assert status == ShieldStatus.SAFE

    def test_soft_hold_when_above_return_threshold(self, smb_vasavi, ledger_high_return):
        # 30% return rate, soft_hold_threshold 25% → SOFT_HOLD
        status = self.shield.check(ledger_high_return, smb_vasavi)
        assert status == ShieldStatus.SOFT_HOLD

    def test_hard_stop_at_double_threshold(self, smb_vasavi):
        ledger = SubMemberBatchLedger(
            sub_member_id=smb_vasavi.sub_member_id,
            session_date="2026-06-19",
            clearing_session="MORNING",
        )
        ledger.total_received = 100
        ledger.stp_return = 55   # 55% — double the soft_hold_threshold of 25%
        ledger.stp_pass = 45
        status = self.shield.check(ledger, smb_vasavi)
        assert status == ShieldStatus.HARD_STOP

    def test_safe_with_zero_returns(self, smb_vasavi):
        ledger = SubMemberBatchLedger(
            sub_member_id=smb_vasavi.sub_member_id,
            session_date="2026-06-19",
            clearing_session="MORNING",
        )
        ledger.total_received = 50
        ledger.stp_pass = 50
        status = self.shield.check(ledger, smb_vasavi)
        assert status == ShieldStatus.SAFE

    def test_apply_soft_hold_updates_ledger(self, smb_vasavi, ledger_high_return):
        self.shield.apply(ledger_high_return, smb_vasavi)
        assert ledger_high_return.soft_hold_active is True

    def test_shield_status_enum_values(self):
        assert ShieldStatus.SAFE.value == "SAFE"
        assert ShieldStatus.SOFT_HOLD.value == "SOFT_HOLD"
        assert ShieldStatus.HARD_STOP.value == "HARD_STOP"
