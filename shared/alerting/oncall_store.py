"""Stored on-call rotas and overrides (platform.alert_oncall_rotas / alert_oncall_overrides), audited with the person who made each change."""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from shared.alerting.incidents import MAX_LIST, _is_conflict
from shared.alerting.oncall import OnCall, Rota, find_gaps, validate_rota, who_is_on_call
from shared.alerting.routing_policy import Calendar
from shared.audit.audit_event import AuditEventType


class RotaInvalid(Exception):
    def __init__(self, codes: list[str]) -> None:
        super().__init__(", ".join(codes))
        self.codes = codes


class OverrideInvalid(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OnCallStore:
    def __init__(self, pool: Any, *, auditor: Any = None, max_attempts: int = 6, retry_backoff_seconds: float = 0.03) -> None:
        self._pool, self._auditor = pool, auditor
        self._max_attempts, self._backoff = max(1, max_attempts), retry_backoff_seconds

    async def _retrying(self, fn):
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001
                if not _is_conflict(exc) or attempt == self._max_attempts:
                    raise
                await asyncio.sleep(self._backoff * attempt * (0.5 + random.random()))

    async def _audit(self, bank_id: str, rota: str, actor: str, detail: dict) -> None:
        if self._auditor is not None:
            await self._auditor.lifecycle(AuditEventType.ALERT_ONCALL_CHANGED, bank_id=bank_id, incident_id=f"oncall:{rota}", actor=actor, detail=detail)

    # ------------------------------------------------------------- rotas

    async def save_rota(self, bank_id: str, name: str, rota: Rota, *, actor: str) -> int:
        codes = validate_rota(rota)
        if codes:
            raise RotaInvalid(codes)
        version = await self._retrying(lambda: self._pool.fetchval(
            "INSERT INTO platform.alert_oncall_rotas (bank_id, name, rota, version, updated_by) VALUES ($1,$2,$3::jsonb,1,$4) "
            "ON CONFLICT (bank_id, name) DO UPDATE SET rota=EXCLUDED.rota, version=platform.alert_oncall_rotas.version+1, updated_by=EXCLUDED.updated_by, updated_at=NOW() "
            "RETURNING version", bank_id, name, rota.model_dump_json(), actor))
        await self._audit(bank_id, name, actor, {"action": "ROTA_SAVED", "version": version, "shifts": len(rota.shifts)})
        return int(version)

    async def get_rota(self, bank_id: str, name: str) -> Optional[Rota]:
        row = await self._pool.fetchrow("SELECT rota FROM platform.alert_oncall_rotas WHERE bank_id=$1 AND name=$2", bank_id, name)
        return Rota.model_validate_json(row["rota"]) if row else None

    async def list_rotas(self, bank_id: str, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch("SELECT name, version, updated_by, updated_at FROM platform.alert_oncall_rotas WHERE bank_id=$1 ORDER BY name LIMIT $2",
                                      bank_id, min(max(limit, 1), MAX_LIST))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- overrides

    async def add_override(self, bank_id: str, rota_name: str, user_id: str, starts_at: datetime, ends_at: datetime, *, reason: str, actor: str) -> str:
        if ends_at <= starts_at:
            raise OverrideInvalid("ends_before_start")
        if await self.get_rota(bank_id, rota_name) is None:
            raise OverrideInvalid("unknown_rota")
        override_id = uuid.uuid4().hex
        await self._retrying(lambda: self._pool.execute(
            "INSERT INTO platform.alert_oncall_overrides (override_id, bank_id, rota_name, user_id, starts_at, ends_at, reason, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            override_id, bank_id, rota_name, user_id, starts_at, ends_at, reason, actor))
        await self._audit(bank_id, rota_name, actor, {"action": "OVERRIDE_ADDED", "override_id": override_id, "user_id": user_id})
        return override_id

    async def remove_override(self, bank_id: str, override_id: str, *, actor: str) -> bool:
        row = await self._retrying(lambda: self._pool.fetchrow(
            "DELETE FROM platform.alert_oncall_overrides WHERE bank_id=$1 AND override_id=$2 RETURNING rota_name, user_id", bank_id, override_id))
        if row is None:
            return False
        await self._audit(bank_id, row["rota_name"], actor, {"action": "OVERRIDE_REMOVED", "override_id": override_id, "user_id": row["user_id"]})
        return True

    async def overrides(self, bank_id: str, rota_name: str, *, since: datetime, days: int) -> list[dict]:
        """Overrides that end after `since` and start within `days` days of it."""
        rows = await self._pool.fetch(
            "SELECT override_id, user_id, starts_at, ends_at, reason, created_by FROM platform.alert_oncall_overrides "
            "WHERE bank_id=$1 AND rota_name=$2 AND ends_at > $3 AND starts_at < $4 ORDER BY starts_at LIMIT $5",
            bank_id, rota_name, since, since + timedelta(days=days), MAX_LIST)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- who is on call

    async def current(self, bank_id: str, rota_name: str, now: datetime, calendar: Calendar) -> OnCall:
        rota = await self.get_rota(bank_id, rota_name)
        if rota is None:
            return OnCall()
        return who_is_on_call(rota, await self.overrides(bank_id, rota_name, since=now, days=1), now, calendar)

    async def current_many(self, bank_id: str, names: list[str], now: datetime, calendar: Calendar) -> dict[str, OnCall]:
        return {name: await self.current(bank_id, name, now, calendar) for name in names}

    async def gaps(self, bank_id: str, rota_name: str, calendar: Calendar, *, start: datetime, days: int, step_minutes: int):
        """Stretches when nobody is on call. A rota that does not exist is one gap for the whole window."""
        rota = await self.get_rota(bank_id, rota_name)
        if rota is None:
            return [(start, start + timedelta(days=days))]
        return find_gaps(rota, await self.overrides(bank_id, rota_name, since=start, days=days), calendar, start=start, days=days, step_minutes=step_minutes)
