"""
Redis-backed distributed lock for ASTRA idempotency guarantees.

Pattern: SET key value NX PX ttl_ms (atomic acquire, auto-release on TTL).

Used by API routes before starting Temporal workflows to prevent thundering-herd
duplicate submissions. Temporal workflow IDs are the primary exactly-once guarantee;
this lock prevents the brief window where two concurrent requests race to start the
same workflow_id before Temporal's dedup kicks in.

Key pattern: lock:workflow:{bank_id}:{workflow_id}
"""
import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.distributed_lock")

# Default TTL for workflow locks — short enough that a crashed caller doesn't block for long
_DEFAULT_LOCK_TTL_MS = 10_000  # 10 seconds


class LockAcquireError(Exception):
    """Raised when lock cannot be acquired (held by another caller)."""


class DistributedLock:
    """
    Redis-backed SET NX PX lock. Auto-releases on TTL expiry.

    Usage (API route):
        lock = DistributedLock(redis_cts, bank_id="hdfc", resource_id=workflow_id)
        async with lock.acquire():
            await temporal_client.start_workflow(...)

    Non-blocking: raises LockAcquireError immediately if lock is held.
    The caller should treat this as the resource already being processed.
    """

    def __init__(
        self,
        redis,
        bank_id: str,
        resource_id: str,
        resource_type: str = "workflow",
        ttl_ms: int = _DEFAULT_LOCK_TTL_MS,
    ) -> None:
        self._redis = redis
        self._key = f"lock:{resource_type}:{bank_id}:{resource_id}"
        self._token = str(uuid.uuid4())  # unique per caller — prevents accidental cross-caller release
        self._ttl_ms = ttl_ms
        self._bank_id = bank_id
        self._resource_id = resource_id

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """
        Acquire the lock. Releases on context exit (or TTL expiry if caller crashes).
        Raises LockAcquireError if already held.
        """
        with tracer.start_as_current_span("distributed_lock.acquire") as span:
            span.set_attribute("lock_key", self._key)
            span.set_attribute("bank_id", self._bank_id)

            try:
                acquired = await self._redis.set(
                    self._key,
                    self._token,
                    nx=True,         # only set if not exists
                    px=self._ttl_ms, # TTL in milliseconds
                )

                if not acquired:
                    span.set_attribute("lock_acquired", False)
                    log.info(
                        "distributed_lock.already_held",
                        key=self._key,
                        bank_id=self._bank_id,
                        resource_id=self._resource_id,
                    )
                    raise LockAcquireError(
                        f"Lock already held for resource '{self._resource_id}' — likely duplicate request in-flight"
                    )

                span.set_attribute("lock_acquired", True)
                log.debug("distributed_lock.acquired", key=self._key)
                yield

            finally:
                await self._release()

    async def _release(self) -> None:
        """Release the lock only if we still hold it (token check prevents cross-caller release)."""
        try:
            # Lua script for atomic check-and-delete
            lua_script = """
            if redis.call("GET", KEYS[1]) == ARGV[1] then
                return redis.call("DEL", KEYS[1])
            else
                return 0
            end
            """
            result = await self._redis.eval(lua_script, 1, self._key, self._token)
            if result == 0:
                log.debug("distributed_lock.already_released_or_expired", key=self._key)
        except Exception as exc:
            log.warning("distributed_lock.release_failed", key=self._key, error=str(exc))


async def try_acquire_workflow_lock(
    redis,
    bank_id: str,
    workflow_id: str,
    ttl_ms: int = _DEFAULT_LOCK_TTL_MS,
) -> Optional[DistributedLock]:
    """
    Convenience function: try to acquire a workflow lock.
    Returns the lock object if acquired, None if already held (duplicate in-flight).

    Usage in API route (without context manager, for fire-and-forget style):
        lock = await try_acquire_workflow_lock(redis, bank_id, workflow_id)
        if lock is None:
            return already_accepted_response()
        try:
            await temporal_client.start_workflow(...)
        finally:
            await lock._release()
    """
    if redis is None:
        return None  # fail-open: no Redis → skip locking, Temporal handles dedup

    lock = DistributedLock(redis=redis, bank_id=bank_id, resource_id=workflow_id)
    try:
        acquired = await redis.set(lock._key, lock._token, nx=True, px=ttl_ms)
        if acquired:
            return lock
        return None
    except Exception as exc:
        log.warning("distributed_lock.acquire_error", workflow_id=workflow_id, error=str(exc))
        return None  # fail-open
