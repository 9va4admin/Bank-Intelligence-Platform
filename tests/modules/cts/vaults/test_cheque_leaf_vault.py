"""
Tests for modules/cts/vaults/cheque_leaf_vault.py

ChequeLeafVault — Redis-backed vault for issued cheque leaf status.

Critical invariants:
  - Vault hit (any status) → outcome=FOUND, status reflects CBS value
  - Vault miss (key absent) → outcome=NOT_FOUND (caller routes to HUMAN_REVIEW)
  - Redis error → outcome=ERROR, degraded=True (caller routes to HUMAN_REVIEW)
  - Raw account number NEVER appears in the Redis key — HMAC hash only
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_vault(bank_id="test-bank", pepper="test-pepper", redis_client=None):
    from modules.cts.vaults.cheque_leaf_vault import ChequeLeafVault
    vault = ChequeLeafVault(bank_id=bank_id, pepper=pepper)
    vault.connect(redis_client or MagicMock())
    return vault


class TestChequeLeafVaultLookup:

    @pytest.mark.asyncio
    async def test_lookup_active_leaf_returns_found_with_active_status(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={b"status": b"ACTIVE", b"issued_date": b"2026-01-15"})
        vault = _make_vault(redis_client=redis)
        result = await vault.lookup("9876543210", "001234")
        assert result.outcome == "FOUND"
        assert result.status == "ACTIVE"

    @pytest.mark.asyncio
    async def test_lookup_lost_leaf_returns_found_with_lost_status(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={b"status": b"LOST", b"issued_date": b"2026-01-15"})
        vault = _make_vault(redis_client=redis)
        result = await vault.lookup("9876543210", "001234")
        assert result.outcome == "FOUND"
        assert result.status == "LOST"

    @pytest.mark.asyncio
    async def test_lookup_stolen_leaf_returns_found_with_stolen_status(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={b"status": b"STOLEN"})
        vault = _make_vault(redis_client=redis)
        result = await vault.lookup("9876543210", "001234")
        assert result.outcome == "FOUND"
        assert result.status == "STOLEN"

    @pytest.mark.asyncio
    async def test_lookup_cancelled_leaf_returns_found_with_cancelled_status(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={b"status": b"CANCELLED"})
        vault = _make_vault(redis_client=redis)
        result = await vault.lookup("9876543210", "001234")
        assert result.outcome == "FOUND"
        assert result.status == "CANCELLED"

    @pytest.mark.asyncio
    async def test_lookup_used_leaf_returns_found_with_used_status(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={b"status": b"USED"})
        vault = _make_vault(redis_client=redis)
        result = await vault.lookup("9876543210", "001234")
        assert result.outcome == "FOUND"
        assert result.status == "USED"

    @pytest.mark.asyncio
    async def test_lookup_miss_returns_not_found(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={})
        vault = _make_vault(redis_client=redis)
        result = await vault.lookup("9876543210", "001234")
        assert result.outcome == "NOT_FOUND"
        assert result.status is None

    @pytest.mark.asyncio
    async def test_lookup_redis_error_routes_to_human_review_with_degraded_flag(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock(side_effect=Exception("Redis connection refused"))
        vault = _make_vault(redis_client=redis)
        result = await vault.lookup("9876543210", "001234")
        assert result.outcome == "HUMAN_REVIEW"   # vault error must never auto-decide
        assert result.degraded is True
        assert result.status is None

    def test_redis_key_never_contains_raw_account_number(self):
        vault = _make_vault()
        key = vault._make_key("9876543210", "001234")
        assert "9876543210" not in key

    def test_redis_key_starts_with_chq_prefix(self):
        vault = _make_vault(bank_id="saraswat-coop")
        key = vault._make_key("1234567890", "000100")
        assert key.startswith("chq:saraswat-coop:")

    def test_redis_key_ends_with_cheque_number(self):
        vault = _make_vault()
        key = vault._make_key("1234567890", "000100")
        assert key.endswith(":000100")

    def test_redis_key_hash_segment_is_64_chars(self):
        """HMAC-SHA256 hex digest is always 64 characters."""
        vault = _make_vault()
        key = vault._make_key("1234567890", "000100")
        parts = key.split(":")
        assert len(parts) == 4   # chq : bank_id : hash : cheque_number
        assert len(parts[2]) == 64

    def test_different_account_numbers_produce_different_keys(self):
        vault = _make_vault()
        k1 = vault._make_key("1111111111", "001234")
        k2 = vault._make_key("2222222222", "001234")
        assert k1 != k2

    def test_different_cheque_numbers_produce_different_keys(self):
        vault = _make_vault()
        k1 = vault._make_key("1111111111", "000001")
        k2 = vault._make_key("1111111111", "000002")
        assert k1 != k2


class TestChequeLeafVaultStore:

    @pytest.mark.asyncio
    async def test_store_writes_status_to_redis_hash(self):
        redis = MagicMock()
        redis.hset = AsyncMock()
        vault = _make_vault(redis_client=redis)
        await vault.store("9876543210", "001234", status="ACTIVE", issued_date="2026-01-15")
        assert redis.hset.called
        mapping = redis.hset.call_args[1]["mapping"]
        assert mapping["status"] == "ACTIVE"

    @pytest.mark.asyncio
    async def test_store_includes_issued_date_when_provided(self):
        redis = MagicMock()
        redis.hset = AsyncMock()
        vault = _make_vault(redis_client=redis)
        await vault.store("9876543210", "001234", status="ACTIVE", issued_date="2026-01-15")
        mapping = redis.hset.call_args[1]["mapping"]
        assert mapping.get("issued_date") == "2026-01-15"

    @pytest.mark.asyncio
    async def test_store_key_never_contains_raw_account_number(self):
        redis = MagicMock()
        redis.hset = AsyncMock()
        vault = _make_vault(redis_client=redis)
        await vault.store("9876543210", "001234", status="ACTIVE")
        key = redis.hset.call_args[0][0]
        assert "9876543210" not in key

    def test_pipeline_store_calls_pipe_hset(self):
        redis = MagicMock()
        pipe = MagicMock()
        vault = _make_vault(redis_client=redis)
        vault._pipeline_store(pipe, "9876543210", "001234", status="ACTIVE")
        assert pipe.hset.called

    def test_pipeline_store_key_never_contains_raw_account_number(self):
        redis = MagicMock()
        pipe = MagicMock()
        vault = _make_vault(redis_client=redis)
        vault._pipeline_store(pipe, "9876543210", "001234", status="ACTIVE")
        key = pipe.hset.call_args[0][0]
        assert "9876543210" not in key


class TestChequeLeafVaultNotConnected:

    @pytest.mark.asyncio
    async def test_lookup_before_connect_raises_runtime_error(self):
        from modules.cts.vaults.cheque_leaf_vault import ChequeLeafVault
        vault = ChequeLeafVault(bank_id="test-bank", pepper="test-pepper")
        with pytest.raises(RuntimeError, match="connect"):
            await vault.lookup("9876543210", "001234")


def _vault_with_db(row):
    """Vault whose DB pool returns `row` for the leaf lookup; returns (vault, conn)."""
    redis = MagicMock()
    for m in ("set", "setex", "hset", "expire", "hgetall", "delete"):
        setattr(redis, m, AsyncMock())
    vault = _make_vault(redis_client=redis)
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.execute = AsyncMock()
    tx = MagicMock(); tx.__aenter__ = AsyncMock(return_value=None); tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    acq = MagicMock(); acq.__aenter__ = AsyncMock(return_value=conn); acq.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock(); pool.acquire = MagicMock(return_value=acq)
    vault._db_pool = pool
    return vault, conn


class TestMarkPresentedDuplicateDetection:
    """Duplicate presentment is the double-payment guard: it had no unit tests, and a second real bug
    (the workflow not recognising the error) hid behind that. Same-instrument retries must stay safe."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["PRESENTED", "PAID"])
    async def test_leaf_already_presented_by_another_instrument_raises(self, status):
        from modules.cts.vaults.cheque_leaf_vault import DuplicatePresentmentError
        vault, _ = _vault_with_db({"id": 1, "status": status, "instrument_id": "IW-OTHER"})
        with pytest.raises(DuplicatePresentmentError):
            await vault.mark_presented("9876543210", "001234", "IW-NEW")

    @pytest.mark.asyncio
    async def test_retry_of_the_same_instrument_is_idempotent_not_a_duplicate(self):
        vault, conn = _vault_with_db({"id": 1, "status": "PRESENTED", "instrument_id": "IW-SAME"})
        await vault.mark_presented("9876543210", "001234", "IW-SAME")      # must not raise
        conn.execute.assert_not_awaited()                                   # and must not rewrite history

    @pytest.mark.asyncio
    async def test_active_leaf_becomes_presented(self):
        vault, conn = _vault_with_db({"id": 1, "status": "ACTIVE", "instrument_id": None})
        await vault.mark_presented("9876543210", "001234", "IW-NEW")
        assert conn.execute.await_count >= 1

    @pytest.mark.asyncio
    async def test_unseeded_leaf_is_created_as_presented(self):
        vault, conn = _vault_with_db(None)
        await vault.mark_presented("9876543210", "001234", "IW-NEW")
        sql = conn.execute.await_args_list[0].args[0]
        assert "INSERT INTO cts.cheque_leaves" in sql
