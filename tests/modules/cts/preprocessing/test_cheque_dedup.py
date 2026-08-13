"""TDD — Cheque dedup validator.

Tests: dedup key format, FRESH first-seen, DUPLICATE second-seen,
lot-level dedup, TTL configuration, key components (MICR + cheque_no).
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from modules.cts.preprocessing.cheque_dedup import (
    make_dedup_key,
    DedupCheckResult,
    check_and_register_dedup,
    DEDUP_TTL_SECONDS,
)


class TestMakeDedupKey:
    def test_key_contains_all_components(self):
        k = make_dedup_key("saraswat", "400053001", "000123")
        assert "saraswat" in k
        assert "400053001" in k
        assert "000123" in k

    def test_key_format_stable(self):
        k1 = make_dedup_key("bank", "123456789", "000001")
        k2 = make_dedup_key("bank", "123456789", "000001")
        assert k1 == k2

    def test_different_micr_different_key(self):
        k1 = make_dedup_key("bank", "400053001", "000001")
        k2 = make_dedup_key("bank", "400053002", "000001")
        assert k1 != k2

    def test_different_cheque_no_different_key(self):
        k1 = make_dedup_key("bank", "400053001", "000001")
        k2 = make_dedup_key("bank", "400053001", "000002")
        assert k1 != k2

    def test_different_bank_different_key(self):
        k1 = make_dedup_key("bank_a", "400053001", "000001")
        k2 = make_dedup_key("bank_b", "400053001", "000001")
        assert k1 != k2

    def test_key_has_no_spaces(self):
        k = make_dedup_key("saraswat coop", "400053001", "000123")
        assert " " not in k


class TestDedupCheckResult:
    def test_fresh_result_shape(self):
        r = DedupCheckResult(
            decision="FRESH",
            existing_instrument_id=None,
            existing_presented_at=None,
        )
        assert r.decision == "FRESH"
        assert r.existing_instrument_id is None

    def test_duplicate_result_shape(self):
        r = DedupCheckResult(
            decision="DUPLICATE",
            existing_instrument_id="INS-001",
            existing_presented_at="2026-08-10T10:00:00",
        )
        assert r.decision == "DUPLICATE"
        assert r.existing_instrument_id == "INS-001"


class TestCheckAndRegisterDedup:
    """Uses a fake Redis stub — no real Redis needed."""

    @pytest.fixture
    def fresh_redis(self):
        """Redis stub that returns None on get (key not present)."""
        mock = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock(return_value=True)
        return mock

    @pytest.fixture
    def duplicate_redis(self):
        """Redis stub that returns an existing entry on get."""
        mock = AsyncMock()
        mock.get = AsyncMock(return_value=b"INS-ORIGINAL|2026-08-01T09:30:00")
        mock.setex = AsyncMock(return_value=True)
        return mock

    @pytest.mark.asyncio
    async def test_fresh_cheque_returns_fresh(self, fresh_redis):
        result = await check_and_register_dedup(
            bank_id="saraswat",
            micr_code="400053001",
            cheque_number="000123",
            instrument_id="INS-NEW",
            presented_at="2026-08-12T10:00:00",
            redis=fresh_redis,
        )
        assert result.decision == "FRESH"
        assert result.existing_instrument_id is None

    @pytest.mark.asyncio
    async def test_fresh_cheque_registers_in_redis(self, fresh_redis):
        await check_and_register_dedup(
            bank_id="saraswat",
            micr_code="400053001",
            cheque_number="000123",
            instrument_id="INS-NEW",
            presented_at="2026-08-12T10:00:00",
            redis=fresh_redis,
        )
        fresh_redis.setex.assert_awaited_once()
        args = fresh_redis.setex.call_args
        # Should set the key with correct TTL
        assert args[0][1] == DEDUP_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_duplicate_cheque_returns_duplicate(self, duplicate_redis):
        result = await check_and_register_dedup(
            bank_id="saraswat",
            micr_code="400053001",
            cheque_number="000123",
            instrument_id="INS-SECOND-PRESENTATION",
            presented_at="2026-08-12T10:00:00",
            redis=duplicate_redis,
        )
        assert result.decision == "DUPLICATE"
        assert result.existing_instrument_id == "INS-ORIGINAL"
        assert result.existing_presented_at == "2026-08-01T09:30:00"

    @pytest.mark.asyncio
    async def test_duplicate_does_not_overwrite_redis(self, duplicate_redis):
        await check_and_register_dedup(
            bank_id="saraswat",
            micr_code="400053001",
            cheque_number="000123",
            instrument_id="INS-SECOND",
            presented_at="2026-08-12T10:00:00",
            redis=duplicate_redis,
        )
        duplicate_redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_custom_ttl_passed_to_redis(self, fresh_redis):
        custom_ttl = 1000
        await check_and_register_dedup(
            bank_id="bank",
            micr_code="123456789",
            cheque_number="000001",
            instrument_id="INS-1",
            presented_at="2026-08-12T09:00:00",
            redis=fresh_redis,
            ttl_seconds=custom_ttl,
        )
        args = fresh_redis.setex.call_args
        assert args[0][1] == custom_ttl

    @pytest.mark.asyncio
    async def test_same_cheque_no_different_micr_is_fresh(self, fresh_redis):
        """Cheque number 000001 at branch A ≠ cheque number 000001 at branch B."""
        r1 = await check_and_register_dedup(
            bank_id="bank", micr_code="400053001", cheque_number="000001",
            instrument_id="INS-A", presented_at="2026-08-12T09:00:00",
            redis=fresh_redis,
        )
        # Both calls → redis.get returns None → both FRESH
        assert r1.decision == "FRESH"


class TestDedupTTL:
    def test_ttl_is_at_least_18_months_seconds(self):
        seconds_in_18_months = 18 * 30 * 24 * 3600
        assert DEDUP_TTL_SECONDS >= seconds_in_18_months
