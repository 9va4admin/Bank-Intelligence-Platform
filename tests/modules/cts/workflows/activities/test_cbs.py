"""
Tests for modules/cts/workflows/activities/cbs.py

CBS activity: check account status and balance via CBS connector.
Critical: CBS unreachable → graceful degradation (not crash, not IET breach).
Vault miss action enforced: FROZEN/CLOSED/NPA → RETURN, DORMANT → HUMAN_REVIEW.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(account_number="1234567890", bank_id="test-bank", instrument_id="INST001"):
    from modules.cts.workflows.activities.cbs import CBSActivityInput
    return CBSActivityInput(
        account_number=account_number,
        bank_id=bank_id,
        instrument_id=instrument_id,
    )


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class TestCBSActivityInput:
    def test_input_requires_account_number(self):
        from modules.cts.workflows.activities.cbs import CBSActivityInput
        with pytest.raises(Exception):
            CBSActivityInput(bank_id="b", instrument_id="I1")

    def test_input_requires_bank_id(self):
        from modules.cts.workflows.activities.cbs import CBSActivityInput
        with pytest.raises(Exception):
            CBSActivityInput(account_number="1234567890", instrument_id="I1")

    def test_input_requires_instrument_id(self):
        from modules.cts.workflows.activities.cbs import CBSActivityInput
        with pytest.raises(Exception):
            CBSActivityInput(account_number="1234567890", bank_id="b")

    def test_input_is_frozen(self):
        from modules.cts.workflows.activities.cbs import CBSActivityInput
        inp = CBSActivityInput(account_number="1234", bank_id="b", instrument_id="I")
        with pytest.raises(Exception):
            inp.account_number = "9999"


# ---------------------------------------------------------------------------
# Happy path — account active
# ---------------------------------------------------------------------------

class TestCBSActivityHappyPath:
    @pytest.mark.asyncio
    async def test_active_account_outcome_proceed(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="hash123",
            account_number_last4="7890",
            status=AccountStatus.ACTIVE,
            bank_id="test-bank",
            available_balance=250000.0,
            currency="INR",
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_active_account_returns_balance(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="h",
            account_number_last4="7890",
            status=AccountStatus.ACTIVE,
            bank_id="test-bank",
            available_balance=500000.0,
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.available_balance == 500000.0

    @pytest.mark.asyncio
    async def test_active_account_returns_status(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="h",
            account_number_last4="7890",
            status=AccountStatus.ACTIVE,
            bank_id="test-bank",
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.account_status == "ACTIVE"


# ---------------------------------------------------------------------------
# Frozen / Closed / NPA → RETURN immediately
# ---------------------------------------------------------------------------

class TestCBSActivityReturnStatuses:
    @pytest.mark.asyncio
    async def test_frozen_account_outcome_return(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="h", account_number_last4="7890",
            status=AccountStatus.FROZEN, bank_id="test-bank",
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.outcome == "RETURN"

    @pytest.mark.asyncio
    async def test_closed_account_outcome_return(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="h", account_number_last4="7890",
            status=AccountStatus.CLOSED, bank_id="test-bank",
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.outcome == "RETURN"

    @pytest.mark.asyncio
    async def test_npa_account_outcome_return(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="h", account_number_last4="7890",
            status=AccountStatus.NPA, bank_id="test-bank",
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.outcome == "RETURN"

    @pytest.mark.asyncio
    async def test_dormant_account_outcome_human_review(self):
        """Dormant is ambiguous — escalate to human rather than auto-return."""
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="h", account_number_last4="7890",
            status=AccountStatus.DORMANT, bank_id="test-bank",
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.outcome == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# CBS unavailable — graceful degradation
# ---------------------------------------------------------------------------

class TestCBSActivityDegradation:
    @pytest.mark.asyncio
    async def test_cbs_unavailable_outcome_is_degraded(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.exceptions import CBSUnavailableError

        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(
            side_effect=CBSUnavailableError("CBS connection refused")
        )

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.outcome == "CBS_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_does_not_raise(self):
        """CBS failure must never crash the Temporal activity."""
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.exceptions import CBSUnavailableError

        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(
            side_effect=CBSUnavailableError("timeout")
        )

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result is not None

    @pytest.mark.asyncio
    async def test_cbs_unavailable_balance_is_none(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.exceptions import CBSUnavailableError

        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(
            side_effect=CBSUnavailableError("down")
        )

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.available_balance is None

    @pytest.mark.asyncio
    async def test_account_not_found_outcome_return(self):
        """Account not in CBS = return the cheque."""
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from shared.cbs_connector.exceptions import AccountNotFoundError

        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(
            side_effect=AccountNotFoundError("1234567890")
        )

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert result.outcome == "RETURN"


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestCBSActivityOutput:
    @pytest.mark.asyncio
    async def test_output_is_frozen_pydantic_model(self):
        from modules.cts.workflows.activities.cbs import check_cbs_balance, CBSActivityResult
        from shared.cbs_connector.base import AccountInfo, AccountStatus

        mock_info = AccountInfo(
            account_number_hash="h", account_number_last4="7890",
            status=AccountStatus.ACTIVE, bank_id="test-bank", available_balance=100.0,
        )
        mock_connector = AsyncMock()
        mock_connector.get_account_info = AsyncMock(return_value=mock_info)

        result = await check_cbs_balance(_make_input(), cbs_connector=mock_connector)
        assert isinstance(result, CBSActivityResult)
