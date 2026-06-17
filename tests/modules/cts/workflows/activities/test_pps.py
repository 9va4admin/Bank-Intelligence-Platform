"""
Tests for modules/cts/workflows/activities/pps.py

PPS (Positive Pay System) activity: checks presented cheque details
against bank's pre-registered cheque registry.

Vault miss → HUMAN_REVIEW (invariant — never auto-return).
Amount mismatch → HUMAN_REVIEW (bank submitted different amount).
Payee mismatch → HUMAN_REVIEW.
All clear → PROCEED.
"""
from unittest.mock import AsyncMock
import pytest


def _make_input(
    instrument_id="INST001",
    bank_id="test-bank",
    account_number="1234567890",
    cheque_number="100001",
    presented_amount=50000.0,
    presented_payee="ACME Corp",
):
    from modules.cts.workflows.activities.pps import PPSActivityInput
    return PPSActivityInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        account_number=account_number,
        cheque_number=cheque_number,
        presented_amount=presented_amount,
        presented_payee=presented_payee,
    )


class TestPPSInput:
    def test_requires_account_number(self):
        from modules.cts.workflows.activities.pps import PPSActivityInput
        with pytest.raises(Exception):
            PPSActivityInput(instrument_id="I", bank_id="b", cheque_number="1",
                             presented_amount=100.0, presented_payee="X")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.presented_amount = 99999.0


class TestPPSVaultMiss:
    @pytest.mark.asyncio
    async def test_vault_miss_outcome_human_review(self):
        """CRITICAL: PPS miss → HUMAN_REVIEW, never auto-return."""
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(outcome="HUMAN_REVIEW", pps_entry=None, miss_reason="PPS_MISS")
        )

        result = await lookup_pps(_make_input(), vault=mock_vault)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_miss_outcome_never_auto_return(self):
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(outcome="HUMAN_REVIEW", pps_entry=None, miss_reason="PPS_MISS")
        )

        result = await lookup_pps(_make_input(), vault=mock_vault)
        assert result.outcome != "AUTO_RETURN"

    @pytest.mark.asyncio
    async def test_vault_error_outcome_human_review(self):
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(outcome="HUMAN_REVIEW", pps_entry=None, miss_reason="VAULT_ERROR")
        )

        result = await lookup_pps(_make_input(), vault=mock_vault)
        assert result.outcome == "HUMAN_REVIEW"


class TestPPSMatch:
    @pytest.mark.asyncio
    async def test_exact_match_outcome_proceed(self):
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(
                outcome="FOUND",
                pps_entry={"amount": 50000.0, "payee": "ACME Corp", "cheque_number": "100001"},
            )
        )

        result = await lookup_pps(_make_input(presented_amount=50000.0, presented_payee="ACME Corp"), vault=mock_vault)
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_amount_mismatch_outcome_human_review(self):
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(
                outcome="FOUND",
                pps_entry={"amount": 50000.0, "payee": "ACME Corp", "cheque_number": "100001"},
            )
        )

        result = await lookup_pps(
            _make_input(presented_amount=75000.0, presented_payee="ACME Corp"),
            vault=mock_vault,
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_payee_mismatch_outcome_human_review(self):
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(
                outcome="FOUND",
                pps_entry={"amount": 50000.0, "payee": "ACME Corp", "cheque_number": "100001"},
            )
        )

        result = await lookup_pps(
            _make_input(presented_amount=50000.0, presented_payee="Different Company"),
            vault=mock_vault,
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_mismatch_reason_set(self):
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(
                outcome="FOUND",
                pps_entry={"amount": 50000.0, "payee": "ACME Corp", "cheque_number": "100001"},
            )
        )

        result = await lookup_pps(
            _make_input(presented_amount=99000.0),
            vault=mock_vault,
        )
        assert result.mismatch_reason is not None

    @pytest.mark.asyncio
    async def test_amount_tolerance_within_one_rupee(self):
        """Floating-point tolerance: ±₹1 should not trigger mismatch."""
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.vaults.pps_vault import PPSResult

        mock_vault = AsyncMock()
        mock_vault.lookup = AsyncMock(
            return_value=PPSResult(
                outcome="FOUND",
                pps_entry={"amount": 50000.0, "payee": "ACME Corp", "cheque_number": "100001"},
            )
        )

        result = await lookup_pps(
            _make_input(presented_amount=50000.50),  # within ₹1
            vault=mock_vault,
        )
        assert result.outcome == "PROCEED"
