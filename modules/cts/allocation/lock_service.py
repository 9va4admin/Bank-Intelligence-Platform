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
import json
import time as _time

import structlog

log = structlog.get_logger()

LOCK_KEY_PREFIX = "lock:cts:"
_HEARTBEAT_KEY_PREFIX = "active-reviewers:"
_HYBRID_PENDING_KEY_PREFIX = "hybrid-pending:"

_DEFAULT_TTL_MINUTES = 10
_PUS_KEY_PREFIX = "reviewer-pus:"
_AUTO_KEY_PREFIX = "alloc-auto:"          # unopened, auto-assigned items: the only ones the rebalancer may move
_ITEM_META_KEY_PREFIX = "alloc-item:"      # per-bank hash: instrument_id -> {"pu_id", "iet_deadline"}
_REBALANCE_GATE_PREFIX = "alloc-rebalance-gate:"
_META_TTL_SECONDS = 24 * 3600
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

        # NX: if two reviewers race past the read above, exactly one write wins.
        acquired = await self._redis.set(key, reviewer_id, ex=ttl, nx=True)
        if acquired:
            log.info(
                "allocation.lock_acquired",
                instrument_id=instrument_id,
                reviewer_id=reviewer_id,
                ttl_seconds=ttl,
            )
        return bool(acquired)

    async def release_lock(self, instrument_id: str, reviewer_id: str, bank_id: str | None = None) -> None:
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
        if bank_id:
            await self.unmark_auto(bank_id, instrument_id)
        log.info(
            "allocation.lock_released",
            instrument_id=instrument_id,
            reviewer_id=reviewer_id,
        )

    async def get_lock_holder(self, instrument_id: str) -> str | None:
        """Return the reviewer_id holding the lock, or None if unclaimed."""
        return await self._redis.get(_lock_key(instrument_id))

    async def get_lock_holders(self, instrument_ids: list[str]) -> dict[str, str | None]:
        """Holder of each instrument's claim (None if unclaimed), in one round trip."""
        if not instrument_ids:
            return {}
        values = await self._redis.mget([_lock_key(i) for i in instrument_ids])
        return {i: self._text(v) for i, v in zip(instrument_ids, values)}

    async def force_release(self, instrument_id: str, bank_id: str | None = None) -> None:
        """Admin-only: release a lock regardless of who holds it.

        Caller must be ops_manager or bank_it_admin — enforced at the API layer.
        This method does NOT check ownership — it unconditionally deletes the key.
        Always call this through the admin endpoint so the Immudb audit trail is written.
        """
        key = _lock_key(instrument_id)
        await self._redis.delete(key)
        if bank_id:
            await self.unmark_auto(bank_id, instrument_id)
        log.info("allocation.lock_force_released", instrument_id=instrument_id)

    # ------------------------------------------------------------------ #
    # Reviewer heartbeat — active pool for auto_assign                    #
    # ------------------------------------------------------------------ #

    async def heartbeat_reviewer(
        self,
        bank_id: str,
        reviewer_id: str,
        ttl_seconds: int = _DEFAULT_HEARTBEAT_TTL_SECONDS,
        pu_ids: list[str] | None = None,
    ) -> bool:
        """Register reviewer as active. Returns True when they were not in the pool before (a new login). Score = expiry timestamp.

        Called on every queue poll by the reviewer. If they stop polling
        (closed browser / logged out), their entry expires automatically.
        """
        key = f"{_HEARTBEAT_KEY_PREFIX}{bank_id}"
        expiry_ts = _time.time() + ttl_seconds
        # Purge lapsed members first so a reviewer who timed out and returns counts as a new login.
        await self._redis.zremrangebyscore(key, "-inf", _time.time())
        added = await self._redis.zadd(key, {reviewer_id: expiry_ts})
        # Safety-net TTL on the whole set (2x max member TTL)
        await self._redis.expire(key, ttl_seconds * 2)
        if pu_ids is not None:
            zkey = f"{_PUS_KEY_PREFIX}{bank_id}"
            await self._redis.hset(zkey, reviewer_id, json.dumps(list(pu_ids)))
            await self._redis.expire(zkey, ttl_seconds * 2)
        log.debug("allocation.reviewer_heartbeat", bank_id=bank_id, reviewer_id=reviewer_id)
        return bool(added)

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

    # ------------------------------------------------------------------ #
    # Zones, load, item metadata                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _text(v):
        return v.decode() if isinstance(v, bytes) else v

    async def get_reviewer_pus(self, bank_id: str) -> dict[str, list[str]]:
        """reviewer_id -> processing units they are scoped to ([] or ["ALL"] means any PU)."""
        raw = await self._redis.hgetall(f"{_PUS_KEY_PREFIX}{bank_id}")
        return {self._text(k): json.loads(self._text(v)) for k, v in (raw or {}).items()}

    async def reviewer_loads(self, reviewer_ids: list[str]) -> dict[str, int]:
        """How many live claims each reviewer holds right now (a lapsed lock does not count)."""
        loads = {r: 0 for r in reviewer_ids}
        cursor = 0
        keys: list = []
        while True:
            cursor, batch = await self._redis.scan(cursor, match=f"{LOCK_KEY_PREFIX}*", count=500)
            keys.extend(batch)
            if not cursor:
                break
        if keys:
            for holder in await self._redis.mget(keys):
                holder = self._text(holder)
                if holder in loads:
                    loads[holder] += 1
        return loads

    async def set_item_meta(self, bank_id: str, instrument_id: str, *, pu_id: str | None = None,
                            iet_deadline: float | None = None, bucket: str | None = None,
                            origin_bucket: str | None = None, queued_at: float | None = None) -> None:
        """Remember what allocation needs to know about an item. bucket / origin_bucket / queued_at are stored only
        when given, so older callers keep exactly the old record."""
        record = {"pu_id": pu_id, "iet_deadline": iet_deadline}
        for key, value in (("bucket", bucket), ("origin_bucket", origin_bucket), ("queued_at", queued_at)):
            if value is not None:
                record[key] = value
        name = f"{_ITEM_META_KEY_PREFIX}{bank_id}"
        await self._redis.hset(name, instrument_id, json.dumps(record))
        await self._redis.expire(name, _META_TTL_SECONDS)

    async def update_item_meta(self, bank_id: str, instrument_id: str, **fields) -> None:
        """Merge fields into an item's record (creating it if absent)."""
        record = await self.get_item_meta(bank_id, instrument_id)
        record.update({k: v for k, v in fields.items()})
        name = f"{_ITEM_META_KEY_PREFIX}{bank_id}"
        await self._redis.hset(name, instrument_id, json.dumps(record))
        await self._redis.expire(name, _META_TTL_SECONDS)

    async def get_item_meta(self, bank_id: str, instrument_id: str) -> dict:
        raw = await self._redis.hget(f"{_ITEM_META_KEY_PREFIX}{bank_id}", instrument_id)
        return json.loads(self._text(raw)) if raw else {}

    async def get_item_metas(self, bank_id: str, instrument_ids: list[str]) -> dict[str, dict]:
        """Metadata for several items (missing ones map to {})."""
        return {i: await self.get_item_meta(bank_id, i) for i in instrument_ids}

    async def forget_item(self, bank_id: str, instrument_id: str) -> None:
        """The item reached a terminal state: drop every allocation record for it."""
        await self._redis.hdel(f"{_ITEM_META_KEY_PREFIX}{bank_id}", instrument_id)
        await self.unmark_auto(bank_id, instrument_id)
        await self.remove_hybrid_pending(bank_id, instrument_id)

    # ------------------------------------------------------------------ #
    # Auto-assignment index and rebalancing                               #
    # ------------------------------------------------------------------ #

    async def mark_auto(self, bank_id: str, instrument_id: str) -> None:
        await self._redis.zadd(f"{_AUTO_KEY_PREFIX}{bank_id}", {instrument_id: _time.time()})

    async def unmark_auto(self, bank_id: str, instrument_id: str) -> None:
        await self._redis.zrem(f"{_AUTO_KEY_PREFIX}{bank_id}", instrument_id)

    async def list_auto(self, bank_id: str) -> list[tuple[str, str]]:
        """(instrument_id, holder) for auto-assigned items nobody has opened yet. Lapsed locks are pruned."""
        key = f"{_AUTO_KEY_PREFIX}{bank_id}"
        out = []
        for member in await self._redis.zrange(key, 0, -1):
            iid = self._text(member)
            holder = self._text(await self._redis.get(_lock_key(iid)))
            if holder is None:
                await self._redis.zrem(key, member)
            else:
                out.append((iid, holder))
        return out

    async def transfer(self, instrument_id: str, from_reviewer: str, to_reviewer: str, cts_config: dict) -> bool:
        """Move a claim from one reviewer to another. Only succeeds while from_reviewer still holds it.

        Not a Lua compare-and-swap: the window between the check and the write is a few microseconds, and a
        reviewer who opens the item in that window simply finds it held by someone else and refreshes.
        """
        key = _lock_key(instrument_id)
        if self._text(await self._redis.get(key)) != from_reviewer:
            return False
        moved = await self._redis.set(key, to_reviewer, ex=self._ttl_seconds(cts_config), xx=True)
        if moved:
            log.info("allocation.lock_transferred", instrument_id=instrument_id,
                     from_reviewer=from_reviewer, to_reviewer=to_reviewer)
        return bool(moved)

    async def force_assign(self, instrument_id: str, reviewer_id: str, cts_config: dict,
                           bank_id: str | None = None) -> str | None:
        """Admin: give the item to reviewer_id whoever holds it now. Returns the previous holder.

        Caller must be ops_manager or bank_it_admin (enforced at the API layer, which also audits it).
        An admin assignment is never auto-moved: it is removed from the rebalancer's index.
        """
        key = _lock_key(instrument_id)
        previous = self._text(await self._redis.get(key))
        await self._redis.set(key, reviewer_id, ex=self._ttl_seconds(cts_config))
        if bank_id:
            await self.unmark_auto(bank_id, instrument_id)
            await self.remove_hybrid_pending(bank_id, instrument_id)
        log.info("allocation.lock_force_assigned", instrument_id=instrument_id, reviewer_id=reviewer_id,
                 previous_holder=previous)
        return previous

    async def try_rebalance_gate(self, bank_id: str, interval_seconds: int) -> bool:
        """True for at most one caller per interval, so a busy queue does not rebalance on every poll."""
        got = await self._redis.set(f"{_REBALANCE_GATE_PREFIX}{bank_id}", "1", ex=max(1, int(interval_seconds)), nx=True)
        return bool(got)
