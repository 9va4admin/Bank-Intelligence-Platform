"""
Tests for SponsorSettlementShield — Phase 6.1 CCP compliance.

Karnataka Bank CCP Section 9 + PNB Section 7:
  Before forwarding an SMB batch to NGCH via the sponsor bank, verify the SMB's
  settlement account at the sponsor bank has sufficient funds to cover the batch.

  Insufficient → BLOCK the batch, return all instruments with URRBCH code 72
                 (SMB_SPONSOR_FUNDS_INSUFFICIENT, Citibank/NPCI numbering), not customer fault.
  CBS unavailable → ESCALATE (human review) — never silently proceed.
  Sufficient → PROCEED with batch forwarding.
"""
import pytest
from unittest.mock import AsyncMock


def _make_batch(total_amount=150000.0, instrument_count=10, sub_member_id="smb-ucb-01"):
    from modules.cts.sub_member.risk_shield import SponsorBatchInfo
    return SponsorBatchInfo(
        sub_member_id=sub_member_id,
        sponsor_bank_id="saraswat-coop",
        batch_total_amount=total_amount,
        instrument_count=instrument_count,
    )


def _cbs_with_balance(balance: float):
    cbs = AsyncMock()
    cbs.get_smb_settlement_balance = AsyncMock(return_value=balance)
    return cbs


def _cbs_unavailable():
    cbs = AsyncMock()
    cbs.get_smb_settlement_balance = AsyncMock(
        side_effect=Exception("CBS connection timeout")
    )
    return cbs


class TestSponsorSettlementShieldSufficient:
    @pytest.mark.asyncio
    async def test_balance_exceeds_batch_total_proceeds(self):
        """SMB has ₹3L balance, batch is ₹1.5L → PROCEED."""
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(total_amount=150000.0),
            cbs=_cbs_with_balance(300000.0),
        )
        assert result.status == "PROCEED"

    @pytest.mark.asyncio
    async def test_balance_exactly_equals_batch_total_proceeds(self):
        """Exact balance = batch amount → PROCEED (boundary case)."""
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(total_amount=200000.0),
            cbs=_cbs_with_balance(200000.0),
        )
        assert result.status == "PROCEED"

    @pytest.mark.asyncio
    async def test_no_return_code_on_proceed(self):
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(total_amount=100000.0),
            cbs=_cbs_with_balance(500000.0),
        )
        assert result.return_reason_code is None


class TestSponsorSettlementShieldInsufficient:
    @pytest.mark.asyncio
    async def test_balance_below_batch_total_blocks(self):
        """SMB balance ₹50K < batch ₹1.5L → BLOCK, code 72 (URRBCH SMB sponsor funds insufficient)."""
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(total_amount=150000.0),
            cbs=_cbs_with_balance(50000.0),
        )
        assert result.status == "BLOCK"
        assert result.return_reason_code == "72"

    @pytest.mark.asyncio
    async def test_zero_balance_blocks(self):
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(total_amount=10000.0),
            cbs=_cbs_with_balance(0.0),
        )
        assert result.status == "BLOCK"
        assert result.return_reason_code == "72"

    @pytest.mark.asyncio
    async def test_code_72_is_not_customer_fault(self):
        """SMB settlement failure is bank-side — drawee customer not at fault."""
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(total_amount=500000.0),
            cbs=_cbs_with_balance(100000.0),
        )
        assert result.is_customer_fault is False

    @pytest.mark.asyncio
    async def test_block_result_contains_sub_member_id(self):
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(sub_member_id="smb-ucb-99", total_amount=500000.0),
            cbs=_cbs_with_balance(100000.0),
        )
        assert result.sub_member_id == "smb-ucb-99"


class TestSponsorSettlementShieldCBSUnavailable:
    @pytest.mark.asyncio
    async def test_cbs_unavailable_escalates_not_blocks(self):
        """CBS down → ESCALATE (ops human review) — never silently proceed or auto-block."""
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(total_amount=200000.0),
            cbs=_cbs_unavailable(),
        )
        assert result.status == "ESCALATE"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_no_return_code(self):
        """Escalation is not a return — no URRBCH code assigned."""
        from modules.cts.sub_member.risk_shield import SponsorSettlementShield
        shield = SponsorSettlementShield()
        result = await shield.check(
            batch=_make_batch(),
            cbs=_cbs_unavailable(),
        )
        assert result.return_reason_code is None
        assert result.is_customer_fault is None


class TestSponsorBatchInfoModel:
    def test_batch_info_has_required_fields(self):
        from modules.cts.sub_member.risk_shield import SponsorBatchInfo
        b = SponsorBatchInfo(
            sub_member_id="smb-01",
            sponsor_bank_id="saraswat",
            batch_total_amount=500000.0,
            instrument_count=25,
        )
        assert b.batch_total_amount == 500000.0
        assert b.instrument_count == 25


class TestSettlementShieldResultModel:
    def test_result_has_all_fields(self):
        from modules.cts.sub_member.risk_shield import SettlementShieldResult
        r = SettlementShieldResult(
            status="BLOCK",
            sub_member_id="smb-01",
            return_reason_code="72",
            is_customer_fault=False,
        )
        assert r.status == "BLOCK"
        assert r.return_reason_code == "72"
        assert r.is_customer_fault is False
