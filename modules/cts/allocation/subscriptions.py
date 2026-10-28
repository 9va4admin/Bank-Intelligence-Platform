"""
Reviewer-to-bucket subscriptions (admin-controlled).

A reviewer works only the buckets an admin has connected them to; MISC needs no subscription (anyone may self-claim
from it). The table is the source of truth; a short-lived Redis copy keeps allocation (which asks "who is subscribed to
this bucket?" for every item) off the database. Every write refreshes the copy.

With no database (dev/test) nobody is subscribed, so nothing is wrongly blocked.
"""
from __future__ import annotations

import json
from typing import Optional

import structlog

from modules.cts.buckets import ALL_BUCKETS

log = structlog.get_logger()

SUBSCRIBABLE = tuple(b for b in ALL_BUCKETS if b != "MISC")
_CACHE_KEY = "bucket-subs:"
_CACHE_TTL_SECONDS = 60

SQL_ALL = "SELECT bucket, reviewer_id FROM cts.reviewer_bucket_subscriptions WHERE bank_id = $1 ORDER BY bucket, reviewer_id"
SQL_BY_REVIEWER = "SELECT bucket FROM cts.reviewer_bucket_subscriptions WHERE bank_id = $1 AND reviewer_id = $2 ORDER BY bucket"
SQL_BY_BUCKET = "SELECT reviewer_id FROM cts.reviewer_bucket_subscriptions WHERE bank_id = $1 AND bucket = $2 ORDER BY reviewer_id"
SQL_DELETE_FOR_REVIEWER = "DELETE FROM cts.reviewer_bucket_subscriptions WHERE bank_id = $1 AND reviewer_id = $2"
SQL_DELETE_ONE = "DELETE FROM cts.reviewer_bucket_subscriptions WHERE bank_id = $1 AND reviewer_id = $2 AND bucket = $3"
SQL_INSERT = ("INSERT INTO cts.reviewer_bucket_subscriptions (bank_id, reviewer_id, bucket, created_by) "
              "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING")


class InvalidBucketError(ValueError):
    pass


class SubscriptionStore:
    def __init__(self, db_pool, redis=None) -> None:
        self._db = db_pool
        self._redis = redis

    async def get_all(self, bank_id: str) -> dict[str, list[str]]:
        """bucket -> reviewers subscribed to it (buckets nobody is subscribed to are present and empty)."""
        cached = await self._cache_get(bank_id)
        if cached is not None:
            return cached
        out: dict[str, list[str]] = {b: [] for b in SUBSCRIBABLE}
        if self._db is not None:
            async with self._db.acquire() as conn:
                for row in await conn.fetch(SQL_ALL, bank_id):
                    out.setdefault(row["bucket"], []).append(row["reviewer_id"])
        await self._cache_put(bank_id, out)
        return out

    async def get_subscribers(self, bank_id: str, bucket: str) -> list[str]:
        return list((await self.get_all(bank_id)).get(bucket, []))

    async def get_reviewer_buckets(self, bank_id: str, reviewer_id: str) -> list[str]:
        return sorted(b for b, who in (await self.get_all(bank_id)).items() if reviewer_id in who)

    async def set_reviewer_buckets(
        self, bank_id: str, reviewer_id: str, buckets: list[str], changed_by: str,
    ) -> tuple[list[str], list[str]]:
        """Replace a reviewer's buckets. Returns (added, removed)."""
        wanted = list(dict.fromkeys(buckets))
        bad = [b for b in wanted if b not in SUBSCRIBABLE]
        if bad:
            raise InvalidBucketError(f"not a subscribable bucket: {bad}. Valid: {list(SUBSCRIBABLE)}")
        if self._db is None:
            raise RuntimeError("database unavailable")
        before = set(await self.get_reviewer_buckets(bank_id, reviewer_id))
        async with self._db.acquire() as conn:
            async with conn.transaction():
                await conn.execute(SQL_DELETE_FOR_REVIEWER, bank_id, reviewer_id)
                for b in wanted:
                    await conn.execute(SQL_INSERT, bank_id, reviewer_id, b, changed_by)
        await self._cache_drop(bank_id)
        added, removed = sorted(set(wanted) - before), sorted(before - set(wanted))
        log.info("allocation.bucket_subscriptions_changed", bank_id=bank_id, reviewer_id=reviewer_id,
                 added=added, removed=removed, changed_by=changed_by)
        return added, removed

    # ---- cache -----------------------------------------------------------------------------------------------

    async def _cache_get(self, bank_id: str) -> Optional[dict[str, list[str]]]:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(f"{_CACHE_KEY}{bank_id}")
            if raw is None:
                return None
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:  # noqa: BLE001 - a broken cache must never block allocation
            return None

    async def _cache_put(self, bank_id: str, data: dict) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(f"{_CACHE_KEY}{bank_id}", json.dumps(data), ex=_CACHE_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            pass

    async def _cache_drop(self, bank_id: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(f"{_CACHE_KEY}{bank_id}")
        except Exception:  # noqa: BLE001
            pass
