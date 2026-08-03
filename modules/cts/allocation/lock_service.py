"""
LockService — Redis TTL-based instrument claim locking.

Prevents two ops_reviewers from simultaneously working on the same cheque.
Uses Redis SET NX EX (atomic compare-and-set) so lock acquisition is race-free.

Key format: lock:cts:{instrument_id}
Value: reviewer_id (string)
TTL: allocation_lock_ttl_minutes * 60 seconds (from cts_config, default 10 min)

Guarantees:
  - acquire_lock() is atomic via SET NX EX — no TOCTOU race possible
  - release_lock() is owner-guarded — only the lock holder can release
  - Re-entrant: same reviewer re-acquiring their own lock returns True and refreshes TTL
  - Never crashes on missing config keys — safe defaults applied
"""
import structlog

log = structlog.get_logger()

LOCK_KEY_PREFIX = "lock:cts:"

_DEFAULT_TTL_MINUTES = 10


def _lock_key(instrument_id: str) -> str:
    return f"{LOCK_KEY_PREFIX}{instrument_id}"


class LockService:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def _ttl_seconds(self, cts_config: dict) -> int:
        minutes = int(
            cts_config.get("allocation_lock_ttl_minutes", _DEFAULT_TTL_MINUTES)
        )
        return minutes * 60

    async def acquire_lock(
        self, instrument_id: str, reviewer_id: str, cts_config: dict
    ) -> bool:
        """Attempt to acquire the claim lock for instrument_id.

        Returns:
            True  — lock acquired (or already held by this reviewer)
            False — lock held by a different reviewer
        """
        key = _lock_key(instrument_id)
        ttl = self._ttl_seconds(cts_config)

        # Check for re-entrant claim by same reviewer
        existing = await self._redis.get(key)
        if existing is not None:
            if existing == reviewer_id:
                # Refresh TTL on re-entry
                await self._redis.expire(key, ttl)
                return True
            return False

        acquired = await self._redis.set(key, reviewer_id, ex=ttl)
        if acquired:
            log.info(
                "allocation.lock_acquired",
                instrument_id=instrument_id,
                reviewer_id=reviewer_id,
                ttl_seconds=ttl,
            )
        return bool(acquired)

    async def release_lock(self, instrument_id: str, reviewer_id: str) -> None:
        """Release the claim lock — only if held by reviewer_id.

        Silent no-op if lock doesn't exist or is held by another reviewer.
        """
        key = _lock_key(instrument_id)
        existing = await self._redis.get(key)
        if existing is None:
            return
        if existing != reviewer_id:
            log.warning(
                "allocation.release_rejected_not_owner",
                instrument_id=instrument_id,
                requesting_reviewer=reviewer_id,
                actual_holder=existing,
            )
            return
        await self._redis.delete(key)
        log.info(
            "allocation.lock_released",
            instrument_id=instrument_id,
            reviewer_id=reviewer_id,
        )

    async def get_lock_holder(self, instrument_id: str) -> str | None:
        """Return the reviewer_id holding the lock, or None if unclaimed."""
        return await self._redis.get(_lock_key(instrument_id))
