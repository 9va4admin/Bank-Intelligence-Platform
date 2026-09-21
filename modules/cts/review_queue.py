"""Durable human-review queue (cts.human_review_items + cts.human_review_history).

One table for inward and outward (direction flag). A decision updates the row in place
(status=DECIDED) so reports can still join to it; the log is the append-only history table
(every state change), and each change is also audited to ImmuDB by the caller.
"""
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from shared.utils.instrument_uuid import to_instrument_uuid

DIRECTIONS = ("INWARD", "OUTWARD")
STAGES = ("PENDING", "ASSIGNED", "IN_REVIEW", "DECIDED")
OPEN_STATUSES = ("PENDING", "ASSIGNED", "IN_REVIEW")

_UPSERT = """
    INSERT INTO cts.human_review_items
        (bank_id, direction, instrument_id, instrument_ref, decision_id, workflow_id, parent_workflow_id,
         escalation_reason, context_bundle, review_deadline_at, iet_deadline_at, queue_tier, review_level, status)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,'PENDING')
    ON CONFLICT (bank_id, workflow_id) DO UPDATE SET updated_at = now()
    RETURNING review_id
"""
_HISTORY = """
    INSERT INTO cts.human_review_history (review_id, bank_id, event, actor, detail)
    VALUES ($1,$2,$3,$4,$5::jsonb)
"""
_DECIDE = """
    UPDATE cts.human_review_items
       SET status = 'DECIDED', reviewer_decision = $3, reviewer_notes = $4, reviewed_at = now(), updated_at = now()
     WHERE bank_id = $1 AND workflow_id = $2 AND status IN ('PENDING','ASSIGNED','IN_REVIEW')
 RETURNING review_id
"""


async def open_item(conn: Any, *, bank_id: str, direction: str, instrument_id: str, workflow_id: str,
                    parent_workflow_id: str, escalation_reason: str, context_bundle: dict,
                    review_deadline_at: datetime, iet_deadline_at: Optional[datetime] = None,
                    decision_id: Optional[uuid.UUID] = None, queue_tier: str = "standard",
                    review_level: int = 1) -> uuid.UUID:
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    async with conn.transaction():
        review_id = await conn.fetchval(
            _UPSERT, bank_id, direction, to_instrument_uuid(bank_id, instrument_id), instrument_id, decision_id,
            workflow_id, parent_workflow_id, escalation_reason, json.dumps(context_bundle, default=str),
            review_deadline_at, iet_deadline_at, queue_tier, review_level)
        await conn.execute(_HISTORY, review_id, bank_id, "CREATED", "system",
                           json.dumps({"direction": direction, "reason": escalation_reason,
                                       "queue_tier": queue_tier, "review_level": review_level}))
    return review_id


async def record_decision(conn: Any, *, bank_id: str, workflow_id: str, decision: str,
                          reviewer_id: str, notes: str) -> bool:
    """True if an open item was decided; False if there was none (already decided / unknown)."""
    async with conn.transaction():
        row = await conn.fetchrow(_DECIDE, bank_id, workflow_id, decision, notes)
        if row is None:
            return False
        await conn.execute(_HISTORY, row["review_id"], bank_id, "DECIDED", reviewer_id,
                           json.dumps({"decision": decision, "notes": notes}))
    return True


async def list_open(conn: Any, bank_id: str, direction: Optional[str] = None, limit: int = 50) -> list:
    """Open items only (PENDING/ASSIGNED). Explicit columns, bounded limit — never SELECT *."""
    limit = max(1, min(int(limit), 100))
    cols = ("review_id, bank_id, direction, instrument_ref, workflow_id, escalation_reason, status, "
            "queue_tier, review_level, assigned_zone, assigned_reviewer_id, review_deadline_at, iet_deadline_at, created_at")
    if direction:
        return await conn.fetch(
            f"SELECT {cols} FROM cts.human_review_items WHERE bank_id=$1 AND direction=$2 "
            f"AND status IN ('PENDING','ASSIGNED','IN_REVIEW') ORDER BY review_level DESC, created_at LIMIT $3", bank_id, direction, limit)
    return await conn.fetch(
        f"SELECT {cols} FROM cts.human_review_items WHERE bank_id=$1 "
        f"AND status IN ('PENDING','ASSIGNED','IN_REVIEW') ORDER BY review_level DESC, created_at LIMIT $2", bank_id, limit)


async def assign(conn: Any, *, bank_id: str, workflow_id: str, reviewer_id: str, zone: Optional[str] = None) -> bool:
    async with conn.transaction():
        row = await conn.fetchrow(
            "UPDATE cts.human_review_items SET status='ASSIGNED', assigned_reviewer_id=$3, assigned_zone=$4, "
            "assigned_at=now(), updated_at=now() WHERE bank_id=$1 AND workflow_id=$2 "
            "AND status IN ('PENDING','ASSIGNED') RETURNING review_id", bank_id, workflow_id, reviewer_id, zone)
        if row is None:
            return False
        await conn.execute(_HISTORY, row["review_id"], bank_id, "ASSIGNED", reviewer_id,
                           json.dumps({"zone": zone}))
    return True


async def start_review(conn: Any, *, bank_id: str, workflow_id: str, reviewer_id: str) -> bool:
    async with conn.transaction():
        row = await conn.fetchrow(
            "UPDATE cts.human_review_items SET status='IN_REVIEW', updated_at=now() "
            "WHERE bank_id=$1 AND workflow_id=$2 AND status IN ('PENDING','ASSIGNED','IN_REVIEW') "
            "RETURNING review_id", bank_id, workflow_id)
        if row is None:
            return False
        await conn.execute(_HISTORY, row["review_id"], bank_id, "IN_REVIEW", reviewer_id, "{}")
    return True


async def escalate(conn: Any, *, bank_id: str, workflow_id: str, actor: str, reason: str) -> Optional[int]:
    """Raise the review level and put the item back in PENDING for the next level. Returns the new level."""
    async with conn.transaction():
        row = await conn.fetchrow(
            "UPDATE cts.human_review_items SET review_level = review_level + 1, status='PENDING', "
            "assigned_reviewer_id=NULL, assigned_at=NULL, updated_at=now() "
            "WHERE bank_id=$1 AND workflow_id=$2 AND status IN ('PENDING','ASSIGNED','IN_REVIEW') "
            "RETURNING review_id, review_level", bank_id, workflow_id)
        if row is None:
            return None
        await conn.execute(_HISTORY, row["review_id"], bank_id, "ESCALATED", actor,
                           json.dumps({"reason": reason, "to_level": row["review_level"]}))
    return row["review_level"]


async def decide_by_instrument(conn: Any, *, bank_id: str, direction: str, instrument_ref: str, decision: str,
                               reviewer_id: str, notes: str) -> bool:
    """Decide the open item for an instrument (used by the API decide endpoints, which know the
    instrument id, not the review workflow id). True if an open item was decided."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    async with conn.transaction():
        row = await conn.fetchrow(
            "UPDATE cts.human_review_items SET status='DECIDED', reviewer_decision=$4, reviewer_notes=$5, "
            "reviewed_at=now(), updated_at=now() WHERE bank_id=$1 AND direction=$2 AND instrument_ref=$3 "
            "AND status IN ('PENDING','ASSIGNED','IN_REVIEW') RETURNING review_id",
            bank_id, direction, instrument_ref, decision, notes)
        if row is None:
            return False
        await conn.execute(_HISTORY, row["review_id"], bank_id, "DECIDED", reviewer_id,
                           json.dumps({"decision": decision, "notes": notes}))
    return True
