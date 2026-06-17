"""
Tests for modules/cts/vaults/pps_vault.py

PPS = Positive Pay System. Banks pre-register high-value cheques with
account number, cheque series, amount and payee. CTS verifies presented
cheques against this registry.

Critical invariant: vault miss MUST route to HUMAN_REVIEW, never AUTO_RETURN.
"""
import hashlib
import hmac
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(bank_id="test-bank", redis_client=None, pepper="test-pepper"):
    from modules.cts.vaults.pps_vault import PPSVault
    vault = PPSVault(bank_id=bank_id, pepper=pepper)
    vault._redis = redis_client or MagicMock()
    vault._ready = True
    return vault


def _pps_key(bank_id, account_number, cheque_series_start, pepper="test-pepper"):
    digest = hmac.new(
        pepper.encode(),
        f"{bank_id}:{account_number}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"pps:{bank_id}:{digest}:{cheque_series_start}"


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestPPSVaultInit:
    @pytest.mark.asyncio
    async def test_requires_connect_before_lookup(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="b", pepper="p")
        with pytest.raises(RuntimeError, match="connect"):
            await vault.lookup("ACC001", "b", "100001")

    def test_connect_sets_ready(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="b", pepper="p")
        vault.connect(redis_client=MagicMock())
        assert vault._ready is True


# ---------------------------------------------------------------------------
# Key format
# ---------------------------------------------------------------------------

class TestPPSKeyFormat:
    def test_key_never_contains_raw_account(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="kotak", pepper="p")
        key = vault._make_key("9876543210", "100001")
        assert "9876543210" not in key

    def test_key_starts_with_pps_prefix(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="kotak", pepper="p")
        key = vault._make_key("ACC001", "100001")
        assert key.startswith("pps:kotak:")

    def test_key_includes_cheque_series(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="kotak", pepper="p")
        key = vault._make_key("ACC001", "100001")
        assert key.endswith(":100001")

    def test_key_differs_for_different_cheque_series(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC001", "100001") != vault._make_key("ACC001", "200001")

    def test_key_is_deterministic(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC001", "100001") == vault._make_key("ACC001", "100001")

    def test_key_matches_expected_format(self):
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id="kotak", pepper="test-pepper")
        assert vault._make_key("ACC001", "100001") == _pps_key("kotak", "ACC001", "100001")


# ---------------------------------------------------------------------------
# Lookup — cache hit
# ---------------------------------------------------------------------------

class TestLookupCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_pps_entry(self):
        vault = _make_vault()
        key = vault._make_key("ACC001", "100001")
        vault._cache[key] = {"amount": 100000.0, "payee": "ACME Corp", "cheque_number": "100001"}

        result = await vault.lookup("ACC001", "test-bank", "100001")
        assert result.outcome == "FOUND"

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_redis(self):
        mock_redis = MagicMock()
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC001", "100001")
        vault._cache[key] = {"amount": 50000.0}

        await vault.lookup("ACC001", "test-bank", "100001")
        mock_redis.hgetall.assert_not_called()


# ---------------------------------------------------------------------------
# Lookup — Redis hit
# ---------------------------------------------------------------------------

class TestLookupRedisHit:
    @pytest.mark.asyncio
    async def test_redis_hit_outcome_is_found(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={
            b"amount": b"150000.00",
            b"payee": b"John Doe",
            b"cheque_number": b"100001",
        })
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC001", "test-bank", "100001")
        assert result.outcome == "FOUND"

    @pytest.mark.asyncio
    async def test_redis_hit_returns_amount_as_float(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={
            b"amount": b"150000.50",
            b"payee": b"Jane",
            b"cheque_number": b"100001",
        })
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC001", "test-bank", "100001")
        assert result.pps_entry["amount"] == 150000.50

    @pytest.mark.asyncio
    async def test_redis_hit_uses_correct_key(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={b"amount": b"100.0", b"payee": b"x", b"cheque_number": b"1"})
        vault = _make_vault(redis_client=mock_redis)

        await vault.lookup("ACC001", "test-bank", "100001")
        expected = vault._make_key("ACC001", "100001")
        mock_redis.hgetall.assert_called_once_with(expected)

    @pytest.mark.asyncio
    async def test_redis_hit_populates_cache(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={b"amount": b"100.0", b"payee": b"x", b"cheque_number": b"1"})
        vault = _make_vault(redis_client=mock_redis)

        await vault.lookup("ACC001", "test-bank", "100001")
        key = vault._make_key("ACC001", "100001")
        assert key in vault._cache


# ---------------------------------------------------------------------------
# Vault miss — MUST route to HUMAN_REVIEW
# ---------------------------------------------------------------------------

class TestPPSVaultMiss:
    @pytest.mark.asyncio
    async def test_miss_outcome_is_human_review(self):
        """CRITICAL: PPS miss must never become AUTO_RETURN."""
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={})  # empty = not registered
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC_UNKNOWN", "test-bank", "999999")
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_miss_reason_is_pps_miss(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={})
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC_UNKNOWN", "test-bank", "999999")
        assert result.miss_reason == "PPS_MISS"

    @pytest.mark.asyncio
    async def test_miss_outcome_is_never_auto_return(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={})
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC_UNKNOWN", "test-bank", "999999")
        assert result.outcome != "AUTO_RETURN"

    @pytest.mark.asyncio
    async def test_miss_pps_entry_is_none(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(return_value={})
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC_UNKNOWN", "test-bank", "999999")
        assert result.pps_entry is None


# ---------------------------------------------------------------------------
# Redis error — MUST route to HUMAN_REVIEW
# ---------------------------------------------------------------------------

class TestPPSRedisError:
    @pytest.mark.asyncio
    async def test_redis_error_outcome_is_human_review(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(side_effect=Exception("Redis down"))
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC001", "test-bank", "100001")
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_redis_error_reason_is_vault_error(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(side_effect=ConnectionError("timeout"))
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC001", "test-bank", "100001")
        assert result.miss_reason == "VAULT_ERROR"

    @pytest.mark.asyncio
    async def test_redis_error_does_not_raise(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(side_effect=RuntimeError("unexpected"))
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC001", "test-bank", "100001")
        assert result is not None

    @pytest.mark.asyncio
    async def test_redis_error_outcome_is_never_auto_return(self):
        mock_redis = MagicMock()
        mock_redis.hgetall = MagicMock(side_effect=Exception("gone"))
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.lookup("ACC001", "test-bank", "100001")
        assert result.outcome != "AUTO_RETURN"


# ---------------------------------------------------------------------------
# Store PPS entry
# ---------------------------------------------------------------------------

class TestStorePPS:
    @pytest.mark.asyncio
    async def test_store_uses_correct_key(self):
        mock_redis = MagicMock()
        mock_redis.hset = MagicMock()
        mock_redis.expire = MagicMock()
        vault = _make_vault(redis_client=mock_redis)

        await vault.store("ACC001", "100001", amount=50000.0, payee="ACME")
        expected_key = vault._make_key("ACC001", "100001")
        mock_redis.hset.assert_called_once()
        call_key = mock_redis.hset.call_args[0][0]
        assert call_key == expected_key

    @pytest.mark.asyncio
    async def test_store_does_not_use_raw_account_as_key(self):
        mock_redis = MagicMock()
        mock_redis.hset = MagicMock()
        mock_redis.expire = MagicMock()
        vault = _make_vault(redis_client=mock_redis)

        await vault.store("ACC_SECRET", "100001", amount=100.0, payee="Bob")
        call_key = mock_redis.hset.call_args[0][0]
        assert "ACC_SECRET" not in call_key

    @pytest.mark.asyncio
    async def test_store_sets_amount_and_payee(self):
        mock_redis = MagicMock()
        mock_redis.hset = MagicMock()
        mock_redis.expire = MagicMock()
        vault = _make_vault(redis_client=mock_redis)

        await vault.store("ACC001", "100001", amount=75000.0, payee="XYZ Ltd")
        mapping = mock_redis.hset.call_args[1]["mapping"]
        assert float(mapping["amount"]) == 75000.0
        assert mapping["payee"] == "XYZ Ltd"

    @pytest.mark.asyncio
    async def test_store_invalidates_cache(self):
        mock_redis = MagicMock()
        mock_redis.hset = MagicMock()
        mock_redis.expire = MagicMock()
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC001", "100001")
        vault._cache[key] = {"amount": 1.0}

        await vault.store("ACC001", "100001", amount=99.0, payee="New")
        assert key not in vault._cache
