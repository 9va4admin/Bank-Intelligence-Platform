"""
CTS custody of original instruments — 8 routes.

An accepted outward original stays at its branch for a while, is handed over in a batch (with a courier reference) to
central storage, is received there by a different person, is kept to the end of the retention period, and is then disposed
of. Anything missing at receipt is flagged, never forgotten. Hold days and retention years are bank configuration.

Routes:
  GET  /v1/cts/custody/pending                      originals still at a branch (late ones flagged)
  POST /v1/cts/custody/handovers                    a branch sends a batch
  GET  /v1/cts/custody/handovers                    batches (filter by status)
  POST /v1/cts/custody/handovers/{id}/receive       central storage receives a batch
  GET  /v1/cts/custody/due-for-disposal             stored originals whose retention has ended
  GET  /v1/cts/custody/missing                      originals not in the box at receipt
  POST /v1/cts/custody/instruments/{id}/dispose     dispose of one (manager, only after retention)
  GET  /v1/cts/custody/instruments/{id}/history     every step of one original
"""
from __future__ import annotations

import uuid
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.schemas.types import OptIsoTimestamp
from shared.audit.audit_event import AuditEvent, AuditEventType
from shared.auth.rbac import UserContext

from .cts_deps import get_current_user_context

log = structlog.get_logger()
router_v1 = APIRouter(prefix="/v1/cts/custody", tags=["CTS Custody v1"])

_MANAGERS = {"ops_manager", "bank_it_admin"}
_STORAGE = {"ops_reviewer", "ops_manager", "bank_it_admin"}

# ── SQL (module constants: the tests and the router share them) ───────────────────────────────────────────────────────────────
SQL_PENDING = (
    "SELECT e.instrument_id, e.micr_suffix AS cheque_number, e.branch_id, "
    "(SELECT b.branch_name FROM cts.branches b WHERE b.bank_id = e.bank_id AND b.branch_id = e.branch_id LIMIT 1) AS branch_name, "
    "e.amount_range, e.payee_display, "
    "e.scanned_at::text AS captured_at, EXTRACT(EPOCH FROM (now() - e.scanned_at)) / 86400.0 AS age_days "
    "FROM cts.outward_scan_events e WHERE e.bank_id = $1 AND e.outcome = 'ACCEPTED' AND e.instrument_id IS NOT NULL "
    "AND ($2::text IS NULL OR e.branch_id = $2) "
    "AND NOT EXISTS (SELECT 1 FROM cts.instrument_custody c WHERE c.bank_id = e.bank_id AND c.instrument_id = e.instrument_id) "
    "ORDER BY e.scanned_at LIMIT 500")
SQL_ELIGIBLE = (
    "SELECT e.instrument_id FROM cts.outward_scan_events e WHERE e.bank_id = $1 AND e.branch_id = $2 "
    "AND e.outcome = 'ACCEPTED' AND e.instrument_id = ANY($3::text[]) "
    "AND NOT EXISTS (SELECT 1 FROM cts.instrument_custody c WHERE c.bank_id = e.bank_id AND c.instrument_id = e.instrument_id)")
SQL_INSERT_HANDOVER = (
    "INSERT INTO cts.custody_handovers (bank_id, handover_id, branch_id, courier_ref, notes, item_count, created_by) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7)")
SQL_INSERT_CUSTODY = (
    "INSERT INTO cts.instrument_custody (bank_id, instrument_id, branch_id, status, handover_id) "
    "VALUES ($1, $2, $3, 'IN_TRANSIT', $4) ON CONFLICT DO NOTHING")
SQL_HANDOVERS = (
    "SELECT handover_id, branch_id, "
    "(SELECT b.branch_name FROM cts.branches b WHERE b.bank_id = custody_handovers.bank_id AND b.branch_id = custody_handovers.branch_id LIMIT 1) AS branch_name, "
    "status, courier_ref, notes, item_count, created_by, created_at::text AS created_at, "
    "received_by, received_at::text AS received_at FROM cts.custody_handovers "
    "WHERE bank_id = $1 AND ($2::text IS NULL OR status = $2) ORDER BY created_at DESC LIMIT 200")
SQL_HANDOVER_ONE = (
    "SELECT handover_id, branch_id, status, created_by FROM cts.custody_handovers WHERE bank_id = $1 AND handover_id = $2")
SQL_HANDOVER_ITEMS = "SELECT instrument_id FROM cts.instrument_custody WHERE bank_id = $1 AND handover_id = $2"
SQL_RECEIVE_HANDOVER = (
    "UPDATE cts.custody_handovers SET status = $3, received_by = $4, received_at = now(), notes = COALESCE($5, notes) "
    "WHERE bank_id = $1 AND handover_id = $2 AND status = 'IN_TRANSIT'")
SQL_RECEIVE_ITEM = (
    "UPDATE cts.instrument_custody SET status = 'STORED', received_by = $3, received_at = now(), location = $4, "
    "retention_until = current_date + make_interval(years => $5), updated_at = now() "
    "WHERE bank_id = $1 AND instrument_id = $2 AND status = 'IN_TRANSIT'")
SQL_MISSING_ITEM = (
    "UPDATE cts.instrument_custody SET status = 'MISSING', updated_at = now() "
    "WHERE bank_id = $1 AND instrument_id = $2 AND status = 'IN_TRANSIT'")
SQL_DUE = (
    "SELECT instrument_id, branch_id, "
    "(SELECT b.branch_name FROM cts.branches b WHERE b.bank_id = instrument_custody.bank_id AND b.branch_id = instrument_custody.branch_id LIMIT 1) AS branch_name, "
    "location, retention_until::text AS retention_until FROM cts.instrument_custody "
    "WHERE bank_id = $1 AND status = 'STORED' AND retention_until <= current_date ORDER BY retention_until LIMIT 500")
SQL_MISSING_LIST = (
    "SELECT instrument_id, branch_id, "
    "(SELECT b.branch_name FROM cts.branches b WHERE b.bank_id = instrument_custody.bank_id AND b.branch_id = instrument_custody.branch_id LIMIT 1) AS branch_name, "
    "handover_id, updated_at::text AS flagged_at FROM cts.instrument_custody WHERE bank_id = $1 AND status = 'MISSING' "
    "ORDER BY updated_at LIMIT 500")
SQL_CUSTODY_ONE = "SELECT instrument_id, branch_id, status FROM cts.instrument_custody WHERE bank_id = $1 AND instrument_id = $2"
SQL_DISPOSE = (
    "UPDATE cts.instrument_custody SET status = 'DISPOSED', disposed_by = $3, disposed_at = now(), updated_at = now() "
    "WHERE bank_id = $1 AND instrument_id = $2 AND status = 'STORED' AND retention_until <= current_date")
SQL_EVENT = (
    "INSERT INTO cts.custody_events (bank_id, instrument_id, handover_id, event, actor, detail) VALUES ($1, $2, $3, $4, $5, $6)")
SQL_HISTORY = (
    "SELECT event, actor, detail, handover_id, at::text AS at FROM cts.custody_events "
    "WHERE bank_id = $1 AND instrument_id = $2 ORDER BY at, event_id")


# ── Models ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
class PendingItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    cheque_number: Optional[str] = None
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    amount_range: Optional[str] = None
    payee_display: Optional[str] = None
    captured_at: OptIsoTimestamp = None
    age_days: float = 0.0
    overdue: bool = False                 # held at the branch longer than custody_branch_hold_days


class PendingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: List[PendingItem]
    hold_days: int


class HandoverRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id: str = Field(min_length=1)
    instrument_ids: List[str] = Field(min_length=1, max_length=500)
    courier_ref: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=500)


class HandoverResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    handover_id: str
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    status: str
    courier_ref: Optional[str] = None
    notes: Optional[str] = None
    item_count: int = 0
    created_by: Optional[str] = None
    created_at: OptIsoTimestamp = None
    received_by: Optional[str] = None
    received_at: OptIsoTimestamp = None


class HandoverListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    handovers: List[HandoverResponse]


class ReceiveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    location: str = Field(min_length=1, max_length=100)
    received_ids: Optional[List[str]] = None      # omit = everything in the batch arrived
    notes: Optional[str] = Field(default=None, max_length=500)


class ReceiveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    handover_id: str
    status: str                                   # RECEIVED | DISCREPANCY
    received: List[str]
    missing: List[str]


class DueItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    location: Optional[str] = None
    retention_until: Optional[str] = None


class MissingItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    handover_id: Optional[str] = None
    flagged_at: OptIsoTimestamp = None


class MissingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: List[MissingItem]


class DueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: List[DueItem]


class DisposeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    reason: str = Field(min_length=1, max_length=300)


class DisposeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    status: str


class HistoryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event: str
    actor: Optional[str] = None
    detail: Optional[str] = None
    handover_id: Optional[str] = None
    at: Optional[str] = None


class HistoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    events: List[HistoryEvent]


# ── Helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _db(request: Request):
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")
    return db


async def _cfg(request: Request, bank_id: str) -> dict:
    cs = getattr(request.app.state, "config_service", None)
    if cs is None:
        return {}
    try:
        return dict(await cs.get_cts_config(bank_id))
    except Exception:  # noqa: BLE001 - config trouble must not stop custody being recorded
        return {}


def _branches(ctx: UserContext) -> list:
    return list(getattr(ctx, "branch_ids", None) or [])


def _count(tag: str) -> int:
    try:
        return int(str(tag).rsplit(" ", 1)[-1])
    except (ValueError, AttributeError):
        return 0


def _audit(request: Request, event_type: AuditEventType, bank_id: str, payload: dict) -> None:
    """Fire-and-forget audit write. Failures are logged but never raise."""
    try:
        immudb = getattr(request.app.state, "immudb_client", None)
        if immudb:
            immudb.write_event(AuditEvent(event_type=event_type, bank_id=bank_id, payload=payload).to_record())
    except Exception as exc:  # noqa: BLE001
        log.error("custody.audit_write_failed", event_type=event_type.value, error=str(exc))


# ── Routes ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@router_v1.get("/pending", response_model=PendingResponse)
async def pending(request: Request, ctx: UserContext = Depends(get_current_user_context)) -> PendingResponse:
    """Originals still at a branch. Branch staff see their own branches; managers see all; central staff have no branch."""
    role, mine = ctx.role.value, _branches(ctx)
    if role not in _MANAGERS and not mine:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Branch staff or a manager only")
    hold = int((await _cfg(request, ctx.bank_id)).get("custody_branch_hold_days", 7))
    rows = []
    async with _db(request).acquire() as conn:
        if role in _MANAGERS:
            rows = list(await conn.fetch(SQL_PENDING, ctx.bank_id, None))
        else:
            for b in mine:
                rows += list(await conn.fetch(SQL_PENDING, ctx.bank_id, b))
    items = [PendingItem(**{**dict(r), "age_days": round(float(r["age_days"] or 0.0), 2),
                            "overdue": float(r["age_days"] or 0.0) > hold}) for r in rows]
    return PendingResponse(items=items, hold_days=hold)


@router_v1.post("/handovers", response_model=HandoverResponse, status_code=status.HTTP_201_CREATED)
async def create_handover(body: HandoverRequest, request: Request,
                          ctx: UserContext = Depends(get_current_user_context)) -> HandoverResponse:
    role = ctx.role.value
    if role not in _MANAGERS and body.branch_id not in _branches(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only hand over from your own branch")
    ids = list(dict.fromkeys(body.instrument_ids))
    handover_id = "HO-" + uuid.uuid4().hex[:10].upper()
    async with _db(request).acquire() as conn:
        ok = {r["instrument_id"] for r in await conn.fetch(SQL_ELIGIBLE, ctx.bank_id, body.branch_id, ids)}
        if ok != set(ids):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Some instruments are not accepted originals of this branch still held there")
        async with conn.transaction():
            await conn.execute(SQL_INSERT_HANDOVER, ctx.bank_id, handover_id, body.branch_id, body.courier_ref, body.notes,
                               len(ids), ctx.user_id)
            for iid in ids:
                if _count(await conn.execute(SQL_INSERT_CUSTODY, ctx.bank_id, iid, body.branch_id, handover_id)) != 1:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An instrument was handed over meanwhile")
                await conn.execute(SQL_EVENT, ctx.bank_id, iid, handover_id, "HANDED_OVER", ctx.user_id, body.courier_ref)
    _audit(request, AuditEventType.CUSTODY_HANDED_OVER, ctx.bank_id,
           {"handover_id": handover_id, "branch_id": body.branch_id, "item_count": len(ids), "actor": ctx.user_id})
    return HandoverResponse(handover_id=handover_id, branch_id=body.branch_id, status="IN_TRANSIT", courier_ref=body.courier_ref,
                            notes=body.notes, item_count=len(ids), created_by=ctx.user_id)


@router_v1.get("/handovers", response_model=HandoverListResponse)
async def list_handovers(request: Request, status_filter: Optional[str] = Query(default=None, alias="status"),
                         ctx: UserContext = Depends(get_current_user_context)) -> HandoverListResponse:
    if ctx.role.value not in _STORAGE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    async with _db(request).acquire() as conn:
        rows = await conn.fetch(SQL_HANDOVERS, ctx.bank_id, status_filter)
    mine = _branches(ctx)
    return HandoverListResponse(handovers=[HandoverResponse(**dict(r)) for r in rows
                                           if ctx.role.value in _MANAGERS or not mine or r["branch_id"] in mine])


@router_v1.post("/handovers/{handover_id}/receive", response_model=ReceiveResponse)
async def receive_handover(handover_id: str, body: ReceiveRequest, request: Request,
                           ctx: UserContext = Depends(get_current_user_context)) -> ReceiveResponse:
    if ctx.role.value not in _STORAGE or _branches(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Central storage staff only")
    cfg = await _cfg(request, ctx.bank_id)
    years = int(cfg.get("custody_retention_years", 10))
    async with _db(request).acquire() as conn:
        h = await conn.fetchrow(SQL_HANDOVER_ONE, ctx.bank_id, handover_id)
        if not h:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handover not found")
        if h["created_by"] == ctx.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The person who sent a batch cannot receive it")
        if h["status"] != "IN_TRANSIT":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This batch has already been received")
        batch = [r["instrument_id"] for r in await conn.fetch(SQL_HANDOVER_ITEMS, ctx.bank_id, handover_id)]
        if body.received_ids is None:
            arrived = list(batch)
        else:
            unknown = set(body.received_ids) - set(batch)
            if unknown:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Some items are not in this batch")
            arrived = [i for i in batch if i in set(body.received_ids)]
        missing = [i for i in batch if i not in set(arrived)]
        result = "DISCREPANCY" if missing else "RECEIVED"
        async with conn.transaction():
            # Claim the batch first: only one receiver wins, so a double click or a race cannot receive it twice.
            if _count(await conn.execute(SQL_RECEIVE_HANDOVER, ctx.bank_id, handover_id, result, ctx.user_id, body.notes)) != 1:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This batch has already been received")
            for iid in arrived:
                await conn.execute(SQL_RECEIVE_ITEM, ctx.bank_id, iid, ctx.user_id, body.location, years)
                await conn.execute(SQL_EVENT, ctx.bank_id, iid, handover_id, "RECEIVED", ctx.user_id, body.location)
            for iid in missing:
                await conn.execute(SQL_MISSING_ITEM, ctx.bank_id, iid)
                await conn.execute(SQL_EVENT, ctx.bank_id, iid, handover_id, "MISSING", ctx.user_id, "not in the box at receipt")
    _audit(request, AuditEventType.CUSTODY_RECEIVED, ctx.bank_id,
           {"handover_id": handover_id, "status": result, "received": len(arrived), "missing": len(missing), "actor": ctx.user_id})
    return ReceiveResponse(handover_id=handover_id, status=result, received=arrived, missing=missing)


@router_v1.get("/due-for-disposal", response_model=DueResponse)
async def due_for_disposal(request: Request, ctx: UserContext = Depends(get_current_user_context)) -> DueResponse:
    if ctx.role.value not in _MANAGERS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers only")
    async with _db(request).acquire() as conn:
        rows = await conn.fetch(SQL_DUE, ctx.bank_id)
    return DueResponse(items=[DueItem(**{k: (str(v) if k == "retention_until" and v is not None else v)
                                         for k, v in dict(r).items() if k in DueItem.model_fields}) for r in rows])


@router_v1.get("/missing", response_model=MissingResponse)
async def missing(request: Request, ctx: UserContext = Depends(get_current_user_context)) -> MissingResponse:
    """Originals that were handed over but not in the box at receipt. They stay listed until someone resolves them."""
    if ctx.role.value not in _MANAGERS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers only")
    async with _db(request).acquire() as conn:
        rows = await conn.fetch(SQL_MISSING_LIST, ctx.bank_id)
    return MissingResponse(items=[MissingItem(**{k: v for k, v in dict(r).items() if k in MissingItem.model_fields}) for r in rows])


@router_v1.post("/instruments/{instrument_id}/dispose", response_model=DisposeResponse)
async def dispose(instrument_id: str, body: DisposeRequest, request: Request,
                  ctx: UserContext = Depends(get_current_user_context)) -> DisposeResponse:
    if ctx.role.value not in _MANAGERS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers only")
    async with _db(request).acquire() as conn:
        if not await conn.fetchrow(SQL_CUSTODY_ONE, ctx.bank_id, instrument_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No custody record for this instrument")
        async with conn.transaction():
            if _count(await conn.execute(SQL_DISPOSE, ctx.bank_id, instrument_id, ctx.user_id)) != 1:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="Not in storage, or its retention period has not ended")
            await conn.execute(SQL_EVENT, ctx.bank_id, instrument_id, None, "DISPOSED", ctx.user_id, body.reason)
    _audit(request, AuditEventType.CUSTODY_DISPOSED, ctx.bank_id,
           {"instrument_id": instrument_id, "reason": body.reason, "actor": ctx.user_id})
    return DisposeResponse(instrument_id=instrument_id, status="DISPOSED")


@router_v1.get("/instruments/{instrument_id}/history", response_model=HistoryResponse)
async def history(instrument_id: str, request: Request,
                  ctx: UserContext = Depends(get_current_user_context)) -> HistoryResponse:
    if ctx.role.value not in _STORAGE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    async with _db(request).acquire() as conn:
        rows = await conn.fetch(SQL_HISTORY, ctx.bank_id, instrument_id)
    return HistoryResponse(instrument_id=instrument_id, events=[HistoryEvent(**{k: v for k, v in dict(r).items()
                                                                                 if k in HistoryEvent.model_fields}) for r in rows])
