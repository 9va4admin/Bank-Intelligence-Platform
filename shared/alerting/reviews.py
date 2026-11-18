"""Post-incident reviews and mitigation actions (docs/design/alerting-blueprint.md, section 18).

A resolved P0 or P1 incident gets a review that falls due (the number of days is a bank setting by severity). The review is submitted with a root cause, a narrative, the detection gap
and the impact, and may be linked to a risk. Its actions have an owner and a due date, are finished with evidence, and are verified by a DIFFERENT person (or sent back).
After an action is finished the system works out, when asked, whether the same failure came back: that is a hint for a person, never a verdict, and nothing is closed or reopened by itself.
Audit events name the review or action, the actor and the kind of change; the free text is not copied into the audit trail.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.audit.audit_event import AuditEventType

log = structlog.get_logger()

ROOT_CAUSES = ("capacity", "configuration", "software_defect", "dependency", "process", "hardware", "security", "unknown")
REVIEW_SEVERITIES = ("P0", "P1")
ACTION_KINDS = ("corrective", "preventive")
Effectiveness = Literal["NA", "TOO_EARLY", "EFFECTIVE_SUGGESTED", "RECURRED"]

# the states an action may move to from its current state
_TRANSITIONS = {
    "OPEN": {"IN_PROGRESS", "DONE", "WONT_FIX"},
    "IN_PROGRESS": {"DONE", "WONT_FIX"},
    "DONE": {"VERIFIED", "IN_PROGRESS", "WONT_FIX"},
    "VERIFIED": {"IN_PROGRESS"},
    "WONT_FIX": set(),
}


class ReviewInvalid(Exception):
    """A change was refused. `code` says why (not_found, bad_category, narrative_short, unknown_risk, already_submitted, review_not_submitted, bad_action, due_in_past,
    bad_transition, evidence_required, note_required, same_person)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Review(BaseModel):
    model_config = ConfigDict(frozen=True)
    review_id: str
    incident_id: str
    severity: str
    component: str
    resolved_at: datetime
    due_at: datetime
    overdue: bool
    status: Literal["DUE", "SUBMITTED"]
    root_cause_category: Optional[str] = None
    narrative: str = ""
    contributing_factors: str = ""
    detection_gap: str = ""
    impact: str = ""
    risk_id: Optional[str] = None
    submitted_by: Optional[str] = None
    submitted_at: Optional[datetime] = None


class Action(BaseModel):
    model_config = ConfigDict(frozen=True)
    action_id: str
    review_id: str
    kind: str
    description: str
    owner: str
    due_on: date
    status: Literal["OPEN", "IN_PROGRESS", "DONE", "VERIFIED", "WONT_FIX"]
    evidence: str = ""
    note: str = ""
    done_by: Optional[str] = None
    done_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    created_by: str
    overdue: bool = False
    effectiveness: Effectiveness = "NA"


_REVIEW_COLUMNS = ("review_id, incident_id, severity, component, resolved_at, status, root_cause_category, narrative, contributing_factors, detection_gap, impact, risk_id, "
                   "submitted_by, submitted_at, dedup_key")
_ACTION_COLUMNS = "action_id, review_id, kind, description, owner, due_on, status, evidence, note, done_by, done_at, verified_by, verified_at, created_by"


class ReviewStore:
    def __init__(self, pool: Any, *, due_days: dict[str, int], effectiveness_days: int, min_narrative_chars: int, auditor: Any = None) -> None:
        self._pool, self._due_days, self._effectiveness_days, self._min_narrative, self._auditor = pool, due_days, effectiveness_days, min_narrative_chars, auditor

    async def _audit(self, bank_id: str, entity: str, actor: str, detail: dict[str, Any]) -> None:
        if self._auditor is not None:
            await self._auditor.lifecycle(AuditEventType.ALERT_REVIEW_CHANGED, bank_id=bank_id, incident_id=entity, actor=actor, detail=detail)

    # ----------------------------------------------------------------- reviews

    async def ensure_due(self, bank_id: str, incident_id: str, severity: str, component: str, dedup_key: str, *, resolved_at: Optional[datetime] = None) -> bool:
        """A review falls due for a resolved P0 or P1 incident (once per incident). True when one was created."""
        if severity not in REVIEW_SEVERITIES:
            return False
        created = await self._pool.fetchval(
            "INSERT INTO platform.alert_reviews (review_id, bank_id, incident_id, severity, component, dedup_key, resolved_at) VALUES ($1,$2,$3,$4,$5,$6,$7) "
            "ON CONFLICT (bank_id, incident_id) DO NOTHING RETURNING review_id", uuid.uuid4().hex, bank_id, incident_id, severity, component, dedup_key, resolved_at or datetime.now(timezone.utc))
        if created:
            await self._audit(bank_id, f"review:{created}", "system", {"action": "due", "severity": severity, "component": component})
        return bool(created)

    def _review(self, row: Any, now: datetime) -> Review:
        due_at = row["resolved_at"] + timedelta(days=self._due_days.get(row["severity"], 7))
        data = {k: row[k] for k in row.keys() if k != "dedup_key"}
        return Review(**data, due_at=due_at, overdue=row["status"] == "DUE" and due_at < now)

    async def list_reviews(self, bank_id: str, *, status: Optional[str] = None, now: Optional[datetime] = None, limit: int = 100) -> list[Review]:
        moment = now or datetime.now(timezone.utc)
        rows = await self._pool.fetch(f"SELECT {_REVIEW_COLUMNS} FROM platform.alert_reviews WHERE bank_id=$1 AND ($2::text IS NULL OR status=$2) ORDER BY resolved_at DESC LIMIT $3",
                                      bank_id, status, limit)
        return [self._review(r, moment) for r in rows]

    async def submit(self, bank_id: str, review_id: str, by: str, *, category: str, narrative: str, contributing: str = "", detection_gap: str = "", impact: str = "",
                     risk_id: Optional[str] = None) -> Review:
        row = await self._pool.fetchrow(f"SELECT {_REVIEW_COLUMNS} FROM platform.alert_reviews WHERE bank_id=$1 AND review_id=$2", bank_id, review_id)
        if row is None:
            raise ReviewInvalid("not_found")
        if row["status"] == "SUBMITTED":
            raise ReviewInvalid("already_submitted")
        if category not in ROOT_CAUSES:
            raise ReviewInvalid("bad_category")
        if len((narrative or "").strip()) < self._min_narrative:
            raise ReviewInvalid("narrative_short")
        if risk_id and not await self._pool.fetchval("SELECT 1 FROM platform.alert_risks WHERE bank_id=$1 AND risk_id=$2", bank_id, risk_id):
            raise ReviewInvalid("unknown_risk")
        updated = await self._pool.fetchrow(
            "UPDATE platform.alert_reviews SET status='SUBMITTED', root_cause_category=$3, narrative=$4, contributing_factors=$5, detection_gap=$6, impact=$7, risk_id=$8, "
            f"submitted_by=$9, submitted_at=NOW() WHERE bank_id=$1 AND review_id=$2 RETURNING {_REVIEW_COLUMNS}",
            bank_id, review_id, category, narrative.strip(), contributing.strip(), detection_gap.strip(), impact.strip(), risk_id or None, by)
        await self._audit(bank_id, f"review:{review_id}", by, {"action": "submitted", "category": category, "risk_linked": bool(risk_id)})
        return self._review(updated, datetime.now(timezone.utc))

    # ----------------------------------------------------------------- actions

    async def add_action(self, bank_id: str, review_id: str, by: str, kind: str, description: str, owner: str, due_on: date, *, today: Optional[date] = None) -> Action:
        review = await self._pool.fetchrow("SELECT status FROM platform.alert_reviews WHERE bank_id=$1 AND review_id=$2", bank_id, review_id)
        if review is None:
            raise ReviewInvalid("not_found")
        if review["status"] != "SUBMITTED":
            raise ReviewInvalid("review_not_submitted")
        if kind not in ACTION_KINDS or not description.strip() or not owner.strip() or len(owner.strip()) > 80:
            raise ReviewInvalid("bad_action")
        if due_on < (today or date.today()):
            raise ReviewInvalid("due_in_past")
        row = await self._pool.fetchrow(
            f"INSERT INTO platform.alert_actions (action_id, bank_id, review_id, kind, description, owner, due_on, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING {_ACTION_COLUMNS}",
            uuid.uuid4().hex, bank_id, review_id, kind, description.strip(), owner.strip(), due_on, by)
        await self._audit(bank_id, f"action:{row['action_id']}", by, {"action": "added", "kind": kind, "review_id": review_id})
        return Action(**dict(row))

    async def set_status(self, bank_id: str, action_id: str, by: str, status: str, *, evidence: str = "", note: str = "") -> Action:
        row = await self._pool.fetchrow(f"SELECT {_ACTION_COLUMNS} FROM platform.alert_actions WHERE bank_id=$1 AND action_id=$2", bank_id, action_id)
        if row is None:
            raise ReviewInvalid("not_found")
        if status not in _TRANSITIONS.get(row["status"], set()):
            raise ReviewInvalid("bad_transition")
        if status == "DONE" and not evidence.strip():
            raise ReviewInvalid("evidence_required")
        if status == "VERIFIED" and row["done_by"] == by:
            raise ReviewInvalid("same_person")
        if status in ("WONT_FIX",) or (status == "IN_PROGRESS" and row["status"] in ("DONE", "VERIFIED")):
            if not note.strip():
                raise ReviewInvalid("note_required")
        updated = await self._pool.fetchrow(
            "UPDATE platform.alert_actions SET status=$3, evidence=CASE WHEN $3='DONE' THEN $4 ELSE evidence END, note=CASE WHEN $5 <> '' THEN $5 ELSE note END, "
            "done_by=CASE WHEN $3='DONE' THEN $6 WHEN $3='IN_PROGRESS' THEN NULL ELSE done_by END, done_at=CASE WHEN $3='DONE' THEN NOW() WHEN $3='IN_PROGRESS' THEN NULL ELSE done_at END, "
            "verified_by=CASE WHEN $3='VERIFIED' THEN $6 WHEN $3 IN ('IN_PROGRESS','DONE') THEN NULL ELSE verified_by END, "
            "verified_at=CASE WHEN $3='VERIFIED' THEN NOW() WHEN $3 IN ('IN_PROGRESS','DONE') THEN NULL ELSE verified_at END, updated_at=NOW() "
            f"WHERE bank_id=$1 AND action_id=$2 RETURNING {_ACTION_COLUMNS}", bank_id, action_id, status, evidence.strip(), note.strip(), by)
        await self._audit(bank_id, f"action:{action_id}", by, {"action": "status", "from": row["status"], "to": status})
        return Action(**dict(updated))

    async def list_actions(self, bank_id: str, *, today: Optional[date] = None, now: Optional[datetime] = None, limit: int = 200) -> list[Action]:
        moment = now or datetime.now(timezone.utc)
        day = today or moment.date()
        rows = await self._pool.fetch(
            f"SELECT a.{_ACTION_COLUMNS.replace(', ', ', a.')}, r.dedup_key FROM platform.alert_actions a JOIN platform.alert_reviews r ON r.bank_id=a.bank_id AND r.review_id=a.review_id "
            "WHERE a.bank_id=$1 ORDER BY a.due_on, a.created_at LIMIT $2", bank_id, limit)
        out: list[Action] = []
        for r in rows:
            data = {k: r[k] for k in r.keys() if k != "dedup_key"}
            effectiveness: Effectiveness = "NA"
            if r["status"] in ("DONE", "VERIFIED") and r["done_at"] is not None:
                recurred = await self._pool.fetchval("SELECT 1 FROM platform.alert_incidents WHERE bank_id=$1 AND dedup_key=$2 AND opened_at > $3 LIMIT 1", bank_id, r["dedup_key"], r["done_at"])
                if recurred:
                    effectiveness = "RECURRED"
                elif moment - r["done_at"] >= timedelta(days=self._effectiveness_days):
                    effectiveness = "EFFECTIVE_SUGGESTED"
                else:
                    effectiveness = "TOO_EARLY"
            out.append(Action(**data, overdue=r["status"] in ("OPEN", "IN_PROGRESS") and r["due_on"] < day, effectiveness=effectiveness))
        return out
