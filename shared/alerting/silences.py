"""Alert silences: a planned quiet period for one component (or all) so maintenance does not page people.

An incident is still recorded while a silence is in force; only the notifications are held back, and each held notification is written to the audit trail.
A silence has a reason, an end, a maximum length (alerting.silence_max_hours) and cannot cover critical (P0) alerts unless the bank allows it (alerting.silence_allow_p0).
The audit event names the silence and who changed it; the free-text reason is not copied into the audit trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.audit.audit_event import AuditEventType

log = structlog.get_logger()

PRIORITIES = ("P0", "P1", "P2", "P3")


class SilenceInvalid(Exception):
    """A silence was refused. `code`: p0_not_allowed | too_long | reason_too_short | ends_before_start | no_priority | unknown_priority."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Silence(BaseModel):
    model_config = ConfigDict(frozen=True)
    silence_id: str
    component: str
    priorities: list[str]
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by: str
    created_at: datetime
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[str] = None


class SilenceListing(BaseModel):
    model_config = ConfigDict(frozen=True)
    in_force: list[Silence]
    upcoming: list[Silence]
    recent: list[Silence]


_COLUMNS = "silence_id, component, priorities, starts_at, ends_at, reason, created_by, created_at, cancelled_at, cancelled_by"


class SilenceStore:
    def __init__(self, pool: Any, *, max_hours: int, allow_p0: bool, min_reason_chars: int, auditor: Any = None, recent_days: int = 7) -> None:
        self._pool, self._max_hours, self._allow_p0, self._min_reason, self._auditor, self._recent_days = pool, max_hours, allow_p0, min_reason_chars, auditor, recent_days

    async def _audit(self, bank_id: str, silence_id: str, actor: str, detail: dict[str, Any]) -> None:
        if self._auditor is not None:
            await self._auditor.lifecycle(AuditEventType.ALERT_SILENCE_CHANGED, bank_id=bank_id, incident_id=f"silence:{silence_id}", actor=actor, detail=detail)

    async def create(self, bank_id: str, component: str, priorities: list[str], starts_at: datetime, ends_at: datetime, reason: str, by: str) -> Silence:
        if not priorities:
            raise SilenceInvalid("no_priority")
        if any(p not in PRIORITIES for p in priorities):
            raise SilenceInvalid("unknown_priority")
        if "P0" in priorities and not self._allow_p0:
            raise SilenceInvalid("p0_not_allowed")
        if ends_at <= starts_at:
            raise SilenceInvalid("ends_before_start")
        if ends_at - starts_at > timedelta(hours=self._max_hours):
            raise SilenceInvalid("too_long")
        if len((reason or "").strip()) < self._min_reason:
            raise SilenceInvalid("reason_too_short")
        silence_id = uuid.uuid4().hex
        row = await self._pool.fetchrow(
            f"INSERT INTO platform.alert_silences (silence_id, bank_id, component, priorities, starts_at, ends_at, reason, created_by) VALUES ($1,$2,$3,$4::text[],$5,$6,$7,$8) RETURNING {_COLUMNS}",
            silence_id, bank_id, component.strip(), sorted(set(priorities)), starts_at, ends_at, reason.strip(), by)
        await self._audit(bank_id, silence_id, by, {"action": "created", "component": component.strip(), "priorities": sorted(set(priorities)), "ends_at": ends_at.isoformat()})
        return Silence(**dict(row))

    async def cancel(self, bank_id: str, silence_id: str, by: str, *, at: Optional[datetime] = None) -> bool:
        done = await self._pool.fetchval("UPDATE platform.alert_silences SET cancelled_at=$4, cancelled_by=$3 WHERE bank_id=$1 AND silence_id=$2 AND cancelled_at IS NULL RETURNING silence_id",
                                         bank_id, silence_id, by, at or datetime.now(timezone.utc))
        if done:
            await self._audit(bank_id, silence_id, by, {"action": "cancelled"})
        return bool(done)

    async def is_silenced(self, bank_id: str, component: str, priority: str, at: Optional[datetime] = None) -> Optional[str]:
        """The id of a silence in force for this component and priority at this moment, or None."""
        return await self._pool.fetchval(
            "SELECT silence_id FROM platform.alert_silences WHERE bank_id=$1 AND (component='' OR component=$2) AND $3 = ANY(priorities) "
            "AND starts_at <= $4 AND ends_at > $4 AND cancelled_at IS NULL ORDER BY ends_at DESC LIMIT 1", bank_id, component, priority, at or datetime.now(timezone.utc))

    async def listing(self, bank_id: str, at: Optional[datetime] = None, limit: int = 100) -> SilenceListing:
        moment = at or datetime.now(timezone.utc)
        rows = await self._pool.fetch(f"SELECT {_COLUMNS} FROM platform.alert_silences WHERE bank_id=$1 AND ends_at > $2::timestamptz - make_interval(days => $3) ORDER BY starts_at LIMIT $4",
                                      bank_id, moment, self._recent_days, limit)
        silences = [Silence(**dict(r)) for r in rows]
        in_force = [s for s in silences if s.cancelled_at is None and s.starts_at <= moment < s.ends_at]
        upcoming = [s for s in silences if s.cancelled_at is None and s.starts_at > moment]
        recent = [s for s in silences if s not in in_force and s not in upcoming]
        return SilenceListing(in_force=in_force, upcoming=upcoming, recent=recent)
