"""
Tests for modules/cts/vaults/signature_vault.py

TDD RED step — run before implementation exists.

Critical invariant: vault miss MUST route to HUMAN_REVIEW, never AUTO_RETURN.
"""
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(bank_id="test-bank", redis_client=None, pepper="test-pepper"):
    from modules.cts.vaults.signature_vault import SignatureVault
    vault = SignatureVault(bank_id=bank_id, pepper=pepper)
    vault._redis = redis_client or MagicMock()
    vault._ready = True
    return vault


def _expected_key(bank_id, account_number, pepper="test-pepper"):
    h = hmac.new(pepper.encode(), f"{bank_id}:{account_number}".encode(), hashlib.sha256).hexdigest()
    return f"sig:{bank_id}:{h}"


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestSignatureVaultInit:
    @pytest.mark.asyncio
    async def test_requires_connect_before_get(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="b", pepper="p")
        with pytest.raises(RuntimeError, match="connect"):
            await vault.get_signatures("1234567890", "b")

    def test_connect_sets_ready(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        mock_redis = MagicMock()
        vault = SignatureVault(bank_id="b", pepper="p")
        vault.connect(redis_client=mock_redis)
        assert vault._ready is True

    def test_connect_stores_redis_client(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        mock_redis = MagicMock()
        vault = SignatureVault(bank_id="b", pepper="p")
        vault.connect(redis_client=mock_redis)
        assert vault._redis is mock_redis


# ---------------------------------------------------------------------------
# Key format — never raw account number
# ---------------------------------------------------------------------------

class TestVaultKeyFormat:
    def test_key_uses_hmac_hash_not_raw_account(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="pepper123")
        key = vault._make_key("9876543210")
        assert "9876543210" not in key

    def test_key_starts_with_sig_prefix(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        key = vault._make_key("9876543210")
        assert key.startswith("sig:kotak:")

    def test_key_is_deterministic(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC123") == vault._make_key("ACC123")

    def test_key_differs_for_different_accounts(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC111") != vault._make_key("ACC222")

    def test_key_differs_for_different_bank_ids(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        v1 = SignatureVault(bank_id="bank-a", pepper="p")
        v2 = SignatureVault(bank_id="bank-b", pepper="p")
        assert v1._make_key("ACC123") != v2._make_key("ACC123")

    def test_key_format_matches_expected(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="test-pepper")
        key = vault._make_key("ACC123")
        expected = _expected_key("kotak", "ACC123", "test-pepper")
        assert key == expected


# ---------------------------------------------------------------------------
# Cache hit — must NOT call Redis
# ---------------------------------------------------------------------------

class TestCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_specimens(self):
        vault = _make_vault()
        key = vault._make_key("ACC001")
        fake_specimens = [b"sig1", b"sig2"]
        vault._cache[key] = fake_specimens

        result = await vault.get_signatures("ACC001", "test-bank")
        assert result.specimens == fake_specimens

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_redis(self):
        mock_redis = MagicMock()
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC001")
        vault._cache[key] = [b"sig1"]

        await vault.get_signatures("ACC001", "test-bank")
        mock_redis.lrange.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_outcome_is_found(self):
        vault = _make_vault()
        key = vault._make_key("ACC001")
        vault._cache[key] = [b"specimen"]

        result = await vault.get_signatures("ACC001", "test-bank")
        assert result.outcome == "FOUND"


# ---------------------------------------------------------------------------
# Cache miss + Redis hit
# ---------------------------------------------------------------------------

class TestCacheMissRedisHit:
    @pytest.mark.asyncio
    async def test_redis_hit_returns_specimens(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[b"sig_bytes_1", b"sig_bytes_2"])
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC002", "test-bank")
        assert result.specimens == [b"sig_bytes_1", b"sig_bytes_2"]

    @pytest.mark.asyncio
    async def test_redis_hit_uses_correct_key(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[b"sig"])
        vault = _make_vault(redis_client=mock_redis)

        await vault.get_signatures("ACC002", "test-bank")
        expected_key = vault._make_key("ACC002")
        mock_redis.lrange.assert_called_once_with(expected_key, 0, -1)

    @pytest.mark.asyncio
    async def test_redis_hit_populates_local_cache(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[b"sig1"])
        vault = _make_vault(redis_client=mock_redis)

        await vault.get_signatures("ACC002", "test-bank")
        key = vault._make_key("ACC002")
        assert key in vault._cache

    @pytest.mark.asyncio
    async def test_redis_hit_outcome_is_found(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[b"sig1"])
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC002", "test-bank")
        assert result.outcome == "FOUND"


# ---------------------------------------------------------------------------
# Vault miss — MUST route to HUMAN_REVIEW, NEVER AUTO_RETURN
# ---------------------------------------------------------------------------

class TestVaultMiss:
    @pytest.mark.asyncio
    async def test_vault_miss_outcome_is_human_review(self):
        """CRITICAL safety invariant: vault miss must never become AUTO_RETURN."""
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])   # empty list = no specimens
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_miss_specimens_is_empty(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.specimens == []

    @pytest.mark.asyncio
    async def test_vault_miss_reason_is_set(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.miss_reason == "VAULT_MISS"

    @pytest.mark.asyncio
    async def test_vault_miss_outcome_is_never_auto_return(self):
        """Explicit guard: outcome must not be AUTO_RETURN on any empty vault response."""
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC_MISSING", "test-bank")
        assert result.outcome != "AUTO_RETURN"


# ---------------------------------------------------------------------------
# Vault error — Redis unavailable
# ---------------------------------------------------------------------------

class TestVaultRedisError:
    @pytest.mark.asyncio
    async def test_redis_error_outcome_is_human_review(self):
        """Redis failure must degrade to HUMAN_REVIEW, not crash."""
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=Exception("Redis connection refused"))
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC003", "test-bank")
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_redis_error_reason_is_vault_error(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=Exception("Redis timeout"))
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC003", "test-bank")
        assert result.miss_reason == "VAULT_ERROR"

    @pytest.mark.asyncio
    async def test_redis_error_outcome_is_never_auto_return(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=Exception("timeout"))
        vault = _make_vault(redis_client=mock_redis)

        result = await vault.get_signatures("ACC003", "test-bank")
        assert result.outcome != "AUTO_RETURN"

    @pytest.mark.asyncio
    async def test_redis_error_does_not_raise(self):
        """Vault errors must never propagate — always return a VaultResult."""
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=ConnectionError("down"))
        vault = _make_vault(redis_client=mock_redis)

        # Must not raise
        result = await vault.get_signatures("ACC003", "test-bank")
        assert result is not None


# ---------------------------------------------------------------------------
# Store (warm vault)
# ---------------------------------------------------------------------------

class TestStoreSignatures:
    @pytest.mark.asyncio
    async def test_store_uses_correct_key(self):
        mock_redis = MagicMock()
        mock_redis.delete = MagicMock()
        mock_redis.rpush = MagicMock()
        vault = _make_vault(redis_client=mock_redis)

        await vault.store_signatures("ACC004", [b"specimen1", b"specimen2"])
        expected_key = vault._make_key("ACC004")
        mock_redis.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_store_pushes_each_specimen(self):
        mock_redis = MagicMock()
        mock_redis.delete = MagicMock()
        mock_redis.rpush = MagicMock()
        vault = _make_vault(redis_client=mock_redis)

        specimens = [b"s1", b"s2", b"s3"]
        await vault.store_signatures("ACC004", specimens)
        assert mock_redis.rpush.call_count == 3

    @pytest.mark.asyncio
    async def test_store_never_uses_raw_account_as_key(self):
        mock_redis = MagicMock()
        mock_redis.delete = MagicMock()
        mock_redis.rpush = MagicMock()
        vault = _make_vault(redis_client=mock_redis)

        await vault.store_signatures("ACC004", [b"sig"])
        # Check that raw account number never appeared as Redis key
        for call in mock_redis.delete.call_args_list + mock_redis.rpush.call_args_list:
            for arg in call[0]:
                if isinstance(arg, str):
                    assert "ACC004" not in arg

    @pytest.mark.asyncio
    async def test_store_invalidates_local_cache(self):
        mock_redis = MagicMock()
        mock_redis.delete = MagicMock()
        mock_redis.rpush = MagicMock()
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC004")
        vault._cache[key] = [b"old"]

        await vault.store_signatures("ACC004", [b"new"])
        assert key not in vault._cache


class TestSignatureVaultConnectFallback:
    def test_connect_without_redis_client_imports_redis(self, monkeypatch):
        """Covers lines 39-40: connect() with no redis_client imports redis module."""
        import sys
        from unittest.mock import MagicMock
        fake_redis_mod = MagicMock()
        fake_redis_instance = MagicMock()
        fake_redis_mod.Redis.return_value = fake_redis_instance
        monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)

        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="test-bank", pepper="pepper")
        vault.connect()  # no redis_client → imports redis
        assert vault._ready is True
        assert vault._redis is fake_redis_instance
