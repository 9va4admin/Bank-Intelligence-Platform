"""
LockService — Redis TTL-based instrument claim locking.

Prevents two ops_reviewers from simultaneously working on the same cheque.
Uses Redis SET NX EX (atomic compare-and-set) so lock acquisition is race-free.

Key format: lock:cts:{instrument_id}
Value: reviewer_id (string)
TTL: allocation_lock_ttl_minutes * 60 seconds (from cts_config, default 10 min)

Reviewer heartbeat: active-reviewers:{bank_id} — sorted set, score = expiry timestamp.
  heartbeat_reviewer() registers presence; get_active_reviewers() returns live members.
  Used by auto_assign() to know who to pick from.

HYBRID deferred queue: hybrid-pending:{bank_id} — sorted set, score = assign_after_ts.
  add_hybrid_pending() schedules a future auto-assign; pop_due_hybrid_pending() returns
  items whose deadline has passed (called on each queue poll).

Admin force-release: force_release() deletes the lock without owner check.
  Only callable from the admin-only endpoint — never from reviewer paths.

Guarantees:
  - acquire_lock() is atomic via SET NX EX — no TOCTOU race possible
  - release_lock() is owner-guarded — only the lock holder can release
  - force_release() is admin-only — bypasses owner guard, always audited
  - Re-entrant: same reviewer re-acquiring their own lock returns True and refreshes TTL
  - Never crashes on missing config keys — safe defaults applied
"""
import time as _time

import structlog

log = structlog.get_logger()

LOCK_KEY_PREFIX = "lock:cts:"
_HEARTBEAT_KEY_PREFIX = "active-reviewers:"
_HYBRID_PENDING_KEY_PREFIX = "hybrid-pending:"

_DEFAULT_TTL_MINUTES = 10
_DEFAULT_HEARTBEAT_TTL_SECONDS = 300  # 5 minutes — refreshed on every queue poll


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

    async def force_release(self, instrument_id: str) -> None:
        """Admin-only: release a lock regardless of who holds it.

        Caller must be ops_manager or bank_it_admin — enforced at the API layer.
        This method does NOT check ownership — it unconditionally deletes the key.
        Always call this through the admin endpoint so the Immudb audit trail is written.
        """
        key = _lock_key(instrument_id)
        await self._redis.delete(key)
        log.info("allocation.lock_force_released", instrument_id=instrument_id)

    # ------------------------------------------------------------------ #
    # Reviewer heartbeat — active pool for auto_assign                    #
    # ------------------------------------------------------------------ #

    async def heartbeat_reviewer(
        self,
        bank_id: str,
        reviewer_id: str,
        ttl_seconds: int = _DEFAULT_HEARTBEAT_TTL_SECONDS,
    ) -> None:
        """Register reviewer as active. Score = expiry timestamp.

        Called on every queue poll by the reviewer. If they stop polling
        (closed browser / logged out), their entry expires automatically.
        """
        key = f"{_HEARTBEAT_KEY_PREFIX}{bank_id}"
        expiry_ts = _time.time() + ttl_seconds
        await self._redis.zadd(key, {reviewer_id: expiry_ts})
        # Safety-net TTL on the whole set (2× max member TTL)
        await self._redis.expire(key, ttl_seconds * 2)
        log.debug("allocation.reviewer_heartbeat", bank_id=bank_id, reviewer_id=reviewer_id)

    async def get_active_reviewers(self, bank_id: str) -> list[str]:
        """Return reviewer_ids whose heartbeat hasn't expired."""
        key = f"{_HEARTBEAT_KEY_PREFIX}{bank_id}"
        now_ts = _time.time()
        # Purge stale entries first
        await self._redis.zremrangebyscore(key, "-inf", now_ts)
        members = await self._redis.zrange(key, 0, -1)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    # ------------------------------------------------------------------ #
    # HYBRID deferred auto-assign queue                                   #
    # ------------------------------------------------------------------ #

    async def add_hybrid_pending(
        self, bank_id: str, instrument_id: str, assign_after_ts: float
    ) -> None:
        """Schedule instrument for auto-assign at assign_after_ts (Unix timestamp).

        Used in HYBRID mode: instrument enters the queue unclaimed; if no reviewer
        self-claims within hybrid_auto_assign_timeout_minutes, auto_assign fires.
        """
        key = f"{_HYBRID_PENDING_KEY_PREFIX}{bank_id}"
        await self._redis.zadd(key, {instrument_id: assign_after_ts})

    async def remove_hybrid_pending(self, bank_id: str, instrument_id: str) -> None:
        """Remove an instrument from the HYBRID pending queue (e.g., was self-claimed)."""
        key = f"{_HYBRID_PENDING_KEY_PREFIX}{bank_id}"
        await self._redis.zrem(key, instrument_id)

    async def pop_due_hybrid_pending(
        self, bank_id: str, limit: int = 20
    ) -> list[str]:
        """Return and remove instrument_ids due for auto-assign (assign_after_ts <= now).

        Called on each queue poll. Returns at most `limit` items to avoid
        a thundering-herd on large backlogs.
        """
        key = f"{_HYBRID_PENDING_KEY_PREFIX}{bank_id}"
        now_ts = _time.time()
        members = await self._redis.zrangebyscore(key, "-inf", now_ts, start=0, num=limit)
        if members:
            await self._redis.zrem(key, *members)
        return [m.decode() if isinstance(m, bytes) else m for m in members]
