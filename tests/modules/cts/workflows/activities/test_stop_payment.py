"""
Tests for modules/cts/workflows/activities/stop_payment.py

Stop payment check: CBS lookup via check_stop_payment() + Bloom filter pre-check.
Critical routing:
  - CBS confirms stopped → STP_RETURN
  - Bloom filter hit (probabilistic) → HUMAN_REVIEW (not RETURN — may be false positive)
  - CBS unavailable → HUMAN_REVIEW  (never auto-return on uncertainty)
  - No stop instruction → PROCEED
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_input(
    account_number="1234567890",
    cheque_number="000123",
    bank_id="test-bank",
    instrument_id="INST001",
):
    from modules.cts.workflows.activities.stop_payment import StopPaymentActivityInput
    return StopPaymentActivityInput(
        account_number=account_number,
        cheque_number=cheque_number,
        bank_id=bank_id,
        instrument_id=instrument_id,
    )


def _make_stop_payment_result(is_stopped: bool, reason: str = ""):
    from shared.cbs_connector.base import StopPaymentResult
    return StopPaymentResult(is_stopped=is_stopped, reason=reason or None)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class TestStopPaymentInput:
    def test_requires_account_number(self):
        from modules.cts.workflows.activities.stop_payment import StopPaymentActivityInput
        with pytest.raises(Exception):
            StopPaymentActivityInput(cheque_number="000123", bank_id="b", instrument_id="I1")

    def test_requires_cheque_number(self):
        from modules.cts.workflows.activities.stop_payment import StopPaymentActivityInput
        with pytest.raises(Exception):
            StopPaymentActivityInput(account_number="123", bank_id="b", instrument_id="I1")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.account_number = "changed"

    def test_all_fields_set(self):
        inp = _make_input()
        assert inp.account_number == "1234567890"
        assert inp.cheque_number == "000123"
        assert inp.bank_id == "test-bank"
        assert inp.instrument_id == "INST001"


# ---------------------------------------------------------------------------
# Happy path — not stopped
# ---------------------------------------------------------------------------

class TestStopPaymentNotStopped:
    @pytest.mark.asyncio
    async def test_not_stopped_returns_proceed(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.return_value = _make_stop_payment_result(is_stopped=False)
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_not_stopped_result_is_not_degraded(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.return_value = _make_stop_payment_result(is_stopped=False)
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.degraded is False


# ---------------------------------------------------------------------------
# CBS confirms stop payment → STP_RETURN
# ---------------------------------------------------------------------------

class TestStopPaymentStopped:
    @pytest.mark.asyncio
    async def test_stopped_returns_stp_return(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.return_value = _make_stop_payment_result(
            is_stopped=True, reason="Customer instruction via branch"
        )
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.outcome == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_stopped_result_carries_reason(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.return_value = _make_stop_payment_result(
            is_stopped=True, reason="Cheque reported lost"
        )
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.outcome == "STP_RETURN"
        assert "lost" in (result.stop_reason or "").lower()

    @pytest.mark.asyncio
    async def test_stopped_result_not_degraded(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.return_value = _make_stop_payment_result(is_stopped=True)
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.degraded is False


# ---------------------------------------------------------------------------
# Bloom filter hit (before CBS call) → HUMAN_REVIEW
# Bloom is probabilistic — may be false positive, so we must never auto-RETURN on Bloom alone
# ---------------------------------------------------------------------------

class TestBloomFilterHit:
    @pytest.mark.asyncio
    async def test_bloom_hit_routes_to_human_review(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        bloom = MagicMock()
        bloom.check_serial.return_value = True   # Bloom says: possibly stopped

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_bloom_hit_skips_cbs_call(self):
        """Bloom hit exits early — no CBS call needed (saves CBS load)."""
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        bloom = MagicMock()
        bloom.check_serial.return_value = True

        await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        cbs.check_stop_payment.assert_not_called()

    @pytest.mark.asyncio
    async def test_bloom_hit_is_not_stp_return(self):
        """Bloom is probabilistic — never STP_RETURN on Bloom alone, only HUMAN_REVIEW."""
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        bloom = MagicMock()
        bloom.check_serial.return_value = True

        result = await check_stop_payment(_make_input(), cbs_connector=AsyncMock(), bloom_client=bloom)
        assert result.outcome != "STP_RETURN"

    @pytest.mark.asyncio
    async def test_bloom_hit_marked_as_bloom_hit_in_result(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        bloom = MagicMock()
        bloom.check_serial.return_value = True

        result = await check_stop_payment(_make_input(), cbs_connector=AsyncMock(), bloom_client=bloom)
        assert result.bloom_hit is True


# ---------------------------------------------------------------------------
# CBS unavailable → HUMAN_REVIEW (never auto-return on uncertainty)
# ---------------------------------------------------------------------------

class TestCBSUnavailable:
    @pytest.mark.asyncio
    async def test_cbs_unavailable_routes_to_human_review(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment
        from shared.cbs_connector.exceptions import CBSUnavailableError

        cbs = AsyncMock()
        cbs.check_stop_payment.side_effect = CBSUnavailableError("Connection refused")
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_never_returns_stp_return(self):
        """Critical: uncertainty must never auto-return. Vault-miss invariant."""
        from modules.cts.workflows.activities.stop_payment import check_stop_payment
        from shared.cbs_connector.exceptions import CBSUnavailableError

        cbs = AsyncMock()
        cbs.check_stop_payment.side_effect = CBSUnavailableError("Timeout")
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.outcome != "STP_RETURN"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_marks_degraded(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment
        from shared.cbs_connector.exceptions import CBSUnavailableError

        cbs = AsyncMock()
        cbs.check_stop_payment.side_effect = CBSUnavailableError("CBS down")
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_unexpected_exception_also_human_review(self):
        """Any unexpected CBS error → HUMAN_REVIEW, not crash."""
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.side_effect = RuntimeError("Unexpected CBS error")
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_activity_never_raises(self):
        """Activity must never propagate exceptions — workflow must not crash."""
        from modules.cts.workflows.activities.stop_payment import check_stop_payment
        from shared.cbs_connector.exceptions import CBSUnavailableError

        cbs = AsyncMock()
        cbs.check_stop_payment.side_effect = CBSUnavailableError("CBS down")
        bloom = MagicMock()
        bloom.check_serial.return_value = False

        # Must not raise
        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=bloom)
        assert result is not None


# ---------------------------------------------------------------------------
# No Bloom client provided — graceful fallback
# ---------------------------------------------------------------------------

class TestNoBloomClient:
    @pytest.mark.asyncio
    async def test_no_bloom_client_falls_through_to_cbs(self):
        """If Bloom client is not injected, proceed straight to CBS lookup."""
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.return_value = _make_stop_payment_result(is_stopped=False)

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=None)
        assert result.outcome == "PROCEED"
        cbs.check_stop_payment.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_bloom_stopped_still_returns(self):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment

        cbs = AsyncMock()
        cbs.check_stop_payment.return_value = _make_stop_payment_result(is_stopped=True)

        result = await check_stop_payment(_make_input(), cbs_connector=cbs, bloom_client=None)
        assert result.outcome == "STP_RETURN"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class TestStopPaymentResult:
    def test_result_is_frozen(self):
        from modules.cts.workflows.activities.stop_payment import StopPaymentActivityResult
        r = StopPaymentActivityResult(outcome="PROCEED", bank_id="b", instrument_id="I")
        with pytest.raises(Exception):
            r.outcome = "changed"

    def test_result_defaults(self):
        from modules.cts.workflows.activities.stop_payment import StopPaymentActivityResult
        r = StopPaymentActivityResult(outcome="PROCEED", bank_id="b", instrument_id="I")
        assert r.degraded is False
        assert r.bloom_hit is False
        assert r.stop_reason is None
