"""The bell: each user's own notifications (platform.user_notifications). Every statement is scoped to bank AND user, so nobody can read or touch
another person's inbox. The bell is the channel that always works while the web app does, so every alert addressed to a person also lands here."""
from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, Optional

from shared.alerting.incidents import MAX_LIST, _is_conflict
from shared.alerting.paging import Page, decode_cursor, page_of

_SEVERITIES = ("P0", "P1", "P2", "P3")
_COLUMNS = "notification_id, incident_id, severity, title, body, action_link, created_at, read_at, acked_at"


class InboxStore:
    def __init__(self, pool: Any, *, max_attempts: int = 6, retry_backoff_seconds: float = 0.03) -> None:
        self._pool, self._max_attempts, self._backoff = pool, max(1, max_attempts), retry_backoff_seconds

    async def _retrying(self, fn):
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001
                if not _is_conflict(exc) or attempt == self._max_attempts:
                    raise
                await asyncio.sleep(self._backoff * attempt * (0.5 + random.random()))

    async def add(self, *, bank_id: str, user_id: str, severity: str, title: str, body: str = "", action_link: Optional[str] = None,
                  incident_id: Optional[str] = None) -> str:
        notification_id = uuid.uuid4().hex
        await self._retrying(lambda: self._pool.execute(
            "INSERT INTO platform.user_notifications (notification_id, bank_id, user_id, incident_id, severity, title, body, action_link) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)", notification_id, bank_id, user_id, incident_id, severity, title, body, action_link))
        return notification_id

    async def list_for_user(self, bank_id: str, user_id: str, *, limit: int, cursor: Optional[str] = None, unread_only: bool = False) -> Page:
        """Newest first. Raises ValueError for a bad cursor."""
        limit = min(max(limit, 1), MAX_LIST)
        clauses, args = ["bank_id = $1", "user_id = $2"], [bank_id, user_id]
        if unread_only:
            clauses.append("read_at IS NULL")
        if cursor:
            moment, row_id = decode_cursor(cursor)
            args += [moment, row_id]
            clauses.append(f"(created_at, notification_id) < (${len(args) - 1}, ${len(args)})")
        args.append(limit + 1)
        rows = await self._pool.fetch(
            f"SELECT {_COLUMNS} FROM platform.user_notifications WHERE " + " AND ".join(clauses)
            + f" ORDER BY created_at DESC, notification_id DESC LIMIT ${len(args)}", *args)
        return page_of(rows, limit, "created_at", "notification_id")

    async def unread_counts(self, bank_id: str, user_id: str) -> dict[str, int]:
        rows = await self._pool.fetch(
            "SELECT severity, COUNT(*) AS n FROM platform.user_notifications WHERE bank_id=$1 AND user_id=$2 AND read_at IS NULL GROUP BY severity",
            bank_id, user_id)
        counts = {s: 0 for s in _SEVERITIES}
        for r in rows:
            counts[r["severity"]] = int(r["n"])
        return {"total": sum(counts.values()), **counts}

    async def pinned(self, bank_id: str, user_id: str, *, limit: int) -> list[dict]:
        """Critical notifications the user has not acknowledged: shown above every page until they are."""
        rows = await self._pool.fetch(
            f"SELECT {_COLUMNS} FROM platform.user_notifications WHERE bank_id=$1 AND user_id=$2 AND severity='P0' AND acked_at IS NULL "
            "ORDER BY created_at DESC LIMIT $3", bank_id, user_id, min(max(limit, 1), MAX_LIST))
        return [dict(r) for r in rows]

    async def mark_read(self, bank_id: str, user_id: str, notification_id: str) -> bool:
        status = await self._retrying(lambda: self._pool.execute(
            "UPDATE platform.user_notifications SET read_at=NOW() WHERE bank_id=$1 AND user_id=$2 AND notification_id=$3 AND read_at IS NULL",
            bank_id, user_id, notification_id))
        return status.endswith(" 1")

    async def mark_all_read(self, bank_id: str, user_id: str) -> int:
        status = await self._retrying(lambda: self._pool.execute(
            "UPDATE platform.user_notifications SET read_at=NOW() WHERE bank_id=$1 AND user_id=$2 AND read_at IS NULL", bank_id, user_id))
        return int(status.rsplit(" ", 1)[-1])

    async def acknowledge(self, bank_id: str, user_id: str, notification_id: str) -> Optional[dict]:
        """Mark it acknowledged (and read). Returns {incident_id} the first time, None if it is not theirs or already acknowledged."""
        row = await self._retrying(lambda: self._pool.fetchrow(
            "UPDATE platform.user_notifications SET acked_at=NOW(), read_at=COALESCE(read_at, NOW()) "
            "WHERE bank_id=$1 AND user_id=$2 AND notification_id=$3 AND acked_at IS NULL RETURNING incident_id",
            bank_id, user_id, notification_id))
        return {"incident_id": row["incident_id"]} if row else None

    async def exists(self, bank_id: str, user_id: str, notification_id: str) -> bool:
        return bool(await self._pool.fetchval(
            "SELECT 1 FROM platform.user_notifications WHERE bank_id=$1 AND user_id=$2 AND notification_id=$3", bank_id, user_id, notification_id))
