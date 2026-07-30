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
