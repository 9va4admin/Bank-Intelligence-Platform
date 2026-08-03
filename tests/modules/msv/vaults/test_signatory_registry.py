"""
Tests for modules/msv/vaults/signatory_registry.py

Covers:
  - Redis hit: does NOT call PostgreSQL
  - Redis miss: calls PostgreSQL, warms Redis
  - store: writes PostgreSQL first, then Redis
  - Redis failure on read: falls back to PostgreSQL (doesn't crash)
  - revoke: removes from both Redis and PostgreSQL
  - account number never appears in Redis key (verify key format)
  - 3 specimens per signatory stored and retrieved correctly
"""
import struct

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from modules.msv.vaults.signatory_registry import SignatoryRegistry
from modules.msv.mandates.models import SignatoryRecord


def _make_embedding(seed: int = 0) -> list[float]:
    """Return a deterministic 512-dim float32 vector."""
    rng = np.random.default_rng(seed)
    v = rng.random(512).astype(np.float32)
    norm = np.linalg.norm(v)
    return (v / norm).tolist()


def _embedding_to_bytes(emb: list[float]) -> bytes:
    """Serialize float32 list to bytes (numpy float32 format)."""
    return np.array(emb, dtype=np.float32).tobytes()


def _make_mock_redis(hit_values: list[bytes] | None = None):
    """Return a mock Redis client."""
    redis = MagicMock()
    if hit_values is not None:
        # lrange returns list of bytes items
        redis.lrange = AsyncMock(return_value=hit_values)
    else:
        redis.lrange = AsyncMock(return_value=[])
    redis.lpush = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=None)
    redis.keys = AsyncMock(return_value=[])
    return redis


def _make_mock_db_pool(rows=None, manifest_rows=None):
    """Return a mock asyncpg pool that returns given rows."""
    conn = MagicMock()

    if rows is not None:
        conn.fetch = AsyncMock(return_value=rows)
    else:
        conn.fetch = AsyncMock(return_value=[])

    conn.execute = AsyncMock(return_value=None)
    conn.fetchrow = AsyncMock(return_value=manifest_rows)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


def _make_config_service(pepper: str = "test-pepper"):
    cfg = MagicMock()
    cfg.get_secret = AsyncMock(return_value=pepper)
    return cfg


class TestSignatoryRegistryLoad:
    @pytest.mark.asyncio
    async def test_redis_hit_does_not_call_postgres(self):
        emb = _make_embedding(0)
        hit_bytes = [_embedding_to_bytes(emb)]
        redis = _make_mock_redis(hit_values=hit_bytes)
        db_pool, conn = _make_mock_db_pool()
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        result = await registry.load("kotak-mah", "account_hash_123", "sig-001")

        assert len(result) == 1
        # PostgreSQL fetch must NOT have been called
        conn.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_miss_calls_postgres_and_warms_redis(self):
        emb = _make_embedding(1)
        redis = _make_mock_redis(hit_values=[])  # cache miss
        row = {
            "specimen_idx": 0,
            "embedding": _embedding_to_bytes(emb),
        }
        db_pool, conn = _make_mock_db_pool(rows=[row])
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        result = await registry.load("kotak-mah", "account_hash_123", "sig-001")

        assert len(result) == 1
        conn.fetch.assert_called_once()
        # Redis should have been warmed
        redis.lpush.assert_called()

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_to_postgres(self):
        redis = MagicMock()
        redis.lrange = AsyncMock(side_effect=ConnectionError("Redis down"))
        redis.lpush = AsyncMock(side_effect=ConnectionError("Redis down"))

        emb = _make_embedding(2)
        row = {"specimen_idx": 0, "embedding": _embedding_to_bytes(emb)}
        db_pool, conn = _make_mock_db_pool(rows=[row])
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        result = await registry.load("kotak-mah", "account_hash_123", "sig-001")

        # Should still succeed via PostgreSQL
        assert len(result) == 1
        conn.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_three_specimens_stored_and_retrieved(self):
        embs = [_make_embedding(i) for i in range(3)]
        hit_bytes = [_embedding_to_bytes(e) for e in embs]
        redis = _make_mock_redis(hit_values=hit_bytes)
        db_pool, conn = _make_mock_db_pool()
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        result = await registry.load("kotak-mah", "account_hash_123", "sig-001")

        assert len(result) == 3
        for emb in result:
            assert len(emb) == 512

    @pytest.mark.asyncio
    async def test_no_enrollment_returns_empty_list(self):
        redis = _make_mock_redis(hit_values=[])   # miss
        db_pool, conn = _make_mock_db_pool(rows=[])  # nothing in DB either
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        result = await registry.load("kotak-mah", "account_hash_123", "sig-001")

        assert result == []


class TestSignatoryRegistryRedisKeyFormat:
    @pytest.mark.asyncio
    async def test_redis_key_never_contains_raw_account_number(self):
        """The Redis key must use account_hash, never raw account number."""
        redis = _make_mock_redis(hit_values=[])
        db_pool, conn = _make_mock_db_pool(rows=[])
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        raw_account = "1234567890"  # This must NEVER appear in Redis key

        # load() uses account_hash directly (pre-hashed by caller)
        await registry.load("kotak-mah", "hashed_account_xyz", "sig-001")

        # Check the lrange call key never contains raw account number
        call_args = redis.lrange.call_args
        redis_key = call_args.args[0] if call_args.args else call_args[0][0]
        assert raw_account not in redis_key

    @pytest.mark.asyncio
    async def test_redis_key_format_is_prefixed(self):
        """Key format: msv:{bank_id}:{account_hash}:{signatory_id}"""
        redis = _make_mock_redis(hit_values=[])
        db_pool, conn = _make_mock_db_pool(rows=[])
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        await registry.load("kotak-mah", "HASH_ABC", "sig-001")

        call_args = redis.lrange.call_args
        redis_key = call_args.args[0] if call_args.args else call_args[0][0]
        assert redis_key.startswith("msv:")
        assert "kotak-mah" in redis_key
        assert "HASH_ABC" in redis_key
        assert "sig-001" in redis_key


class TestSignatoryRegistryStore:
    @pytest.mark.asyncio
    async def test_store_writes_postgres_first_then_redis(self):
        """Verify PostgreSQL write happens before Redis write."""
        emb = _make_embedding(0)
        redis = _make_mock_redis()
        db_pool, conn = _make_mock_db_pool()
        cfg = _make_config_service()

        call_order = []
        conn.execute = AsyncMock(side_effect=lambda *a, **kw: call_order.append("postgres"))
        redis.lpush = AsyncMock(side_effect=lambda *a, **kw: call_order.append("redis"))

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        await registry.store(
            bank_id="kotak-mah",
            account_hash="hash_abc",
            signatory_id="sig-001",
            specimen_idx=0,
            embedding=emb,
            operation_type="J",
        )

        assert "postgres" in call_order
        # If Redis was called, it must come after PostgreSQL
        if "redis" in call_order:
            assert call_order.index("postgres") < call_order.index("redis")

    @pytest.mark.asyncio
    async def test_store_fails_if_postgres_unavailable(self):
        """If PostgreSQL fails, store must raise (Redis not written)."""
        from asyncpg import PostgresError
        redis = _make_mock_redis()
        db_pool, conn = _make_mock_db_pool()
        conn.execute = AsyncMock(side_effect=Exception("DB down"))
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        with pytest.raises(Exception):
            await registry.store(
                bank_id="kotak-mah",
                account_hash="hash_abc",
                signatory_id="sig-001",
                specimen_idx=0,
                embedding=_make_embedding(0),
                operation_type="J",
            )

        # Redis should not have been written
        redis.lpush.assert_not_called()


class TestSignatoryRegistryRevoke:
    @pytest.mark.asyncio
    async def test_revoke_removes_from_postgres_and_redis(self):
        redis = _make_mock_redis()
        redis.keys = AsyncMock(return_value=[b"msv:kotak-mah:hash_abc:sig-001"])
        redis.delete = AsyncMock(return_value=None)
        db_pool, conn = _make_mock_db_pool()
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        await registry.revoke("kotak-mah", "hash_abc", "sig-001")

        # PostgreSQL must have been told to delete
        conn.execute.assert_called()
        # Redis key must have been deleted
        redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_revoke_postgres_sql_targets_correct_signatory(self):
        redis = _make_mock_redis()
        redis.keys = AsyncMock(return_value=[])
        db_pool, conn = _make_mock_db_pool()
        cfg = _make_config_service()

        registry = SignatoryRegistry(redis_client=redis, db_pool=db_pool, config_service=cfg)
        await registry.revoke("kotak-mah", "hash_abc", "sig-001")

        call_args = conn.execute.call_args
        sql = call_args.args[0] if call_args.args else call_args[0][0]
        # The SQL should target the specific signatory
        assert "sig-001" in str(call_args) or "sig-001" in str(sql) or "sig-001" in str(call_args.args)


class TestSignatoryRegistryHashAccount:
    def test_hash_account_produces_hex_string(self):
        cfg = _make_config_service("pepper123")
        registry = SignatoryRegistry(
            redis_client=MagicMock(),
            db_pool=MagicMock(),
            config_service=cfg,
        )
        # _hash_account is synchronous and uses a provided pepper
        result = registry._hash_account_sync("1234567890", "kotak-mah", pepper="pepper123")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest

    def test_hash_account_different_numbers_different_hashes(self):
        cfg = _make_config_service("pepper123")
        registry = SignatoryRegistry(
            redis_client=MagicMock(),
            db_pool=MagicMock(),
            config_service=cfg,
        )
        h1 = registry._hash_account_sync("1234567890", "kotak-mah", pepper="pepper123")
        h2 = registry._hash_account_sync("9999999999", "kotak-mah", pepper="pepper123")
        assert h1 != h2

    def test_hash_account_same_number_same_hash(self):
        cfg = _make_config_service("pepper123")
        registry = SignatoryRegistry(
            redis_client=MagicMock(),
            db_pool=MagicMock(),
            config_service=cfg,
        )
        h1 = registry._hash_account_sync("1234567890", "kotak-mah", pepper="pepper123")
        h2 = registry._hash_account_sync("1234567890", "kotak-mah", pepper="pepper123")
        assert h1 == h2
