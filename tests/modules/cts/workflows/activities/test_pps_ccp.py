"""
CCP-compliance tests for PPS — 5-flag NPCI decision tree.

Karnataka Bank Section 8 documents 5 NPCI flags with explicit actions:
  P — Positive match → PROCEED
  D — Duplicate presentation → AUTO_RETURN (code 41, URRBCH: Item listed twice)
  Y — Financial mismatch (amount/payee) → HUMAN_REVIEW; financial reason outranks PPS
  Z — Data not available → check mandatory threshold; HUMAN_REVIEW if above it
  N — Not registered → PROCEED (issuer opted out)

Mandatory threshold (Layer 3 config, default ₹5L per PNB):
  If cheque >= threshold AND flag Z/vault miss → HUMAN_REVIEW with PPS_MANDATORY_MISSING reason.
  If cheque < threshold AND flag Z/vault miss → PROCEED.
"""
import pytest
from unittest.mock import AsyncMock


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


def _vault_with_flag(npci_flag: str, amount=50000.0, payee="ACME Corp"):
    """Build a mock vault that returns a PPSResult with the given NPCI flag."""
    from modules.cts.vaults.pps_vault import PPSResult
    mock_vault = AsyncMock()
    mock_vault.lookup = AsyncMock(
        return_value=PPSResult(
            outcome="FOUND",
            pps_entry={
                "amount": amount,
                "payee": payee,
                "cheque_number": "100001",
                "npci_flag": npci_flag,
            },
        )
    )
    return mock_vault


def _vault_miss():
    from modules.cts.vaults.pps_vault import PPSResult
    mock_vault = AsyncMock()
    mock_vault.lookup = AsyncMock(
        return_value=PPSResult(outcome="HUMAN_REVIEW", miss_reason="PPS_MISS")
    )
    return mock_vault


def _config(mandatory_threshold=500000.0):
    return {"pps_mandatory_threshold": mandatory_threshold}


class TestPPSFlagP:
    @pytest.mark.asyncio
    async def test_flag_p_all_fields_match_proceeds(self):
        """Flag P = positive match → PROCEED."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=50000.0, presented_payee="ACME Corp"),
            vault=_vault_with_flag("P"),
            config=_config(),
        )
        assert result.outcome == "PROCEED"
        assert result.npci_flag == "P"

    @pytest.mark.asyncio
    async def test_flag_p_no_return_code(self):
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(),
            vault=_vault_with_flag("P"),
            config=_config(),
        )
        assert result.return_reason_code is None


class TestPPSFlagD:
    @pytest.mark.asyncio
    async def test_flag_d_duplicate_gives_auto_return(self):
        """Flag D = duplicate presentation → AUTO_RETURN, code 41 (URRBCH: Item listed twice)."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(),
            vault=_vault_with_flag("D"),
            config=_config(),
        )
        assert result.outcome == "AUTO_RETURN"
        assert result.return_reason_code == "41"

    @pytest.mark.asyncio
    async def test_flag_d_is_not_customer_fault(self):
        """Duplicate presentation is a bank/system error — code 41 not customer fault."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(),
            vault=_vault_with_flag("D"),
            config=_config(),
        )
        assert result.is_customer_fault is False


class TestPPSFlagY:
    @pytest.mark.asyncio
    async def test_flag_y_financial_mismatch_gives_human_review(self):
        """Flag Y = financial mismatch → HUMAN_REVIEW (not auto-return)."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=75000.0),  # differs from vault's 50000
            vault=_vault_with_flag("Y", amount=50000.0),
            config=_config(),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_flag_y_financial_reason_takes_priority_flag(self):
        """When Y flag present, downstream decision should use financial reason, not PPS reason."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=75000.0),
            vault=_vault_with_flag("Y", amount=50000.0),
            config=_config(),
        )
        assert result.financial_reason_takes_priority is True


class TestPPSFlagZ:
    @pytest.mark.asyncio
    async def test_flag_z_below_threshold_proceeds(self):
        """Flag Z (data not available) below mandatory threshold → PROCEED."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=100000.0),  # ₹1L < ₹5L threshold
            vault=_vault_with_flag("Z"),
            config=_config(mandatory_threshold=500000.0),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_flag_z_above_threshold_human_review(self):
        """Flag Z above mandatory threshold → HUMAN_REVIEW (PPS mandatory per PNB)."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=600000.0),  # ₹6L > ₹5L threshold
            vault=_vault_with_flag("Z"),
            config=_config(mandatory_threshold=500000.0),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.mismatch_reason == "PPS_MANDATORY_MISSING"

    @pytest.mark.asyncio
    async def test_flag_z_exactly_at_threshold_human_review(self):
        """Boundary: amount == threshold → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=500000.0),
            vault=_vault_with_flag("Z"),
            config=_config(mandatory_threshold=500000.0),
        )
        assert result.outcome == "HUMAN_REVIEW"


class TestPPSFlagN:
    @pytest.mark.asyncio
    async def test_flag_n_not_registered_proceeds(self):
        """Flag N = issuer opted out of PPS → PROCEED (bank cannot penalise)."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(),
            vault=_vault_with_flag("N"),
            config=_config(),
        )
        assert result.outcome == "PROCEED"
        assert result.npci_flag == "N"


class TestPPSVaultMissWithThreshold:
    @pytest.mark.asyncio
    async def test_vault_miss_below_threshold_proceeds(self):
        """No PPS entry, below mandatory threshold → PROCEED."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=100000.0),
            vault=_vault_miss(),
            config=_config(mandatory_threshold=500000.0),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_vault_miss_above_threshold_human_review(self):
        """No PPS entry, above mandatory threshold → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.pps import lookup_pps
        result = await lookup_pps(
            _make_input(presented_amount=600000.0),
            vault=_vault_miss(),
            config=_config(mandatory_threshold=500000.0),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.mismatch_reason == "PPS_MANDATORY_MISSING"


class TestPPSResultModel:
    def test_result_has_npci_flag(self):
        from modules.cts.workflows.activities.pps import PPSActivityResult
        r = PPSActivityResult(
            outcome="PROCEED",
            npci_flag="P",
        )
        assert r.npci_flag == "P"

    def test_result_has_return_reason_code(self):
        from modules.cts.workflows.activities.pps import PPSActivityResult
        r = PPSActivityResult(
            outcome="AUTO_RETURN",
            npci_flag="D",
            return_reason_code="41",
            is_customer_fault=False,
        )
        assert r.return_reason_code == "41"

    def test_result_has_financial_reason_takes_priority(self):
        from modules.cts.workflows.activities.pps import PPSActivityResult
        r = PPSActivityResult(
            outcome="HUMAN_REVIEW",
            npci_flag="Y",
            financial_reason_takes_priority=True,
        )
        assert r.financial_reason_takes_priority is True
