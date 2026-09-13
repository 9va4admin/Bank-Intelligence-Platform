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


# ---------------------------------------------------------------------------
# Extended helper — adds sorted set operations for heartbeat / HYBRID tests
# ---------------------------------------------------------------------------

def _make_full_redis():
    """Fake Redis with lock key + sorted set support."""
    redis = AsyncMock()
    redis._store: dict = {}
    redis._zsets: dict = {}

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
        pass

    async def zadd(key, mapping):
        if key not in redis._zsets:
            redis._zsets[key] = {}
        redis._zsets[key].update(mapping)

    async def zremrangebyscore(key, min_s, max_s):
        if key not in redis._zsets:
            return
        min_f = float("-inf") if min_s == "-inf" else float(min_s)
        max_f = float("inf") if max_s == "+inf" else float(max_s)
        stale = [m for m, s in redis._zsets[key].items() if min_f <= s <= max_f]
        for m in stale:
            del redis._zsets[key][m]

    async def zrange(key, start, stop):
        if key not in redis._zsets:
            return []
        items = sorted(redis._zsets[key].items(), key=lambda x: x[1])
        members = [m for m, _ in items]
        return members[start:] if stop == -1 else members[start : stop + 1]

    async def zrangebyscore(key, min_s, max_s, start=0, num=None):
        if key not in redis._zsets:
            return []
        min_f = float("-inf") if min_s == "-inf" else float(min_s)
        max_f = float("inf") if max_s == "+inf" else float(max_s)
        items = sorted(redis._zsets[key].items(), key=lambda x: x[1])
        members = [m for m, s in items if min_f <= s <= max_f]
        result = members[start:]
        return result[:num] if num is not None else result

    async def zrem(key, *members):
        if key not in redis._zsets:
            return
        for m in members:
            redis._zsets[key].pop(m, None)

    redis.set = AsyncMock(side_effect=set_nx)
    redis.delete = AsyncMock(side_effect=delete)
    redis.get = AsyncMock(side_effect=get)
    redis.expire = AsyncMock(side_effect=expire)
    redis.zadd = AsyncMock(side_effect=zadd)
    redis.zremrangebyscore = AsyncMock(side_effect=zremrangebyscore)
    redis.zrange = AsyncMock(side_effect=zrange)
    redis.zrangebyscore = AsyncMock(side_effect=zrangebyscore)
    redis.zrem = AsyncMock(side_effect=zrem)
    return redis


# ---------------------------------------------------------------------------
# 6. force_release
# ---------------------------------------------------------------------------

class TestForceRelease:
    @pytest.mark.asyncio
    async def test_force_release_removes_lock_regardless_of_owner(self):
        """Admin force_release deletes lock even when caller is not the lock holder."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST-FR-01", "reviewer-1", _cfg())
        assert await svc.get_lock_holder("INST-FR-01") == "reviewer-1"
        await svc.force_release("INST-FR-01")
        assert await svc.get_lock_holder("INST-FR-01") is None

    @pytest.mark.asyncio
    async def test_force_release_on_unclaimed_instrument_does_not_raise(self):
        """force_release on a key that does not exist is a safe no-op."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        await svc.force_release("INST-NONEXISTENT")

    @pytest.mark.asyncio
    async def test_after_force_release_new_reviewer_can_acquire(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        await svc.acquire_lock("INST-FR-02", "reviewer-1", _cfg())
        await svc.force_release("INST-FR-02")
        result = await svc.acquire_lock("INST-FR-02", "reviewer-2", _cfg())
        assert result is True


# ---------------------------------------------------------------------------
# 7. Reviewer heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeatReviewer:
    @pytest.mark.asyncio
    async def test_heartbeat_registers_reviewer_in_sorted_set(self):
        """heartbeat_reviewer must add reviewer to the sorted set."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        await svc.heartbeat_reviewer("saraswat-coop", "ananya.krishnan")
        assert "active-reviewers:saraswat-coop" in redis._zsets
        assert "ananya.krishnan" in redis._zsets["active-reviewers:saraswat-coop"]

    @pytest.mark.asyncio
    async def test_heartbeat_score_is_future_timestamp(self):
        """Score stored must be a future Unix timestamp (now + ttl_seconds)."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        before = time.time()
        await svc.heartbeat_reviewer("saraswat-coop", "reviewer-x", ttl_seconds=300)
        after = time.time()
        score = redis._zsets["active-reviewers:saraswat-coop"]["reviewer-x"]
        assert before + 299 <= score <= after + 301

    @pytest.mark.asyncio
    async def test_get_active_reviewers_returns_live_members(self):
        """Reviewer with future expiry timestamp is returned."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        redis._zsets["active-reviewers:saraswat-coop"] = {
            "ananya.krishnan": time.time() + 300
        }
        result = await svc.get_active_reviewers("saraswat-coop")
        assert "ananya.krishnan" in result

    @pytest.mark.asyncio
    async def test_get_active_reviewers_excludes_expired_members(self):
        """Reviewer whose expiry timestamp is in the past is pruned."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        redis._zsets["active-reviewers:saraswat-coop"] = {
            "stale.reviewer": time.time() - 1
        }
        result = await svc.get_active_reviewers("saraswat-coop")
        assert "stale.reviewer" not in result

    @pytest.mark.asyncio
    async def test_get_active_reviewers_returns_empty_when_no_heartbeats(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        result = await svc.get_active_reviewers("new-bank-no-reviewers")
        assert result == []


# ---------------------------------------------------------------------------
# 8. HYBRID pending queue
# ---------------------------------------------------------------------------

class TestHybridPendingQueue:
    @pytest.mark.asyncio
    async def test_add_hybrid_pending_stores_with_correct_score(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        assign_at = time.time() + 300.0
        await svc.add_hybrid_pending("saraswat-coop", "INST-HP-01", assign_at)
        key = "hybrid-pending:saraswat-coop"
        assert key in redis._zsets
        assert "INST-HP-01" in redis._zsets[key]
        assert redis._zsets[key]["INST-HP-01"] == assign_at

    @pytest.mark.asyncio
    async def test_pop_due_hybrid_pending_returns_and_removes_due_items(self):
        """Items with assign_after_ts <= now are returned and removed from the set."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        redis._zsets["hybrid-pending:saraswat-coop"] = {
            "INST-DUE-01": time.time() - 1
        }
        result = await svc.pop_due_hybrid_pending("saraswat-coop")
        assert "INST-DUE-01" in result
        assert "INST-DUE-01" not in redis._zsets.get("hybrid-pending:saraswat-coop", {})

    @pytest.mark.asyncio
    async def test_pop_due_hybrid_pending_skips_future_items(self):
        """Items with assign_after_ts > now are NOT returned."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        redis._zsets["hybrid-pending:saraswat-coop"] = {
            "INST-FUTURE": time.time() + 10000
        }
        result = await svc.pop_due_hybrid_pending("saraswat-coop")
        assert result == []

    @pytest.mark.asyncio
    async def test_pop_due_hybrid_pending_returns_empty_when_queue_empty(self):
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        result = await svc.pop_due_hybrid_pending("empty-bank")
        assert result == []

    @pytest.mark.asyncio
    async def test_remove_hybrid_pending_removes_specific_instrument(self):
        """remove_hybrid_pending removes target but leaves siblings untouched."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        redis._zsets["hybrid-pending:saraswat-coop"] = {
            "INST-A": time.time() + 100,
            "INST-B": time.time() + 200,
        }
        await svc.remove_hybrid_pending("saraswat-coop", "INST-A")
        key = "hybrid-pending:saraswat-coop"
        assert "INST-A" not in redis._zsets[key]
        assert "INST-B" in redis._zsets[key]

    @pytest.mark.asyncio
    async def test_pop_due_hybrid_pending_respects_limit(self):
        """pop_due returns at most `limit` items even when more are due."""
        from modules.cts.allocation.lock_service import LockService
        redis = _make_full_redis()
        svc = LockService(redis_client=redis)
        past = time.time() - 1
        redis._zsets["hybrid-pending:saraswat-coop"] = {
            f"INST-{i:03d}": past - i for i in range(5)
        }
        result = await svc.pop_due_hybrid_pending("saraswat-coop", limit=3)
        assert len(result) == 3
