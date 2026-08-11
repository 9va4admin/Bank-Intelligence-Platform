"""
Phase E — LockService TDD tests.

LockService uses Redis TTL keys (lock:cts:{instrument_id}) to prevent two
ops_reviewers from claiming the same cheque simultaneously. It is stateless
and dependency-injected with a Redis client.

All TTL values come from cts_config — never hardcoded.
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis():
    """Fake Redis client with enough surface area for LockService."""
    redis = AsyncMock()
    redis._store: dict = {}

    async def set_nx(key, value, ex=None):
        if key in redis._store:
            return False
        redis._store[key] = value
        return True

    async def delete(key):
        redis._store.pop(key, None)

    async def get(key):
        return redis._store.get(key)

    async def expire(key, seconds):
        pass  # TTL management tested separately

    redis.set = AsyncMock(side_effect=set_nx)
    redis.delete = AsyncMock(side_effect=delete)
    redis.get = AsyncMock(side_effect=get)
    redis.expire = AsyncMock(side_effect=expire)
    return redis


def _cfg(lock_ttl_minutes=10):
    return {"allocation_lock_ttl_minutes": lock_ttl_minutes}


# ---------------------------------------------------------------------------
# 1. LockService initialises
# ---------------------------------------------------------------------------

class TestLockServiceInit:
    def test_lock_service_importable(self):
        from modules.cts.allocation.lock_service import LockService
        assert LockService is not None

    def test_lock_service_instantiable_with_redis(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        assert svc is not None


# ---------------------------------------------------------------------------
# 2. acquire_lock
# ---------------------------------------------------------------------------

class TestAcquireLock:
    @pytest.mark.asyncio
    async def test_acquire_returns_true_on_success(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        result = await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_uses_correct_redis_key(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        call_args = redis.set.call_args
        key_used = call_args[0][0] if call_args[0] else call_args[1].get("name", call_args[1].get("key", ""))
        assert "INST001" in str(call_args)

    @pytest.mark.asyncio
    async def test_acquire_stores_reviewer_id(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        holder = await svc.get_lock_holder("INST001")
        assert holder == "reviewer-1"

    @pytest.mark.asyncio
    async def test_acquire_returns_false_when_already_held(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        result = await svc.acquire_lock("INST001", "reviewer-2", _cfg())
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_same_reviewer_returns_true(self):
        """Re-entrant: same reviewer can re-claim their own lock."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        result = await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_uses_ttl_from_config(self):
        """TTL must come from config, not be hardcoded."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", {"allocation_lock_ttl_minutes": 5})
        call_args = redis.set.call_args
        # ex param should be 5 * 60 = 300 seconds
        all_args = str(call_args)
        assert "300" in all_args

    @pytest.mark.asyncio
    async def test_acquire_uses_default_ttl_when_config_missing(self):
        """Falls back to 10-minute default when key absent."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        # Empty config — should not crash; default TTL applies
        result = await svc.acquire_lock("INST001", "reviewer-1", {})
        assert result is True


# ---------------------------------------------------------------------------
# 3. release_lock
# ---------------------------------------------------------------------------

class TestReleaseLock:
    @pytest.mark.asyncio
    async def test_release_removes_lock(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        await svc.release_lock("INST001", "reviewer-1")
        holder = await svc.get_lock_holder("INST001")
        assert holder is None

    @pytest.mark.asyncio
    async def test_release_by_non_owner_does_not_remove(self):
        """reviewer-2 cannot release reviewer-1's lock."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        await svc.release_lock("INST001", "reviewer-2")
        holder = await svc.get_lock_holder("INST001")
        assert holder == "reviewer-1"

    @pytest.mark.asyncio
    async def test_release_non_existent_lock_does_not_raise(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.release_lock("INST-NONEXISTENT", "reviewer-1")  # no exception

    @pytest.mark.asyncio
    async def test_after_release_another_reviewer_can_acquire(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-1", _cfg())
        await svc.release_lock("INST001", "reviewer-1")
        result = await svc.acquire_lock("INST001", "reviewer-2", _cfg())
        assert result is True


# ---------------------------------------------------------------------------
# 4. get_lock_holder
# ---------------------------------------------------------------------------

class TestGetLockHolder:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_lock(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        assert await svc.get_lock_holder("INST-UNCLAIMED") is None

    @pytest.mark.asyncio
    async def test_returns_reviewer_id_when_locked(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST001", "reviewer-42", _cfg())
        assert await svc.get_lock_holder("INST001") == "reviewer-42"


# ---------------------------------------------------------------------------
# 5. Redis key format
# ---------------------------------------------------------------------------

class TestRedisKeyFormat:
    @pytest.mark.asyncio
    async def test_key_contains_instrument_id(self):
        from modules.cts.allocation.lock_service import LockService, LOCK_KEY_PREFIX
        redis = _make_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST-XYZ", "reviewer-1", _cfg())
        # Lock key must include the instrument ID
        assert any("INST-XYZ" in str(k) for k in redis._store.keys())

    def test_lock_key_prefix_constant_exists(self):
        from modules.cts.allocation.lock_service import LOCK_KEY_PREFIX
        assert LOCK_KEY_PREFIX.startswith("lock:cts:")
