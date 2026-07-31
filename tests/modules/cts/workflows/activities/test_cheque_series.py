"""
Tests for modules/cts/workflows/activities/cheque_series.py

validate_cheque_series checks whether the cheque leaf was legitimately
issued to the account and is in an active state in CBS.

Critical invariants:
  - ACTIVE cheque → PROCEED
  - LOST / STOLEN cheque → STP_RETURN, code "86" (FORGED_INSTRUMENT)
  - CANCELLED cheque → STP_RETURN, code "20" (STOP_PAYMENT)
  - USED cheque → HUMAN_REVIEW (possible re-presentation or duplicate)
  - AccountNotFoundError → STP_RETURN, code "52" (NO_SUCH_ACCOUNT)
  - CBSUnavailableError → HUMAN_REVIEW (graceful degrade)
  - No CBS connector → HUMAN_REVIEW (graceful degrade)
  - NotImplementedError from CBS → HUMAN_REVIEW (connector not yet built)
"""
import pytest
from unittest.mock import AsyncMock

from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError


def _make_input(
    cheque_number: str = "001234",
    account_number: str = "9876543210",
    bank_id: str = "test-bank",
):
    from modules.cts.workflows.activities.cheque_series import ChequeSeriesActivityInput
    return ChequeSeriesActivityInput(
        instrument_id="INST001",
        bank_id=bank_id,
        account_number=account_number,
        cheque_number=cheque_number,
    )


def _mock_cbs(status: str):
    cbs = AsyncMock()
    cbs.get_cheque_status = AsyncMock(return_value=status)
    return cbs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidateChequeSeries:

    @pytest.mark.asyncio
    async def test_active_cheque_proceeds(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(_make_input(), cbs_connector=_mock_cbs("ACTIVE"))
        assert result.outcome == "PROCEED"
        assert result.return_reason_code is None

    @pytest.mark.asyncio
    async def test_stolen_cheque_returns(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(_make_input(), cbs_connector=_mock_cbs("STOLEN"))
        assert result.outcome == "STP_RETURN"
        assert result.return_reason_code == "86"
        assert result.reason == "CHEQUE_STOLEN"

    @pytest.mark.asyncio
    async def test_lost_cheque_returns(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(_make_input(), cbs_connector=_mock_cbs("LOST"))
        assert result.outcome == "STP_RETURN"
        assert result.return_reason_code == "86"
        assert result.reason == "CHEQUE_LOST"

    @pytest.mark.asyncio
    async def test_cancelled_cheque_returns(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(_make_input(), cbs_connector=_mock_cbs("CANCELLED"))
        assert result.outcome == "STP_RETURN"
        assert result.return_reason_code == "20"
        assert result.reason == "CHEQUE_CANCELLED"

    @pytest.mark.asyncio
    async def test_used_cheque_human_review(self):
        """Already-presented cheque: possible re-presentation or duplicated batch item."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(_make_input(), cbs_connector=_mock_cbs("USED"))
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "CHEQUE_ALREADY_USED"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_human_review(self):
        """CBS down → HUMAN_REVIEW, never STP_RETURN."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        cbs = AsyncMock()
        cbs.get_cheque_status = AsyncMock(side_effect=CBSUnavailableError("timeout"))
        result = await validate_cheque_series(_make_input(), cbs_connector=cbs)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "CBS_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_account_not_found_returns(self):
        """Account does not exist in CBS → STP_RETURN, code 52."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        cbs = AsyncMock()
        cbs.get_cheque_status = AsyncMock(side_effect=AccountNotFoundError("not found"))
        result = await validate_cheque_series(_make_input(), cbs_connector=cbs)
        assert result.outcome == "STP_RETURN"
        assert result.return_reason_code == "52"

    @pytest.mark.asyncio
    async def test_no_cbs_connector_human_review(self):
        """No CBS connector wired → HUMAN_REVIEW (graceful degrade)."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(_make_input(), cbs_connector=None)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "CBS_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_not_implemented_human_review(self):
        """CBS connector has get_cheque_status not implemented yet → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        cbs = AsyncMock()
        cbs.get_cheque_status = AsyncMock(side_effect=NotImplementedError())
        result = await validate_cheque_series(_make_input(), cbs_connector=cbs)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "CBS_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_unknown_status_human_review(self):
        """Unrecognised CBS status → HUMAN_REVIEW rather than silent accept."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(_make_input(), cbs_connector=_mock_cbs("UNKNOWN_STATUS"))
        assert result.outcome == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Vault mode tests
# ---------------------------------------------------------------------------

def _mock_vault(outcome: str, status: str = None, degraded: bool = False):
    """Build an async-capable vault mock returning a ChequeLeafVaultResult."""
    from modules.cts.vaults.cheque_leaf_vault import ChequeLeafVaultResult
    from unittest.mock import AsyncMock
    v = AsyncMock()
    v.lookup = AsyncMock(return_value=ChequeLeafVaultResult(
        outcome=outcome,
        status=status,
        degraded=degraded,
    ))
    return v


def _mock_config(mode: str = "VAULT"):
    from unittest.mock import AsyncMock
    cfg = AsyncMock()
    cfg.get_cts_config = AsyncMock(return_value={"cheque_series.source": mode})
    return cfg


class TestValidateChequeSeriesVaultMode:
    """validate_cheque_series in VAULT mode (ChequeLeafVault path)."""

    @pytest.mark.asyncio
    async def test_vault_active_returns_proceed(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cheque_leaf_vault=_mock_vault("FOUND", "ACTIVE"),
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "PROCEED"
        assert result.return_reason_code is None

    @pytest.mark.asyncio
    async def test_vault_lost_returns_stp_return_code_86(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cheque_leaf_vault=_mock_vault("FOUND", "LOST"),
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "STP_RETURN"
        assert result.return_reason_code == "86"
        assert result.reason == "CHEQUE_LOST"

    @pytest.mark.asyncio
    async def test_vault_stolen_returns_stp_return_code_86(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cheque_leaf_vault=_mock_vault("FOUND", "STOLEN"),
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "STP_RETURN"
        assert result.return_reason_code == "86"
        assert result.reason == "CHEQUE_STOLEN"

    @pytest.mark.asyncio
    async def test_vault_cancelled_returns_stp_return_code_20(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cheque_leaf_vault=_mock_vault("FOUND", "CANCELLED"),
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "STP_RETURN"
        assert result.return_reason_code == "20"
        assert result.reason == "CHEQUE_CANCELLED"

    @pytest.mark.asyncio
    async def test_vault_used_routes_to_human_review(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cheque_leaf_vault=_mock_vault("FOUND", "USED"),
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "CHEQUE_ALREADY_USED"

    @pytest.mark.asyncio
    async def test_vault_miss_routes_to_human_review(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cheque_leaf_vault=_mock_vault("NOT_FOUND"),
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "LEAF_NOT_IN_VAULT"

    @pytest.mark.asyncio
    async def test_vault_error_routes_to_human_review_degraded(self):
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cheque_leaf_vault=_mock_vault("ERROR", degraded=True),
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "VAULT_ERROR"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_vault_mode_no_vault_wired_falls_back_to_cbs(self):
        """VAULT mode but vault=None → falls back to CBS (degraded, not silent fail)."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cbs_connector=_mock_cbs("ACTIVE"),
            cheque_leaf_vault=None,
            config_service=_mock_config("VAULT"),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_cbs_mode_uses_cbs_directly(self):
        """Explicit CBS mode → CBS call, vault is irrelevant."""
        from modules.cts.workflows.activities.cheque_series import validate_cheque_series
        result = await validate_cheque_series(
            _make_input(),
            cbs_connector=_mock_cbs("ACTIVE"),
            cheque_leaf_vault=_mock_vault("FOUND", "LOST"),  # vault says LOST but CBS says ACTIVE
            config_service=_mock_config("CBS"),
        )
        assert result.outcome == "PROCEED"   # CBS wins in CBS mode
