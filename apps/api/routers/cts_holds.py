"""
CTS Hold Queue · Mismatch Queue · Review Allocation router.

Routes (9):
  POST   /v1/cts/holds/{instrument_id}                 — place hold
  GET    /v1/cts/holds                                  — list active holds
  POST   /v1/cts/holds/{instrument_id}/release          — release hold
  POST   /v1/cts/holds/{instrument_id}/recommendation   — branch recommendation
  GET    /v1/cts/mismatches                             — list held mismatches
  POST   /v1/cts/mismatches/{mismatch_id}/resolve       — resolve mismatch
  POST   /v1/cts/review/{instrument_id}/claim           — reviewer claims instrument
  DELETE /v1/cts/review/{instrument_id}/claim           — reviewer releases claim
  GET    /v1/cts/allocation/status                      — admin: all active claims
"""
from __future__ import annotations

import time as _time
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.routers.cts_deps import get_current_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])


# ---------------------------------------------------------------------------
# Models — Hold Queue
# ---------------------------------------------------------------------------

class HoldItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    hold_id: str
    instrument_id: str
    bank_id: str
    held_by: str
    held_at: float
    iet_deadline: float
    hold_reason: str
    branch_notified_at: Optional[float] = None
    branch_recommendation: Optional[str] = None
    branch_note: Optional[str] = None
    amount_display: str = ""
    payee_display: str = ""
    account_display: str = ""
    queue_tier: str = "standard"


class HoldListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[HoldItem]
    total: int
    bank_id: str


class PlaceHoldRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    hold_reason: str
    iet_deadline: float
    branch_email: Optional[str] = None
    branch_phone: Optional[str] = None


class PlaceHoldResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    hold_id: str
    held_at: float
    iet_remaining_seconds: float
    branch_notified: bool


class HoldReleaseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_note: Optional[str] = None
    branch_recommendation: Optional[str] = None


class HoldReleaseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    hold_id: str
    released: bool
    hold_duration_seconds: Optional[float] = None
    iet_remaining_at_release: Optional[float] = None


class HoldRecommendationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_note: Optional[str] = None
    branch_recommendation: Optional[str] = None


class HoldRecommendationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    hold_id: str
    updated: bool


# ---------------------------------------------------------------------------
# Models — Mismatch Queue
# ---------------------------------------------------------------------------

class MismatchItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    mismatch_id: str
    instrument_id: str
    branch_id: str
    held_at: str
    status: str
    mismatch_fields: list[str]
    scanner_amount: str
    vision_amount: str
    payee_display: str
    lot_id: Optional[str] = None
    workflow_run_id: Optional[str] = None


class MismatchListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[MismatchItem]
    total: int
    bank_id: str


class MismatchResolveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Literal["GO_AHEAD", "REJECTED"]
    note: Optional[str] = None


class MismatchResolveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    mismatch_id: str
    action: str
    signal_sent: bool


# ---------------------------------------------------------------------------
# Models — Allocation / Review Claims
# ---------------------------------------------------------------------------

class ClaimResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    claimed: bool
    reviewer_id: Optional[str] = None
    held_by: Optional[str] = None
    message: str


class AllocationStatusItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    reviewer_id: str
    tier: Optional[str] = None
    claimed_at: Optional[str] = None


class AllocationStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    active_claims: list[AllocationStatusItem]
    total: int


# ---------------------------------------------------------------------------
# Amount-range display helper
# ---------------------------------------------------------------------------

_AMOUNT_RANGE_DISPLAY = {
    "STANDARD": "₹[<1L]",
    "HIGH_VALUE": "₹[1L–5L]",
    "VERY_HIGH_VALUE": "₹[>1Cr]",
}


# ---------------------------------------------------------------------------
# POST /holds/{instrument_id}
# ---------------------------------------------------------------------------

@router_v1.post(
    "/holds/{instrument_id}",
    response_model=PlaceHoldResponse,
    status_code=status.HTTP_201_CREATED,
)
async def place_hold(
    instrument_id: str,
    body: PlaceHoldRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> PlaceHoldResponse:
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    if ctx.role.value not in ("ops_reviewer", "ops_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    dispatcher = getattr(request.app.state, "notification_dispatcher", None)
    audit_writer_raw = getattr(request.app.state, "audit_stream_writer", None)

    class _AuditWriterAdapter:
        def __init__(self, writer):
            self._writer = writer

        async def write(self, event_type, bank_id, payload):
            if self._writer is None:
                return
            from shared.audit.audit_event import AuditEvent, AuditEventType
            await self._writer(AuditEvent(
                event_type=getattr(AuditEventType, event_type, AuditEventType.CTS_HOLD_PLACED),
                bank_id=bank_id,
                user_id=reviewer_id,
                payload=payload,
            ))

    class _NullSafeDispatcher:
        def __init__(self, d):
            self._d = d

        async def send(self, req):
            if self._d is not None:
                await self._d.send(req)

    class _DBAdapter:
        def __init__(self, p):
            self._pool = p

        async def execute(self, query, *args):
            if self._pool is None:
                return
            async with self._pool.acquire() as conn:
                await conn.execute(query, *args)

    branch_contact: dict = {}
    if body.branch_email:
        branch_contact["email"] = body.branch_email
    if body.branch_phone:
        branch_contact["phone"] = body.branch_phone

    from modules.cts.hold.hold_service import HoldService
    hold_svc = HoldService(
        db_pool=_DBAdapter(pool),
        dispatcher=_NullSafeDispatcher(dispatcher),
        audit_writer=_AuditWriterAdapter(audit_writer_raw),
    )

    record = await hold_svc.place_hold(
        instrument_id=instrument_id,
        bank_id=bank_id,
        reviewer_id=reviewer_id,
        hold_reason=body.hold_reason,
        iet_deadline=body.iet_deadline,
        branch_contact=branch_contact,
    )

    hold_id = instrument_id  # fallback
    if pool is not None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hold_id FROM cts.instrument_holds "
                "WHERE instrument_id = $1 AND bank_id = $2 AND released_at IS NULL "
                "ORDER BY held_at DESC LIMIT 1",
                instrument_id, bank_id,
            )
            if row:
                hold_id = row["hold_id"]

    iet_remaining = max(0.0, body.iet_deadline - _time.time())

    try:
        from temporalio.client import Client as TemporalClient
        from modules.cts.workflows.hold_escalation_workflow import (
            HoldEscalationWorkflow, HoldEscalationInput,
        )
        from shared.config.config_service import config_service
        temporal_address = await config_service.get("temporal.address")
        temporal_client = await TemporalClient.connect(temporal_address)
        escalation_input = HoldEscalationInput(
            instrument_id=instrument_id,
            bank_id=bank_id,
            reviewer_id=reviewer_id,
            iet_deadline=body.iet_deadline,
            held_at=record.held_at,
            branch_email=body.branch_email,
        )
        await temporal_client.start_workflow(
            HoldEscalationWorkflow.run,
            escalation_input,
            id=f"cts-hold-escalation-{bank_id}-{instrument_id}",
            task_queue=f"cts-processing-{bank_id}",
        )
    except Exception as _exc:
        log.warning("hold.escalation.start_failed", instrument_id=instrument_id,
                    bank_id=bank_id, error=str(_exc))

    log.info("cts.hold.placed", instrument_id=instrument_id, bank_id=bank_id, reviewer_id=reviewer_id)
    return PlaceHoldResponse(
        instrument_id=instrument_id,
        hold_id=hold_id,
        held_at=record.held_at,
        iet_remaining_seconds=iet_remaining,
        branch_notified=record.branch_notified_at is not None,
    )


# ---------------------------------------------------------------------------
# GET /holds
# ---------------------------------------------------------------------------

@router_v1.get("/holds", response_model=HoldListResponse)
async def list_holds(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HoldListResponse:
    bank_id = ctx.bank_id
    allowed_roles = ("ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager")
    if ctx.role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    items: list[HoldItem] = []

    if pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    h.hold_id, h.instrument_id, h.bank_id, h.held_by,
                    h.held_at, h.iet_deadline, h.hold_reason,
                    h.branch_notified_at, h.branch_recommendation, h.branch_note,
                    i.account_last4, i.amount_range, i.queue_tier
                FROM cts.instrument_holds h
                LEFT JOIN cts.cheque_instruments i
                    ON h.instrument_id = i.instrument_id::TEXT
                    AND i.bank_id = $1
                WHERE h.bank_id = $1
                  AND h.released_at IS NULL
                ORDER BY h.iet_deadline ASC
                """,
                bank_id,
            )
            for row in rows:
                last4 = row["account_last4"] or "????"
                amount_range = row["amount_range"] or "STANDARD"
                items.append(HoldItem(
                    hold_id=row["hold_id"],
                    instrument_id=row["instrument_id"],
                    bank_id=row["bank_id"],
                    held_by=row["held_by"],
                    held_at=row["held_at"],
                    iet_deadline=row["iet_deadline"],
                    hold_reason=row["hold_reason"],
                    branch_notified_at=row["branch_notified_at"],
                    branch_recommendation=row["branch_recommendation"],
                    branch_note=row["branch_note"],
                    account_display=f"****{last4}",
                    amount_display=_AMOUNT_RANGE_DISPLAY.get(amount_range, "₹[?]"),
                    payee_display="***",
                    queue_tier=row["queue_tier"] or "standard",
                ))

    log.info("cts.holds.listed", bank_id=bank_id, count=len(items))
    return HoldListResponse(items=items, total=len(items), bank_id=bank_id)


# ---------------------------------------------------------------------------
# POST /holds/{instrument_id}/release
# ---------------------------------------------------------------------------

@router_v1.post(
    "/holds/{instrument_id}/release",
    response_model=HoldReleaseResponse,
    status_code=status.HTTP_200_OK,
)
async def release_hold(
    instrument_id: str,
    body: HoldReleaseRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HoldReleaseResponse:
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    if ctx.role.value not in ("ops_manager", "ops_reviewer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="ops_manager or ops_reviewer role required")

    pool = getattr(request.app.state, "db_pool_cts", None)
    hold_id: Optional[str] = None

    if pool is not None:
        now = _time.time()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE cts.instrument_holds
                   SET released_at = $1,
                       released_by = $2,
                       branch_note = COALESCE($3, branch_note),
                       branch_recommendation = COALESCE($4, branch_recommendation)
                 WHERE instrument_id = $5
                   AND bank_id = $6
                   AND released_at IS NULL
                RETURNING hold_id
                """,
                now, reviewer_id,
                body.branch_note, body.branch_recommendation,
                instrument_id, bank_id,
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active hold not found for this instrument",
            )
        hold_id = row["hold_id"]

        from shared.audit.audit_event import AuditEvent, AuditEventType
        audit_writer = getattr(request.app.state, "audit_stream_writer", None)
        if audit_writer is not None:
            audit_event = AuditEvent(
                event_type=AuditEventType.CTS_HOLD_RELEASED,
                bank_id=bank_id,
                user_id=reviewer_id,
                payload={
                    "instrument_id": instrument_id,
                    "hold_id": hold_id,
                    "released_by": reviewer_id,
                    "branch_note": body.branch_note,
                    "branch_recommendation": body.branch_recommendation,
                },
            )
            await audit_writer(audit_event)

    hold_id = hold_id or instrument_id

    try:
        from temporalio.client import Client as TemporalClient
        from modules.cts.workflows.hold_escalation_workflow import HoldEscalationWorkflow
        from shared.config.config_service import config_service
        temporal_address = await config_service.get("temporal.address")
        temporal_client = await TemporalClient.connect(temporal_address)
        handle = temporal_client.get_workflow_handle(
            f"cts-hold-escalation-{bank_id}-{instrument_id}"
        )
        await handle.signal(HoldEscalationWorkflow.released)
    except Exception as _exc:
        log.warning("hold.escalation.signal_failed", instrument_id=instrument_id,
                    bank_id=bank_id, error=str(_exc))

    log.info("cts.hold.released", instrument_id=instrument_id, bank_id=bank_id, released_by=reviewer_id)
    return HoldReleaseResponse(instrument_id=instrument_id, hold_id=hold_id, released=True)


# ---------------------------------------------------------------------------
# POST /holds/{instrument_id}/recommendation
# ---------------------------------------------------------------------------

@router_v1.post(
    "/holds/{instrument_id}/recommendation",
    response_model=HoldRecommendationResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_hold_recommendation(
    instrument_id: str,
    body: HoldRecommendationRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HoldRecommendationResponse:
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "ops_reviewer", "branch_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    hold_id: Optional[str] = None

    if pool is not None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE cts.instrument_holds
                   SET branch_note = COALESCE($1, branch_note),
                       branch_recommendation = COALESCE($2, branch_recommendation)
                 WHERE instrument_id = $3
                   AND bank_id = $4
                   AND released_at IS NULL
                RETURNING hold_id
                """,
                body.branch_note, body.branch_recommendation,
                instrument_id, bank_id,
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active hold not found for this instrument",
            )
        hold_id = row["hold_id"]

        from shared.audit.audit_event import AuditEvent, AuditEventType
        audit_writer = getattr(request.app.state, "audit_stream_writer", None)
        if audit_writer is not None:
            audit_event = AuditEvent(
                event_type=AuditEventType.CTS_HOLD_PLACED,
                bank_id=bank_id,
                user_id=ctx.user_id,
                payload={
                    "instrument_id": instrument_id,
                    "hold_id": hold_id,
                    "branch_recommendation": body.branch_recommendation,
                    "action": "RECOMMENDATION_UPDATED",
                },
            )
            await audit_writer(audit_event)

    hold_id = hold_id or instrument_id
    log.info("cts.hold.recommendation_updated", instrument_id=instrument_id,
             bank_id=bank_id, recommendation=body.branch_recommendation)
    return HoldRecommendationResponse(instrument_id=instrument_id, hold_id=hold_id, updated=True)


# ---------------------------------------------------------------------------
# GET /mismatches
# ---------------------------------------------------------------------------

@router_v1.get("/mismatches", response_model=MismatchListResponse)
async def list_mismatches(
    request: Request,
    branch_id: Optional[str] = None,
    ctx: UserContext = Depends(get_current_user_context),
) -> MismatchListResponse:
    bank_id = ctx.bank_id
    allowed_roles = ("ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager")
    if ctx.role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    items: list[MismatchItem] = []

    if pool is not None:
        async with pool.acquire() as conn:
            if branch_id:
                rows = await conn.fetch(
                    """
                    SELECT mismatch_id, instrument_id, branch_id, held_at, status,
                           mismatch_fields, vision_finding, scanner_data, lot_id, workflow_run_id
                    FROM cts.mismatch_queue
                    WHERE bank_id = $1 AND branch_id = $2 AND status = 'HELD'
                    ORDER BY held_at ASC
                    """,
                    bank_id, branch_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT mismatch_id, instrument_id, branch_id, held_at, status,
                           mismatch_fields, vision_finding, scanner_data, lot_id, workflow_run_id
                    FROM cts.mismatch_queue
                    WHERE bank_id = $1 AND status = 'HELD'
                    ORDER BY held_at ASC
                    """,
                    bank_id,
                )
            for row in rows:
                vf = row["vision_finding"] or {}
                sd = row["scanner_data"] or {}
                items.append(MismatchItem(
                    mismatch_id=row["mismatch_id"],
                    instrument_id=row["instrument_id"],
                    branch_id=row["branch_id"],
                    held_at=str(row["held_at"]),
                    status=row["status"],
                    mismatch_fields=row["mismatch_fields"] or [],
                    scanner_amount=sd.get("amount_figures", "—"),
                    vision_amount=vf.get("amount_figures", "—"),
                    payee_display=sd.get("payee_masked", "***"),
                    lot_id=row["lot_id"],
                    workflow_run_id=row["workflow_run_id"],
                ))

    log.info("cts.mismatches.listed", bank_id=bank_id, count=len(items))
    return MismatchListResponse(items=items, total=len(items), bank_id=bank_id)


# ---------------------------------------------------------------------------
# POST /mismatches/{mismatch_id}/resolve
# ---------------------------------------------------------------------------

@router_v1.post(
    "/mismatches/{mismatch_id}/resolve",
    response_model=MismatchResolveResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve_mismatch(
    mismatch_id: str,
    body: MismatchResolveRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> MismatchResolveResponse:
    bank_id = ctx.bank_id
    user_id = ctx.user_id
    if ctx.role.value not in ("ops_manager", "ops_reviewer", "branch_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    signal_sent = False

    if pool is not None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT mismatch_id, branch_id, workflow_run_id
                FROM cts.mismatch_queue
                WHERE mismatch_id = $1 AND bank_id = $2 AND status = 'HELD'
                """,
                mismatch_id, bank_id,
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mismatch not found or already resolved",
            )

        branch_id_val = row["branch_id"]
        workflow_run_id = row["workflow_run_id"]

        temporal_client = getattr(request.app.state, "temporal_client", None)
        if temporal_client is not None and workflow_run_id:
            try:
                from modules.cts.workflows.mismatch_resolution_workflow import (
                    MismatchResolutionWorkflow, MismatchSignal,
                )
                workflow_id = f"cts-mismatch-{bank_id}-{branch_id_val}-{mismatch_id}"
                handle = temporal_client.get_workflow_handle(
                    workflow_id, run_id=workflow_run_id
                )
                await handle.signal(
                    MismatchResolutionWorkflow.resolve,
                    MismatchSignal(action=body.action, resolved_by=user_id),
                )
                signal_sent = True
            except Exception as exc:
                log.error("cts.mismatch.signal_failed", mismatch_id=mismatch_id, error=str(exc))

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.mismatch_queue
                   SET status = $1, resolved_at = NOW(), resolved_by = $2, resolution_note = $3
                 WHERE mismatch_id = $4 AND bank_id = $5
                """,
                body.action, user_id, body.note, mismatch_id, bank_id,
            )

        from shared.audit.audit_event import AuditEvent, AuditEventType
        audit_writer = getattr(request.app.state, "audit_stream_writer", None)
        if audit_writer is not None:
            audit_event = AuditEvent(
                event_type=AuditEventType.CTS_LOCK_ACQUIRED,
                bank_id=bank_id,
                user_id=user_id,
                payload={
                    "mismatch_id": mismatch_id,
                    "action": body.action,
                    "note": body.note,
                    "signal_sent": signal_sent,
                },
            )
            await audit_writer(audit_event)

    log.info("cts.mismatch.resolved", mismatch_id=mismatch_id,
             action=body.action, bank_id=bank_id, resolved_by=user_id)
    return MismatchResolveResponse(mismatch_id=mismatch_id, action=body.action, signal_sent=signal_sent)


# ---------------------------------------------------------------------------
# POST /review/{instrument_id}/claim
# ---------------------------------------------------------------------------

@router_v1.post(
    "/review/{instrument_id}/claim",
    response_model=ClaimResponse,
    status_code=status.HTTP_200_OK,
)
async def claim_instrument(
    instrument_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ClaimResponse:
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    if ctx.role.value not in ("ops_reviewer", "ops_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    redis = getattr(request.app.state, "redis_cts", None)

    class _NullRedis:
        async def get(self, key):
            return None

        async def set(self, key, value, ex=None):
            return True

        async def delete(self, key):
            return 0

        async def scan(self, cursor, match=None, count=None):
            return (0, [])

    from modules.cts.allocation.lock_service import LockService
    from modules.cts.allocation.allocation_service import AllocationService
    lock_svc = LockService(redis_client=redis if redis is not None else _NullRedis())
    alloc_svc = AllocationService(lock_service=lock_svc)

    cts_config: dict = {}
    config_svc = getattr(request.app.state, "config_service", None)
    if config_svc is not None:
        try:
            cts_config = await config_svc.get_cts_config(bank_id)
        except Exception:
            pass

    result = await alloc_svc.claim(instrument_id, reviewer_id, cts_config)

    from shared.audit.audit_event import AuditEvent, AuditEventType
    audit_writer = getattr(request.app.state, "audit_stream_writer", None)
    if audit_writer is not None:
        audit_event = AuditEvent(
            event_type=AuditEventType.CTS_ALLOC_CLAIMED if result.claimed else AuditEventType.CTS_LOCK_ACQUIRED,
            bank_id=bank_id,
            user_id=reviewer_id,
            payload={
                "instrument_id": instrument_id,
                "claimed": result.claimed,
                "held_by": result.held_by,
                "allocation_mode": cts_config.get("allocation_mode", "SELF"),
            },
        )
        await audit_writer(audit_event)

    if result.claimed:
        log.info("cts.alloc.claimed", instrument_id=instrument_id,
                 reviewer_id=reviewer_id, bank_id=bank_id)
        return ClaimResponse(
            instrument_id=instrument_id, claimed=True,
            reviewer_id=reviewer_id, message="Claimed successfully",
        )

    log.info("cts.alloc.claim_rejected", instrument_id=instrument_id,
             reviewer_id=reviewer_id, held_by=result.held_by)
    return ClaimResponse(
        instrument_id=instrument_id, claimed=False,
        held_by=result.held_by, message="Already claimed by another reviewer",
    )


# ---------------------------------------------------------------------------
# DELETE /review/{instrument_id}/claim
# ---------------------------------------------------------------------------

@router_v1.delete(
    "/review/{instrument_id}/claim",
    response_model=ClaimResponse,
    status_code=status.HTTP_200_OK,
)
async def unclaim_instrument(
    instrument_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ClaimResponse:
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    if ctx.role.value not in ("ops_reviewer", "ops_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    redis = getattr(request.app.state, "redis_cts", None)

    class _NullRedis:
        async def get(self, key): return None
        async def set(self, key, value, ex=None): return True
        async def delete(self, key): return 0
        async def scan(self, cursor, match=None, count=None): return (0, [])

    from modules.cts.allocation.lock_service import LockService
    from modules.cts.allocation.allocation_service import AllocationService
    lock_svc = LockService(redis_client=redis if redis is not None else _NullRedis())
    alloc_svc = AllocationService(lock_service=lock_svc)

    await alloc_svc.unclaim(instrument_id, reviewer_id, {})

    from shared.audit.audit_event import AuditEvent, AuditEventType
    audit_writer = getattr(request.app.state, "audit_stream_writer", None)
    if audit_writer is not None:
        audit_event = AuditEvent(
            event_type=AuditEventType.CTS_ALLOC_UNCLAIMED,
            bank_id=bank_id,
            user_id=reviewer_id,
            payload={"instrument_id": instrument_id, "unclaimed_by": reviewer_id},
        )
        await audit_writer(audit_event)

    log.info("cts.alloc.unclaimed", instrument_id=instrument_id,
             reviewer_id=reviewer_id, bank_id=bank_id)
    return ClaimResponse(instrument_id=instrument_id, claimed=False, message="Released successfully")


# ---------------------------------------------------------------------------
# GET /allocation/status
# ---------------------------------------------------------------------------

@router_v1.get(
    "/allocation/status",
    response_model=AllocationStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_allocation_status(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> AllocationStatusResponse:
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    redis = getattr(request.app.state, "redis_cts", None)
    claims: list[AllocationStatusItem] = []

    if redis is not None:
        from modules.cts.allocation.lock_service import LockService, LOCK_KEY_PREFIX
        pattern = f"{LOCK_KEY_PREFIX}*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                raw = await redis.get(key)
                if raw is None:
                    continue
                key_str = key.decode() if isinstance(key, bytes) else key
                instrument_id = key_str[len(LOCK_KEY_PREFIX):]
                reviewer_id_val = raw.decode() if isinstance(raw, bytes) else str(raw)
                claims.append(AllocationStatusItem(
                    instrument_id=instrument_id,
                    reviewer_id=reviewer_id_val,
                ))
            if cursor == 0:
                break

    log.info("cts.alloc.status", bank_id=bank_id, active_claims=len(claims))
    return AllocationStatusResponse(bank_id=bank_id, active_claims=claims, total=len(claims))
