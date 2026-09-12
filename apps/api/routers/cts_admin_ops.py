"""
CTS Admin Ops router — Step 1f of cts.py split.

Routes:
  GET  /v1/cts/instruments/{instrument_id}/digest
  POST /v1/cts/admin/workflows/cleanup
  GET  /v1/cts/schedules
  PATCH /v1/cts/schedules/{schedule_id}
  POST /v1/cts/schedules/{schedule_id}/pause
  POST /v1/cts/schedules/{schedule_id}/resume
  GET  /v1/cts/ifsc-registry
  GET  /v1/cts/ifsc-registry/{entry_id}
  POST /v1/cts/ifsc-registry
  PUT  /v1/cts/ifsc-registry/{entry_id}/approve
  DELETE /v1/cts/ifsc-registry/{entry_id}
  GET  /v1/cts/admin/login-log
  GET  /v1/cts/admin/ngch-routing
  GET  /v1/cts/admin/micr-prefixes
  GET  /v1/cts/rpc/zones
"""
from __future__ import annotations

from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.routers.cts_deps import (
    _MICR_PREFIX_MAX_ROWS,
    _NGCH_ROUTING_MAX_ROWS,
    get_current_bank_id,
    get_current_user_context,
)
from modules.cts.ifsc.models import IFSCCreateRequest, IFSCEntry, IFSCListResponse
from modules.cts.ifsc.repository import IFSCDuplicateError
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS Admin Ops v1"])


# ---------------------------------------------------------------------------
# Instrument Digest
# ---------------------------------------------------------------------------

class DigestStepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    step_id:     str
    outcome:     str
    reason:      Optional[str]  = None
    score:       Optional[float] = None
    duration_ms: Optional[int]  = None
    extra:       dict = {}


class InstrumentDigestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id:    str
    bank_id:          str
    pipeline:         str
    workflow_id:      str
    started_at:       float
    decided_at:       float
    final_decision:   str
    steps:            list[DigestStepResult]
    shap_values:      dict = {}
    registry_version: str


@router_v1.get(
    "/instruments/{instrument_id}/digest",
    response_model=InstrumentDigestResponse,
)
async def get_instrument_digest(
    instrument_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> InstrumentDigestResponse:
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT instrument_id, bank_id, workflow_id, decision,
                   EXTRACT(EPOCH FROM processing_started_at)::float AS started_at,
                   EXTRACT(EPOCH FROM processing_completed_at)::float AS decided_at,
                   steps_digest, registry_version
            FROM cts.agent_decisions
            WHERE instrument_id = $1 AND bank_id = $2
            LIMIT 1
            """,
            instrument_id,
            bank_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Instrument not found or not yet processed")

    digest_payload = row["steps_digest"] or {}
    steps_raw = digest_payload.get("steps", [])
    steps = [DigestStepResult(**s) for s in steps_raw]

    log.info("cts.instrument_digest", bank_id=bank_id, instrument_id=instrument_id,
             step_count=len(steps))
    return InstrumentDigestResponse(
        instrument_id=row["instrument_id"],
        bank_id=row["bank_id"],
        pipeline=digest_payload.get("pipeline", "INWARD"),
        workflow_id=row["workflow_id"],
        started_at=row["started_at"] or 0.0,
        decided_at=row["decided_at"] or 0.0,
        final_decision=row["decision"],
        steps=steps,
        shap_values={},
        registry_version=row["registry_version"] or "unknown",
    )


# ---------------------------------------------------------------------------
# Admin — stuck workflow cleanup
# ---------------------------------------------------------------------------

class WorkflowCleanupRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_age_minutes: int = 240
    dry_run: bool = False


class WorkflowCleanupResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    found: int
    terminated: int
    dry_run: bool
    degraded: bool


@router_v1.post(
    "/admin/workflows/cleanup",
    response_model=WorkflowCleanupResponse,
)
async def trigger_workflow_cleanup(
    body: WorkflowCleanupRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> WorkflowCleanupResponse:
    from datetime import datetime, timezone, timedelta as _timedelta
    try:
        from temporalio.client import Client as TemporalClient
        temporal_address = getattr(request.app.state, "temporal_address", "localhost:7233")
        client = await TemporalClient.connect(temporal_address, namespace="default")
    except Exception as exc:
        log.warning("admin.workflow_cleanup.client_error", bank_id=bank_id, error=str(exc))
        return WorkflowCleanupResponse(
            bank_id=bank_id, found=0, terminated=0,
            dry_run=body.dry_run, degraded=True,
        )

    cutoff = datetime.now(tz=timezone.utc) - _timedelta(minutes=body.max_age_minutes)
    found = 0
    terminated = 0

    try:
        query = (
            f'WorkflowType="ChequeProcessingWorkflow" AND '
            f'ExecutionStatus="Running" AND '
            f'TaskQueue="cts-processing-{bank_id}"'
        )
        async for wf in client.list_workflows(query):
            if wf.start_time and wf.start_time < cutoff:
                found += 1
                if not body.dry_run:
                    try:
                        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
                        await handle.terminate(
                            reason=f"ASTRA admin cleanup: exceeded {body.max_age_minutes}min limit"
                        )
                        terminated += 1
                        log.warning(
                            "admin.workflow_cleanup.terminated",
                            bank_id=bank_id, workflow_id=wf.id,
                        )
                    except Exception as term_exc:
                        log.warning(
                            "admin.workflow_cleanup.terminate_failed",
                            bank_id=bank_id, workflow_id=wf.id, error=str(term_exc),
                        )
    except Exception as exc:
        log.warning("admin.workflow_cleanup.list_error", bank_id=bank_id, error=str(exc))
        return WorkflowCleanupResponse(
            bank_id=bank_id, found=0, terminated=0,
            dry_run=body.dry_run, degraded=True,
        )

    log.info(
        "admin.workflow_cleanup.complete",
        bank_id=bank_id, found=found, terminated=terminated, dry_run=body.dry_run,
    )
    return WorkflowCleanupResponse(
        bank_id=bank_id, found=found, terminated=terminated,
        dry_run=body.dry_run, degraded=False,
    )


# ---------------------------------------------------------------------------
# Temporal Schedules
# ---------------------------------------------------------------------------

class ScheduleInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    schedule_id: str
    label: str
    workflow: str
    module: str
    cron: str
    cron_human: str
    task_queue: str
    status: str
    last_run_at: Optional[float] = None
    last_run_status: Optional[str] = None
    last_run_duration_s: Optional[int] = None
    next_run_at: Optional[float] = None
    created_at: Optional[float] = None


class ScheduleListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    schedules: list[ScheduleInfo]
    bank_id: str


class ScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    cron: str


class ScheduleUpdateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    schedule_id: str
    cron: str
    status: Literal["UPDATED"]
    message: str


_CTS_SCHEDULE_REGISTRY = [
    {
        "schedule_id_tpl": "cts-vaultsync-schedule-{bank_id}",
        "label": "PPS & Stop Cheque Vault Sync",
        "workflow": "VaultSyncWorkflow",
        "module": "CTS",
        "cron": "0 7 * * *",
        "cron_human": "Daily at 07:00 AM",
        "task_queue_tpl": "cts-processing-{bank_id}",
    },
]


@router_v1.get("/schedules", response_model=ScheduleListResponse)
async def list_schedules(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleListResponse:
    temporal_client = getattr(request.app.state, "temporal_client", None)
    results: list[ScheduleInfo] = []

    for reg in _CTS_SCHEDULE_REGISTRY:
        sid = reg["schedule_id_tpl"].format(bank_id=bank_id)
        tq  = reg["task_queue_tpl"].format(bank_id=bank_id)
        status_val = "RUNNING"
        last_run_at = None
        last_run_status = None
        last_run_duration_s = None
        next_run_at = None
        created_at = None

        if temporal_client is not None:
            try:
                handle = temporal_client.get_schedule_handle(sid)
                desc = await handle.describe()
                status_val = "PAUSED" if desc.schedule.state.paused else "RUNNING"
                if desc.info.recent_actions:
                    last_action = desc.info.recent_actions[-1]
                    last_run_at = last_action.schedule_time.timestamp() if last_action.schedule_time else None
                if desc.info.next_action_times:
                    next_run_at = desc.info.next_action_times[0].timestamp()
                created_at = desc.info.created_at.timestamp() if desc.info.created_at else None
            except Exception:
                pass

        results.append(ScheduleInfo(
            schedule_id=sid,
            label=reg["label"],
            workflow=reg["workflow"],
            module=reg["module"],
            cron=reg["cron"],
            cron_human=reg["cron_human"],
            task_queue=tq,
            status=status_val,
            last_run_at=last_run_at,
            last_run_status=last_run_status,
            last_run_duration_s=last_run_duration_s,
            next_run_at=next_run_at,
            created_at=created_at,
        ))

    log.info("cts.schedules_listed", bank_id=bank_id, count=len(results))
    return ScheduleListResponse(schedules=results, bank_id=bank_id)


@router_v1.patch("/schedules/{schedule_id}", response_model=ScheduleUpdateResponse)
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdateRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleUpdateResponse:
    if bank_id not in schedule_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from temporalio.client import ScheduleUpdate, ScheduleSpec

            handle = temporal_client.get_schedule_handle(schedule_id)

            async def updater(input):  # noqa: ANN001
                input.schedule.spec = ScheduleSpec(cron_expressions=[body.cron])
                return ScheduleUpdate(schedule=input.schedule)

            await handle.update(updater)
        except Exception as exc:
            log.error("cts.schedule_update_error", schedule_id=schedule_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to update Temporal Schedule",
            ) from exc

    log.info("cts.schedule_updated", bank_id=bank_id, schedule_id=schedule_id, cron=body.cron)
    return ScheduleUpdateResponse(
        schedule_id=schedule_id,
        cron=body.cron,
        status="UPDATED",
        message=f"Schedule {schedule_id} updated to cron: {body.cron}",
    )


@router_v1.post("/schedules/{schedule_id}/pause", response_model=ScheduleUpdateResponse)
async def pause_schedule(
    schedule_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleUpdateResponse:
    if bank_id not in schedule_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            handle = temporal_client.get_schedule_handle(schedule_id)
            await handle.pause(note="Paused via ASTRA Admin UI")
        except Exception as exc:
            log.error("cts.schedule_pause_error", schedule_id=schedule_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to pause Temporal Schedule",
            ) from exc

    log.info("cts.schedule_paused", bank_id=bank_id, schedule_id=schedule_id)
    return ScheduleUpdateResponse(
        schedule_id=schedule_id,
        cron="",
        status="UPDATED",
        message=f"Schedule {schedule_id} paused.",
    )


@router_v1.post("/schedules/{schedule_id}/resume", response_model=ScheduleUpdateResponse)
async def resume_schedule(
    schedule_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleUpdateResponse:
    if bank_id not in schedule_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            handle = temporal_client.get_schedule_handle(schedule_id)
            await handle.unpause(note="Resumed via ASTRA Admin UI")
        except Exception as exc:
            log.error("cts.schedule_resume_error", schedule_id=schedule_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to resume Temporal Schedule",
            ) from exc

    log.info("cts.schedule_resumed", bank_id=bank_id, schedule_id=schedule_id)
    return ScheduleUpdateResponse(
        schedule_id=schedule_id,
        cron="",
        status="UPDATED",
        message=f"Schedule {schedule_id} resumed.",
    )


# ---------------------------------------------------------------------------
# IFSC Registry — CRUD
# ---------------------------------------------------------------------------

def _get_ifsc_repo(request: Request):
    repo = getattr(request.app.state, "ifsc_repo", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IFSC registry unavailable",
        )
    return repo


@router_v1.get("/ifsc-registry", response_model=IFSCListResponse)
async def list_ifsc_registry(
    request: Request,
    bank_type: Optional[str] = None,
    smb_id: Optional[str] = None,
    active_only: bool = True,
    limit: int = 50,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCListResponse:
    repo = _get_ifsc_repo(request)
    entries = await repo.list_ifsc(
        ctx.bank_id,
        bank_type=bank_type,
        smb_id=smb_id,
        active_only=active_only,
        limit=min(limit, 100),
    )
    return IFSCListResponse(items=entries, total=len(entries), bank_id=ctx.bank_id)


@router_v1.get("/ifsc-registry/{entry_id}", response_model=IFSCEntry)
async def get_ifsc_by_id(
    entry_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    repo = _get_ifsc_repo(request)
    entry = await repo.get_ifsc_by_id(entry_id)
    if entry is None or entry.bank_id != ctx.bank_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IFSC entry not found")
    return entry


@router_v1.post("/ifsc-registry", response_model=IFSCEntry, status_code=status.HTTP_201_CREATED)
async def create_ifsc(
    body: IFSCCreateRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    if ctx.role.value not in ("ops_manager", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops_manager role required")
    repo = _get_ifsc_repo(request)
    try:
        entry = await repo.create_ifsc(ctx.bank_id, body, created_by=ctx.user_id)
    except IFSCDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    log.info("ifsc_registry.created", ifsc_code=body.ifsc_code, bank_id=ctx.bank_id, created_by=ctx.user_id)
    return entry


@router_v1.put("/ifsc-registry/{entry_id}/approve", response_model=IFSCEntry)
async def approve_ifsc(
    entry_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    if ctx.role.value != "bank_it_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bank_it_admin role required")
    repo = _get_ifsc_repo(request)
    entry = await repo.approve_ifsc(entry_id, approved_by=ctx.user_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IFSC entry not found")
    log.info("ifsc_registry.approved", entry_id=entry_id, bank_id=ctx.bank_id, approved_by=ctx.user_id)
    return entry


@router_v1.delete("/ifsc-registry/{entry_id}", response_model=IFSCEntry)
async def deactivate_ifsc(
    entry_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    if ctx.role.value != "bank_it_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bank_it_admin role required")
    repo = _get_ifsc_repo(request)
    entry = await repo.deactivate_ifsc(entry_id, updated_by=ctx.user_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IFSC entry not found")
    log.info("ifsc_registry.deactivated", entry_id=entry_id, bank_id=ctx.bank_id, updated_by=ctx.user_id)
    return entry


# ---------------------------------------------------------------------------
# Admin — login log
# ---------------------------------------------------------------------------

class AuthLogItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    event_type: str
    user_id: str
    username: str
    role: str
    ip_address: str
    user_agent: Optional[str] = None
    success: bool
    failure_reason: Optional[str] = None
    mfa_used: bool
    occurred_at: str


class AuthLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[AuthLogItem]
    total: int


_AUTH_LOG_ROLES = ("ops_manager", "bank_it_admin", "compliance_officer")


@router_v1.get("/admin/login-log", response_model=AuthLogResponse)
async def get_auth_login_log(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    days: int = Query(1, ge=1, le=30),
    limit: int = Query(200, ge=1, le=500),
) -> AuthLogResponse:
    if ctx.role.value not in _AUTH_LOG_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return AuthLogResponse(bank_id=bank_id, items=[], total=0)

    try:
        rows = await db.fetch(
            """
            SELECT
                event_id,
                event_type,
                user_id,
                username,
                role,
                ip_address,
                user_agent,
                success,
                failure_reason,
                mfa_used,
                occurred_at::text
            FROM cts.auth_events
            WHERE bank_id = $1
              AND occurred_at >= NOW() - ($2 || ' days')::interval
            ORDER BY occurred_at DESC
            LIMIT $3
            """,
            bank_id,
            str(days),
            limit,
        )
    except Exception as exc:
        log.warning("cts.auth_login_log.query_failed", bank_id=bank_id, error=str(exc))
        return AuthLogResponse(bank_id=bank_id, items=[], total=0)

    items = [
        AuthLogItem(
            event_id=r["event_id"],
            event_type=r["event_type"],
            user_id=r["user_id"],
            username=r["username"],
            role=r["role"] or "",
            ip_address=r["ip_address"] or "—",
            user_agent=r["user_agent"],
            success=bool(r["success"]),
            failure_reason=r["failure_reason"],
            mfa_used=bool(r["mfa_used"]),
            occurred_at=r["occurred_at"] or "",
        )
        for r in rows
    ]
    return AuthLogResponse(bank_id=bank_id, items=items, total=len(items))


# ---------------------------------------------------------------------------
# Admin — NGCH routing rules
# ---------------------------------------------------------------------------

class NGCHRoutingRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str
    micr_prefix: str
    clearing_zone: str
    destination: str
    priority: int
    active: bool
    updated_at: str


class NGCHRoutingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    rules: list[NGCHRoutingRule]
    total: int


@router_v1.get("/admin/ngch-routing", response_model=NGCHRoutingResponse)
async def get_ngch_routing(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> NGCHRoutingResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return NGCHRoutingResponse(bank_id=bank_id, rules=[], total=0)

    try:
        rows = await db.fetch(
            f"""
            SELECT rule_id, micr_prefix, clearing_zone, destination,
                   priority, active, updated_at::text
            FROM cts.ngch_routing_rules
            WHERE bank_id = $1
            ORDER BY priority, micr_prefix
            LIMIT {_NGCH_ROUTING_MAX_ROWS}
            """,
            bank_id,
        )
    except Exception as exc:
        log.warning("cts.ngch_routing.query_failed", bank_id=bank_id, error=str(exc))
        return NGCHRoutingResponse(bank_id=bank_id, rules=[], total=0)

    rules = [
        NGCHRoutingRule(
            rule_id=r["rule_id"],
            micr_prefix=r["micr_prefix"],
            clearing_zone=r["clearing_zone"],
            destination=r["destination"],
            priority=r["priority"],
            active=bool(r["active"]),
            updated_at=r["updated_at"] or "",
        )
        for r in rows
    ]
    return NGCHRoutingResponse(bank_id=bank_id, rules=rules, total=len(rules))


# ---------------------------------------------------------------------------
# Admin — MICR prefix routing table
# ---------------------------------------------------------------------------

class MICRPrefixItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    prefix_id: str
    micr_prefix: str
    bank_name: str
    bank_ifsc: str
    clearing_zone: str
    active: bool
    updated_at: str


class MICRPrefixesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[MICRPrefixItem]
    total: int


@router_v1.get("/admin/micr-prefixes", response_model=MICRPrefixesResponse)
async def get_micr_prefixes(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    search: Optional[str] = Query(None),
) -> MICRPrefixesResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return MICRPrefixesResponse(bank_id=bank_id, items=[], total=0)

    try:
        search_clause = "AND (micr_prefix LIKE $2 OR bank_name ILIKE $2)" if search else ""
        params: list = [bank_id]
        if search:
            params.append(f"%{search}%")
        rows = await db.fetch(
            f"""
            SELECT prefix_id, micr_prefix, bank_name, bank_ifsc,
                   clearing_zone, active, updated_at::text
            FROM cts.micr_prefix_routing
            WHERE bank_id = $1
              {search_clause}
            ORDER BY micr_prefix
            LIMIT {_MICR_PREFIX_MAX_ROWS}
            """,
            *params,
        )
    except Exception as exc:
        log.warning("cts.micr_prefixes.query_failed", bank_id=bank_id, error=str(exc))
        return MICRPrefixesResponse(bank_id=bank_id, items=[], total=0)

    items = [
        MICRPrefixItem(
            prefix_id=r["prefix_id"],
            micr_prefix=r["micr_prefix"],
            bank_name=r["bank_name"],
            bank_ifsc=r["bank_ifsc"] or "",
            clearing_zone=r["clearing_zone"] or "",
            active=bool(r["active"]),
            updated_at=r["updated_at"] or "",
        )
        for r in rows
    ]
    return MICRPrefixesResponse(bank_id=bank_id, items=items, total=len(items))


# ---------------------------------------------------------------------------
# RPC Zones
# ---------------------------------------------------------------------------

class RPCZoneItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    zone_id: str
    zone_name: str
    ngch_node: str
    instrument_count_today: int
    settled_count: int
    pending_count: int
    status: str
    last_sync_at: Optional[str] = None


class RPCZonesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    zones: list[RPCZoneItem]
    total: int


@router_v1.get("/rpc/zones", response_model=RPCZonesResponse)
async def get_rpc_zones(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> RPCZonesResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return RPCZonesResponse(bank_id=bank_id, zones=[], total=0)

    try:
        rows = await db.fetch(
            """
            SELECT
                z.zone_id,
                z.zone_name,
                z.ngch_node,
                z.status,
                z.last_sync_at::text,
                COUNT(l.lot_id)::int                                             AS instrument_count_today,
                COUNT(l.lot_id) FILTER (WHERE l.status = 'SETTLED')::int        AS settled_count,
                COUNT(l.lot_id) FILTER (WHERE l.status NOT IN ('SETTLED','PARTIAL_FAIL'))::int AS pending_count
            FROM cts.rpc_zones z
            LEFT JOIN cts.lots l
                   ON l.zone_id = z.zone_id
                  AND l.bank_id = $1
                  AND l.created_at::date = CURRENT_DATE
            WHERE z.bank_id = $1
            GROUP BY z.zone_id, z.zone_name, z.ngch_node, z.status, z.last_sync_at
            ORDER BY z.zone_name
            """,
            bank_id,
        )
    except Exception as exc:
        log.warning("cts.rpc_zones.query_failed", bank_id=bank_id, error=str(exc))
        return RPCZonesResponse(bank_id=bank_id, zones=[], total=0)

    zones = [
        RPCZoneItem(
            zone_id=r["zone_id"],
            zone_name=r["zone_name"],
            ngch_node=r["ngch_node"] or "",
            instrument_count_today=r["instrument_count_today"],
            settled_count=r["settled_count"],
            pending_count=r["pending_count"],
            status=r["status"] or "ACTIVE",
            last_sync_at=r["last_sync_at"],
        )
        for r in rows
    ]
    return RPCZonesResponse(bank_id=bank_id, zones=zones, total=len(zones))
