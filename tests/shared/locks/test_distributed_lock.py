"""
Tests for Redis distributed lock — idempotency guard for workflow submissions.

TDD: RED first confirmed. Tests verify:
  - Lock acquired with SET NX PX
  - Lock denied when already held (NX condition)
  - Lock released on context exit (Lua atomic check-and-delete)
  - Fail-open when Redis is None
  - Token uniqueness prevents cross-caller release
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.locks.distributed_lock import (
    DistributedLock,
    LockAcquireError,
    try_acquire_workflow_lock,
)


class TestDistributedLock:
    def _make_redis(self, set_returns=True, eval_returns=1):
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=set_returns)
        redis.eval = AsyncMock(return_value=eval_returns)
        redis.get = AsyncMock(return_value=None)
        return redis

    @pytest.mark.asyncio
    async def test_acquires_lock_when_available(self):
        """Lock should be acquired when Redis SET NX returns True."""
        redis = self._make_redis(set_returns=True)
        lock = DistributedLock(redis, bank_id="hdfc", resource_id="wf-001")

        async with lock.acquire():
            redis.set.assert_called_once()
            call_kwargs = redis.set.call_args
            assert call_kwargs.kwargs.get("nx") is True
            assert call_kwargs.kwargs.get("px") > 0

    @pytest.mark.asyncio
    async def test_raises_when_lock_held(self):
        """LockAcquireError raised when Redis SET NX returns None (already held)."""
        redis = self._make_redis(set_returns=None)
        lock = DistributedLock(redis, bank_id="hdfc", resource_id="wf-001")

        with pytest.raises(LockAcquireError):
            async with lock.acquire():
                pass

    @pytest.mark.asyncio
    async def test_releases_on_context_exit(self):
        """Lock must be released (Lua eval called) on normal context exit."""
        redis = self._make_redis(set_returns=True, eval_returns=1)
        lock = DistributedLock(redis, bank_id="hdfc", resource_id="wf-001")

        async with lock.acquire():
            pass

        redis.eval.assert_called_once()
        # Lua script checks token before deleting
        call_args = redis.eval.call_args[0]
        assert lock._token in call_args  # token passed to Lua

    @pytest.mark.asyncio
    async def test_releases_on_exception(self):
        """Lock must be released even if code inside context raises."""
        redis = self._make_redis(set_returns=True, eval_returns=1)
        lock = DistributedLock(redis, bank_id="hdfc", resource_id="wf-001")

        with pytest.raises(ValueError):
            async with lock.acquire():
                raise ValueError("something went wrong")

        redis.eval.assert_called_once()  # release was still called

    @pytest.mark.asyncio
    async def test_unique_token_per_lock_instance(self):
        """Each DistributedLock instance gets a unique token — prevents cross-caller release."""
        redis = self._make_redis(set_returns=True)
        lock1 = DistributedLock(redis, bank_id="hdfc", resource_id="wf-001")
        lock2 = DistributedLock(redis, bank_id="hdfc", resource_id="wf-001")
        assert lock1._token != lock2._token

    @pytest.mark.asyncio
    async def test_key_includes_bank_and_resource(self):
        """Lock key must include bank_id and resource_id for proper scoping."""
        redis = self._make_redis()
        lock = DistributedLock(redis, bank_id="hdfc", resource_id="wf-instrument-001")
        assert "hdfc" in lock._key
        assert "wf-instrument-001" in lock._key

    @pytest.mark.asyncio
    async def test_does_not_release_if_token_mismatch(self):
        """Lua script returns 0 if token doesn't match — should log but not raise."""
        redis = self._make_redis(set_returns=True, eval_returns=0)
        lock = DistributedLock(redis, bank_id="hdfc", resource_id="wf-001")
        # Should not raise even if Lua returns 0 (TTL expired between acquire and release)
        async with lock.acquire():
            pass


class TestTryAcquireWorkflowLock:
    @pytest.mark.asyncio
    async def test_returns_lock_on_success(self):
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.eval = AsyncMock(return_value=1)
        lock = await try_acquire_workflow_lock(redis, "hdfc", "cts-hdfc-inst001")
        assert lock is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_held(self):
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=None)  # NX condition: already exists
        lock = await try_acquire_workflow_lock(redis, "hdfc", "cts-hdfc-inst001")
        assert lock is None

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_is_none(self):
        """Fail-open: no Redis → no lock (Temporal handles dedup)."""
        lock = await try_acquire_workflow_lock(None, "hdfc", "cts-hdfc-inst001")
        assert lock is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self):
        """Fail-open: Redis error → no lock."""
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        lock = await try_acquire_workflow_lock(redis, "hdfc", "cts-hdfc-inst001")
        assert lock is None
