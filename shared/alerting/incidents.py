"""The incident store: one row per problem, however many alerts it produces (docs/design/alerting-blueprint.md, sections 3 and 17).

An incident is identified by (bank, dedup key) while it is open. Raising the same problem again updates the existing incident; a recovery resolves
it; the next failure opens a new one. All queries are bank-scoped with explicit column lists.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from shared.messages import get_message

_RECOVERY_EVENTS = ("COMPONENT_RECOVERED", "COMPONENT_SLOW_CLEARED")
_SLOW_EVENTS = ("COMPONENT_SLOW", "COMPONENT_SLOW_CLEARED")
_COMPONENT_EVENTS = ("COMPONENT_DOWN", "COMPONENT_REMINDER", "COMPONENT_RECOVERED") + _SLOW_EVENTS
MAX_LIST = 100


def _is_conflict(exc: Exception) -> bool:
    """YugabyteDB (optimistic concurrency) aborts one of two simultaneous writers to a row with a serialization error; it is safe to retry."""
    return type(exc).__name__ in ("SerializationError", "DeadlockDetectedError") or "could not serialize" in str(exc)


def dedup_key_for(event_type: str, component: str) -> str:
    """Which incident an alert belongs to. Down, its reminders and its recovery are one incident; slow is its own; other checks are keyed by
    what they are and where."""
    if event_type in _COMPONENT_EVENTS:
        return f"component:{component}:{'slow' if event_type in _SLOW_EVENTS else 'down'}"
    return f"{event_type}:{component}"


def is_resolution(event_type: str) -> bool:
    return event_type in _RECOVERY_EVENTS


class OpenResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    incident_id: str
    created: bool
    severity: str
    state: str
    severity_raised: bool = False        # the severity was made worse by this alert


class ClosedIncident(BaseModel):
    model_config = ConfigDict(frozen=True)
    incident_id: str
    severity: str
    component: str
    duration_seconds: Optional[float] = None


class IncidentStore:
    def __init__(self, pool: Any, *, max_attempts: int = 6, retry_backoff_seconds: float = 0.03) -> None:
        self._pool, self._max_attempts, self._backoff = pool, max(1, max_attempts), retry_backoff_seconds

    async def _retrying(self, fn):
        """Run a write, retrying with jittered backoff when the database aborts it because of a concurrent writer."""
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001
                if not _is_conflict(exc) or attempt == self._max_attempts:
                    raise
                await asyncio.sleep(self._backoff * attempt * (0.5 + random.random()))

    async def open_or_update(self, **kw) -> OpenResult:
        return await self._retrying(lambda: self._open_or_update(**kw))

    async def _open_or_update(self, *, bank_id: str, dedup_key: str, alert_id: str, component: str, severity: str, summary: str,
                             impact: str = "", category: str = "", scope_level: str = "BANK", pu_id: Optional[str] = None,
                             smb_id: Optional[str] = None) -> OpenResult:
        for _ in range(3):                      # a concurrent resolve can remove the row between the two statements; try again
            incident_id = uuid.uuid4().hex
            created = await self._pool.fetchval(
                "INSERT INTO platform.alert_incidents (incident_id, bank_id, dedup_key, alert_id, component, category, severity, state, "
                "scope_level, pu_id, smb_id, summary, impact) VALUES ($1,$2,$3,$4,$5,$6,$7,'OPEN',$8,$9,$10,$11,$12) "
                "ON CONFLICT DO NOTHING RETURNING incident_id",
                incident_id, bank_id, dedup_key, alert_id, component, category, severity, scope_level, pu_id, smb_id, summary, impact)
            if created:
                return OpenResult(incident_id=incident_id, created=True, severity=severity, state="OPEN")
            row = await self._pool.fetchrow(
                "SELECT incident_id, severity, state FROM platform.alert_incidents WHERE bank_id=$1 AND dedup_key=$2 AND state <> 'RESOLVED' LIMIT 1",
                bank_id, dedup_key)
            if row is None:
                continue
            raised = severity < row["severity"]                         # 'P0' < 'P1': a lower number is worse
            new_severity = severity if raised else row["severity"]
            await self._pool.execute(
                "UPDATE platform.alert_incidents SET severity=$3, summary=$4, impact=CASE WHEN $5 = '' THEN impact ELSE $5 END "
                "WHERE bank_id=$1 AND incident_id=$2", bank_id, row["incident_id"], new_severity, summary, impact)
            return OpenResult(incident_id=row["incident_id"], created=False, severity=new_severity, state=row["state"], severity_raised=raised)
        raise RuntimeError(get_message("ALERT_INCIDENT_OPEN_FAILED"))

    async def acknowledge(self, bank_id: str, incident_id: str, user: str) -> bool:
        return await self._retrying(lambda: self._acknowledge(bank_id, incident_id, user))

    async def _acknowledge(self, bank_id: str, incident_id: str, user: str) -> bool:
        status = await self._pool.execute(
            "UPDATE platform.alert_incidents SET state='ACKED', acked_at=NOW(), acked_by=$3 WHERE bank_id=$1 AND incident_id=$2 AND state='OPEN'",
            bank_id, incident_id, user)
        return status.endswith(" 1")

    async def resolve(self, bank_id: str, dedup_key: str, by: str) -> Optional[ClosedIncident]:
        return await self._retrying(lambda: self._resolve(bank_id, dedup_key, by))

    async def _resolve(self, bank_id: str, dedup_key: str, by: str) -> Optional[ClosedIncident]:
        row = await self._pool.fetchrow(
            "UPDATE platform.alert_incidents SET state='RESOLVED', resolved_at=NOW(), resolved_by=$3 "
            "WHERE bank_id=$1 AND dedup_key=$2 AND state <> 'RESOLVED' "
            "RETURNING incident_id, severity, component, EXTRACT(EPOCH FROM (resolved_at - opened_at)) AS duration_seconds",
            bank_id, dedup_key, by)
        if row is None:
            return None
        return ClosedIncident(incident_id=row["incident_id"], severity=row["severity"], component=row["component"],
                              duration_seconds=float(row["duration_seconds"]) if row["duration_seconds"] is not None else None)

    async def record_notification(self, bank_id: str, incident_id: str) -> None:
        await self._retrying(lambda: self._record_notification(bank_id, incident_id))

    async def _record_notification(self, bank_id: str, incident_id: str) -> None:
        await self._pool.execute(
            "UPDATE platform.alert_incidents SET last_notified_at=NOW(), notification_count=notification_count+1 WHERE bank_id=$1 AND incident_id=$2",
            bank_id, incident_id)

    async def list_open(self, bank_id: str, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT incident_id, dedup_key, alert_id, component, severity, state, summary, opened_at, acked_at, acked_by, notification_count "
            "FROM platform.alert_incidents WHERE bank_id=$1 AND state <> 'RESOLVED' ORDER BY severity, opened_at LIMIT $2",
            bank_id, min(max(limit, 1), MAX_LIST))
        return [dict(r) for r in rows]

    async def record_state_change(self, bank_id: str, component: str, from_status: str, to_status: str, *, latency_ms: Optional[float],
                                  error: Optional[str], incident_id: Optional[str]) -> None:
        await self._pool.execute(
            "INSERT INTO platform.component_state_history (bank_id, component, from_status, to_status, latency_ms, error, incident_id) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7)", bank_id, component, from_status, to_status, latency_ms, error, incident_id)
