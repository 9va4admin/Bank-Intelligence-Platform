"""
Tests for modules/cts/vaults/signature_vault.py

TDD — embedding-based two-tier vault (YugabyteDB + Redis).

Critical invariant: vault miss MUST route to HUMAN_REVIEW, never AUTO_RETURN.
VaultResult.embeddings replaces the old .specimens (raw bytes).
"""
import hashlib
import hmac
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_DIM = 512
_PACK_FMT = f"{_DIM}f"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_embedding(seed: int = 1) -> list[float]:
    return [float((i + seed) % 7 + 0.1) for i in range(_DIM)]


def _pack(emb: list[float]) -> bytes:
    return struct.pack(_PACK_FMT, *emb)


def _make_vault(bank_id="test-bank", redis_client=None, pepper="test-pepper", db_pool=None):
    from modules.cts.vaults.signature_vault import SignatureVault
    vault = SignatureVault(bank_id=bank_id, pepper=pepper, db_pool=db_pool)
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
        vault = SignatureVault(bank_id="b", pepper="p")
        vault.connect(redis_client=MagicMock())
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
        assert vault._make_key("9876543210").startswith("sig:kotak:")

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
        assert vault._make_key("ACC123") == _expected_key("kotak", "ACC123", "test-pepper")


# ---------------------------------------------------------------------------
# Cache hit — must NOT call Redis
# ---------------------------------------------------------------------------

class TestCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_embeddings(self):
        vault = _make_vault()
        key = vault._make_key("ACC001")
        embs = [_fake_embedding(1), _fake_embedding(2)]
        vault._cache[key] = embs
        result = await vault.get_signatures("ACC001", "test-bank")
        assert result.embeddings == embs

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_redis(self):
        mock_redis = MagicMock()
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC001")
        vault._cache[key] = [_fake_embedding()]
        await vault.get_signatures("ACC001", "test-bank")
        mock_redis.lrange.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_outcome_is_found(self):
        vault = _make_vault()
        key = vault._make_key("ACC001")
        vault._cache[key] = [_fake_embedding()]
        result = await vault.get_signatures("ACC001", "test-bank")
        assert result.outcome == "FOUND"


# ---------------------------------------------------------------------------
# Cache miss + Redis hit — embeddings unpacked from packed bytes
# ---------------------------------------------------------------------------

class TestCacheMissRedisHit:
    @pytest.mark.asyncio
    async def test_redis_hit_returns_embeddings(self):
        emb1, emb2 = _fake_embedding(1), _fake_embedding(2)
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[_pack(emb1), _pack(emb2)])
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC002", "test-bank")
        assert len(result.embeddings) == 2
        assert len(result.embeddings[0]) == _DIM

    @pytest.mark.asyncio
    async def test_redis_hit_uses_correct_key(self):
        emb = _fake_embedding()
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[_pack(emb)])
        vault = _make_vault(redis_client=mock_redis)
        await vault.get_signatures("ACC002", "test-bank")
        expected_key = vault._make_key("ACC002")
        mock_redis.lrange.assert_called_once_with(expected_key, 0, -1)

    @pytest.mark.asyncio
    async def test_redis_hit_populates_local_cache(self):
        emb = _fake_embedding()
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[_pack(emb)])
        vault = _make_vault(redis_client=mock_redis)
        await vault.get_signatures("ACC002", "test-bank")
        assert vault._make_key("ACC002") in vault._cache

    @pytest.mark.asyncio
    async def test_redis_hit_outcome_is_found(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[_pack(_fake_embedding())])
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC002", "test-bank")
        assert result.outcome == "FOUND"


# ---------------------------------------------------------------------------
# Redis miss + YugabyteDB hit — backfills Redis
# ---------------------------------------------------------------------------

class TestRedisMissDbHit:
    def _make_db_pool(self, embeddings: list[list[float]]):
        rows = [{"embedding": _pack(e)} for e in embeddings]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False)))
        return pool

    @pytest.mark.asyncio
    async def test_db_hit_returns_found(self):
        emb = _fake_embedding()
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        mock_redis.pipeline = MagicMock(return_value=MagicMock(delete=MagicMock(), rpush=MagicMock(), execute=MagicMock()))
        db_pool = self._make_db_pool([emb])
        vault = _make_vault(redis_client=mock_redis, db_pool=db_pool)
        result = await vault.get_signatures("ACC010", "test-bank")
        assert result.outcome == "FOUND"

    @pytest.mark.asyncio
    async def test_db_hit_returns_embeddings(self):
        emb = _fake_embedding(5)
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        mock_redis.pipeline = MagicMock(return_value=MagicMock(delete=MagicMock(), rpush=MagicMock(), execute=MagicMock()))
        db_pool = self._make_db_pool([emb])
        vault = _make_vault(redis_client=mock_redis, db_pool=db_pool)
        result = await vault.get_signatures("ACC010", "test-bank")
        assert len(result.embeddings) == 1
        assert len(result.embeddings[0]) == _DIM

    @pytest.mark.asyncio
    async def test_db_hit_backfills_redis(self):
        emb = _fake_embedding()
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        db_pool = self._make_db_pool([emb])
        vault = _make_vault(redis_client=mock_redis, db_pool=db_pool)
        await vault.get_signatures("ACC010", "test-bank")
        pipe_mock.rpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_miss_without_db_pool_is_vault_miss(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        vault = _make_vault(redis_client=mock_redis, db_pool=None)
        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.outcome == "HUMAN_REVIEW"
        assert result.miss_reason == "VAULT_MISS"


# ---------------------------------------------------------------------------
# Vault miss — MUST route to HUMAN_REVIEW, NEVER AUTO_RETURN
# ---------------------------------------------------------------------------

class TestVaultMiss:
    @pytest.mark.asyncio
    async def test_vault_miss_outcome_is_human_review(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_miss_embeddings_is_empty(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.embeddings == []

    @pytest.mark.asyncio
    async def test_vault_miss_reason_is_set(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(return_value=[])
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.miss_reason == "VAULT_MISS"

    @pytest.mark.asyncio
    async def test_vault_miss_outcome_is_never_auto_return(self):
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
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=ConnectionError("down"))
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC003", "test-bank")
        assert result is not None


# ---------------------------------------------------------------------------
# store_embeddings — write path
# ---------------------------------------------------------------------------

class TestStoreEmbeddings:
    @pytest.mark.asyncio
    async def test_store_uses_correct_redis_key(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        await vault.store_embeddings("ACC004", [_fake_embedding()])
        expected_key = vault._make_key("ACC004")
        pipe_mock.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_store_pushes_packed_bytes_for_each_embedding(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        embs = [_fake_embedding(1), _fake_embedding(2), _fake_embedding(3)]
        await vault.store_embeddings("ACC004", embs)
        assert pipe_mock.rpush.call_count == 3

    @pytest.mark.asyncio
    async def test_store_never_uses_raw_account_as_key(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        await vault.store_embeddings("ACC004", [_fake_embedding()])
        for call in pipe_mock.delete.call_args_list + pipe_mock.rpush.call_args_list:
            for arg in call[0]:
                if isinstance(arg, str):
                    assert "ACC004" not in arg

    @pytest.mark.asyncio
    async def test_store_invalidates_local_cache(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC004")
        vault._cache[key] = [_fake_embedding()]
        await vault.store_embeddings("ACC004", [_fake_embedding(9)])
        assert key not in vault._cache

    @pytest.mark.asyncio
    async def test_store_upserts_to_db_when_pool_provided(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)

        conn = AsyncMock()
        conn.execute = AsyncMock()
        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        vault = _make_vault(redis_client=mock_redis, db_pool=pool)
        await vault.store_embeddings("ACC005", [_fake_embedding()])
        conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Connect fallback
# ---------------------------------------------------------------------------

class TestSignatureVaultConnectFallback:
    def test_connect_without_redis_client_imports_redis(self, monkeypatch):
        import sys
        fake_redis_mod = MagicMock()
        fake_redis_instance = MagicMock()
        fake_redis_mod.Redis.return_value = fake_redis_instance
        monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="test-bank", pepper="pepper")
        vault.connect()
        assert vault._ready is True
        assert vault._redis is fake_redis_instance
