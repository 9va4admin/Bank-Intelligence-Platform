"""Alert risk register: the risks to alerting itself, seeded from the shipped template, each with an owner.

The system records facts; only a person declares a risk mitigated, and a DIFFERENT person verifies it. Changing the mitigation text after it was declared reopens the risk.
The audit event names the risk, the actor and what kind of change it was; the free text is not copied into the audit trail.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.alerting.risk_template import RISK_TEMPLATE
from shared.audit.audit_event import AuditEventType
from shared.messages import get_message

log = structlog.get_logger()

OWNER_MAX = 80
MITIGATION_MAX = 2000


class RiskInvalid(Exception):
    """A change was refused. `code`: not_found | bad_rating | bad_owner | bad_review_date | needs_owner_and_mitigation | same_person | not_mitigated."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Risk(BaseModel):
    model_config = ConfigDict(frozen=True)
    risk_id: str
    template_key: str
    category: str
    title: str
    description: str
    likelihood: int
    impact: int
    owner: Optional[str] = None
    status: Literal["OPEN", "MITIGATED", "VERIFIED"]
    mitigation: str = ""
    declared_by: Optional[str] = None
    verified_by: Optional[str] = None
    next_review_on: Optional[date] = None
    updated_by: str
    updated_at: datetime

    @property
    def rating(self) -> int:
        return self.likelihood * self.impact


class RiskSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int = 0
    without_owner: int = 0
    review_overdue: int = 0
    verified: int = 0


_COLUMNS = "risk_id, template_key, category, title, description, likelihood, impact, owner, status, mitigation, declared_by, verified_by, next_review_on, updated_by, updated_at"


class RiskStore:
    def __init__(self, pool: Any, *, review_days: int, auditor: Any = None) -> None:
        self._pool, self._review_days, self._auditor = pool, review_days, auditor

    async def _audit(self, bank_id: str, risk_id: str, actor: str, detail: dict[str, Any]) -> None:
        if self._auditor is not None:
            await self._auditor.lifecycle(AuditEventType.ALERT_RISK_CHANGED, bank_id=bank_id, incident_id=f"risk:{risk_id}", actor=actor, detail=detail)

    async def seed(self, bank_id: str, by: str) -> int:
        """Add the template risks the bank does not have yet; returns how many were added."""
        added = 0
        for key, category, likelihood, impact in RISK_TEMPLATE:
            created = await self._pool.fetchval(
                "INSERT INTO platform.alert_risks (risk_id, bank_id, template_key, category, title, description, likelihood, impact, next_review_on, updated_by) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8, CURRENT_DATE + $9::int, $10) ON CONFLICT (bank_id, template_key) DO NOTHING RETURNING risk_id",
                uuid.uuid4().hex, bank_id, key, category, get_message(f"ALERT_RISK_{key}_TITLE"), get_message(f"ALERT_RISK_{key}_DESC"), likelihood, impact, self._review_days, by)
            if created:
                added += 1
                await self._audit(bank_id, created, by, {"action": "seeded", "template_key": key})
        return added

    async def list(self, bank_id: str, limit: int = 100) -> list[Risk]:
        rows = await self._pool.fetch(f"SELECT {_COLUMNS} FROM platform.alert_risks WHERE bank_id=$1 ORDER BY (likelihood * impact) DESC, template_key LIMIT $2", bank_id, limit)
        return [Risk(**dict(r)) for r in rows]

    async def _get(self, bank_id: str, risk_id: str) -> Risk:
        row = await self._pool.fetchrow(f"SELECT {_COLUMNS} FROM platform.alert_risks WHERE bank_id=$1 AND risk_id=$2", bank_id, risk_id)
        if row is None:
            raise RiskInvalid("not_found")
        return Risk(**dict(row))

    async def update(self, bank_id: str, risk_id: str, by: str, *, owner: Optional[str] = None, mitigation: Optional[str] = None, likelihood: Optional[int] = None,
                     impact: Optional[int] = None, next_review_on: Optional[date] = None) -> Risk:
        current = await self._get(bank_id, risk_id)
        if owner is not None and (not owner.strip() or len(owner.strip()) > OWNER_MAX):
            raise RiskInvalid("bad_owner")
        for value in (likelihood, impact):
            if value is not None and not 1 <= value <= 5:
                raise RiskInvalid("bad_rating")
        if next_review_on is not None and next_review_on < date.today() - timedelta(days=1):
            raise RiskInvalid("bad_review_date")
        new_mitigation = mitigation.strip()[:MITIGATION_MAX] if mitigation is not None else current.mitigation
        reopen = current.status != "OPEN" and new_mitigation != current.mitigation        # a declaration was about the old mitigation
        row = await self._pool.fetchrow(
            "UPDATE platform.alert_risks SET owner=COALESCE($3, owner), mitigation=$4, likelihood=COALESCE($5, likelihood), impact=COALESCE($6, impact), "
            "next_review_on=COALESCE($7, next_review_on), status=CASE WHEN $8 THEN 'OPEN' ELSE status END, declared_by=CASE WHEN $8 THEN NULL ELSE declared_by END, "
            f"verified_by=CASE WHEN $8 THEN NULL ELSE verified_by END, updated_by=$9, updated_at=NOW() WHERE bank_id=$1 AND risk_id=$2 RETURNING {_COLUMNS}",
            bank_id, risk_id, owner.strip() if owner is not None else None, new_mitigation, likelihood, impact, next_review_on, reopen, by)
        changed = [name for name, value in (("owner", owner), ("mitigation", mitigation), ("likelihood", likelihood), ("impact", impact), ("next_review_on", next_review_on)) if value is not None]
        await self._audit(bank_id, risk_id, by, {"action": "updated", "fields": changed, "reopened": reopen})
        return Risk(**dict(row))

    async def declare_mitigated(self, bank_id: str, risk_id: str, by: str) -> Risk:
        current = await self._get(bank_id, risk_id)
        if not current.owner or not current.mitigation.strip():
            raise RiskInvalid("needs_owner_and_mitigation")
        row = await self._pool.fetchrow(
            f"UPDATE platform.alert_risks SET status='MITIGATED', declared_by=$3, verified_by=NULL, updated_by=$3, updated_at=NOW() WHERE bank_id=$1 AND risk_id=$2 RETURNING {_COLUMNS}",
            bank_id, risk_id, by)
        await self._audit(bank_id, risk_id, by, {"action": "declared_mitigated"})
        return Risk(**dict(row))

    async def verify(self, bank_id: str, risk_id: str, by: str) -> Risk:
        current = await self._get(bank_id, risk_id)
        if current.status != "MITIGATED":
            raise RiskInvalid("not_mitigated")
        if current.declared_by == by:
            raise RiskInvalid("same_person")
        row = await self._pool.fetchrow(
            f"UPDATE platform.alert_risks SET status='VERIFIED', verified_by=$3, updated_by=$3, updated_at=NOW() WHERE bank_id=$1 AND risk_id=$2 RETURNING {_COLUMNS}", bank_id, risk_id, by)
        await self._audit(bank_id, risk_id, by, {"action": "verified"})
        return Risk(**dict(row))

    async def reopen(self, bank_id: str, risk_id: str, by: str) -> Risk:
        await self._get(bank_id, risk_id)
        row = await self._pool.fetchrow(
            f"UPDATE platform.alert_risks SET status='OPEN', declared_by=NULL, verified_by=NULL, updated_by=$3, updated_at=NOW() WHERE bank_id=$1 AND risk_id=$2 RETURNING {_COLUMNS}",
            bank_id, risk_id, by)
        await self._audit(bank_id, risk_id, by, {"action": "reopened"})
        return Risk(**dict(row))

    async def summary(self, bank_id: str) -> RiskSummary:
        row = await self._pool.fetchrow(
            "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE owner IS NULL OR owner = '') AS without_owner, COUNT(*) FILTER (WHERE next_review_on < CURRENT_DATE) AS review_overdue, "
            "COUNT(*) FILTER (WHERE status = 'VERIFIED') AS verified FROM platform.alert_risks WHERE bank_id=$1", bank_id)
        return RiskSummary(**dict(row))
