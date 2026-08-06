"""
Processing Unit Master — CRUD.

A Processing Unit (PU) is the clearing-zone level grouping for CTS inward
processing. Each PU maps to one NGCH grid zone, runs its own KEDA-scaled
Temporal task queue, and has its own Kafka inward topic.

Constraint: exactly one PU per clearing zone per bank (enforced by DB unique
index and validated here for in-memory/test path).

Routes:
  GET    /v1/processing-units                    list PUs for bank
  POST   /v1/processing-units                    create PU
  GET    /v1/processing-units/{pu_id}            get single PU
  PUT    /v1/processing-units/{pu_id}            update mutable fields
  DELETE /v1/processing-units/{pu_id}            soft-deactivate (is_active=false)
  GET    /v1/processing-units/{pu_id}/branches   list branches mapped to this PU

Access:
  bank_it_admin — full CRUD
  ops_manager   — read-only (GET routes only)
  all others    — 403
"""
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.audit.audit_event import AuditEvent, AuditEventType

log = structlog.get_logger()
tracer = trace.get_tracer(__name__)

router_v1 = APIRouter(prefix="/v1/processing-units", tags=["Processing Unit Master v1"])

_VALID_CLEARING_ZONES = {
    "MUMBAI", "DELHI", "CHENNAI", "KOLKATA", "HYDERABAD", "AHMEDABAD",
}

_READ_ROLES  = {"bank_it_admin", "ops_manager"}
_WRITE_ROLES = {"bank_it_admin"}


# ── Dependency ────────────────────────────────────────────────────────────────

from fastapi.security import HTTPBearer
_bearer = HTTPBearer(auto_error=True)


def get_current_user(request: Request) -> dict[str, Any]:
    from apps.api.dependencies import require_user_context
    ctx = require_user_context(request)
    return {
        "bank_id": ctx.bank_id,
        "user_id": ctx.user_id,
        "role": ctx.role.value if hasattr(ctx.role, "value") else str(ctx.role),
    }


def _require_read(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in _READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return user


def _require_write(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in _WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return user


# ── Pydantic models ───────────────────────────────────────────────────────────

class PUCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    pu_id: str = Field(..., min_length=1, max_length=64,
                       description="PU identifier — e.g. MUMBAI-PU-01")
    pu_name: str = Field(..., min_length=1, max_length=128)
    clearing_zone: str
    ngch_participant_code: str = Field(..., min_length=1, max_length=64)
    max_agent_swarm_size: int = Field(default=200, ge=1)

    @field_validator("clearing_zone")
    @classmethod
    def validate_zone(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in _VALID_CLEARING_ZONES:
            raise ValueError(
                f"Invalid clearing_zone '{v}'. Must be one of: {sorted(_VALID_CLEARING_ZONES)}"
            )
        return v


class PUUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    pu_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    max_agent_swarm_size: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None

    # Immutable fields — rejected if supplied
    pu_id: None = Field(default=None, exclude=True,
                        description="pu_id is immutable after creation")
    clearing_zone: None = Field(default=None, exclude=True,
                                description="clearing_zone is immutable after creation")
    ngch_participant_code: None = Field(default=None, exclude=True,
                                        description="ngch_participant_code is immutable after creation")

    @model_validator(mode="before")
    @classmethod
    def forbid_immutable(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for field in ("pu_id", "clearing_zone", "ngch_participant_code"):
            if field in data and data[field] is not None:
                raise ValueError(f"{field} is immutable and cannot be updated")
        return data


class PUResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    pu_id: str
    bank_id: str
    pu_name: str
    clearing_zone: str
    ngch_participant_code: str
    temporal_task_queue: str
    kafka_inward_topic: str
    max_agent_swarm_size: int
    is_active: bool
    created_at: str
    updated_at: Optional[str]
    created_by: str


class PUListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    processing_units: list[PUResponse]
    total: int


class BranchSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    branch_id: str
    branch_ifsc: str
    branch_name: str
    city: Optional[str]
    is_scanning_enabled: bool
    is_active: bool


class PUBranchListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    branches: list[BranchSummary]
    total: int


# ── In-memory store (test / dev path) ─────────────────────────────────────────

_PU_STORE: dict[str, dict] = {}


def _get_db_pool(request: Request):
    return getattr(getattr(request, "app", None), "state", None) and \
           getattr(request.app.state, "db_pool_cts", None)


def _computed_fields(bank_id: str, pu_id: str) -> dict:
    return {
        "temporal_task_queue": f"cts-processing-{bank_id}-{pu_id}",
        "kafka_inward_topic":  f"cts.inward.{bank_id}.{pu_id}",
    }


def _pu_to_response(p: dict) -> PUResponse:
    return PUResponse(
        pu_id=p["pu_id"],
        bank_id=p["bank_id"],
        pu_name=p["pu_name"],
        clearing_zone=p["clearing_zone"],
        ngch_participant_code=p["ngch_participant_code"],
        temporal_task_queue=p["temporal_task_queue"],
        kafka_inward_topic=p["kafka_inward_topic"],
        max_agent_swarm_size=p["max_agent_swarm_size"],
        is_active=p["is_active"],
        created_at=p["created_at"],
        updated_at=p.get("updated_at"),
        created_by=p["created_by"],
    )


# ── Audit helper ──────────────────────────────────────────────────────────────

def _write_audit(
    request: Request,
    event_type: AuditEventType,
    bank_id: str,
    payload: dict,
) -> None:
    try:
        immudb = getattr(getattr(request, "app", None), "state", None) and \
                 getattr(request.app.state, "immudb_client", None)
        if immudb:
            event = AuditEvent(event_type=event_type, bank_id=bank_id, payload=payload)
            immudb.write_event(event.to_json())
    except Exception as exc:
        log.error("pu.audit_write_failed", event_type=event_type.value, error=str(exc))


# ── Routes ────────────────────────────────────────────────────────────────────

@router_v1.get("", response_model=PUListResponse)
async def list_processing_units(
    request: Request,
    is_active: Optional[bool] = Query(default=None),
    user: dict = Depends(_require_read),
):
    with tracer.start_as_current_span("processing_units.list") as span:
        span.set_attribute("bank_id", user["bank_id"])
        bank_id = user["bank_id"]
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    conditions = ["bank_id = $1"]
                    params: list[Any] = [bank_id]
                    idx = 2
                    if is_active is not None:
                        conditions.append(f"is_active = ${idx}")
                        params.append(is_active)
                        idx += 1
                    where = " AND ".join(conditions)
                    rows = await conn.fetch(
                        f"SELECT pu_id, bank_id, pu_name, clearing_zone, ngch_participant_code, "
                        f"temporal_task_queue, kafka_inward_topic, max_agent_swarm_size, "
                        f"is_active, created_at, updated_at, created_by "
                        f"FROM cts.processing_units WHERE {where} ORDER BY pu_id",
                        *params,
                    )
                    total = len(rows)
                    pus = [_pu_to_response(dict(r)) for r in rows]
                    return PUListResponse(processing_units=pus, total=total)
            except Exception as exc:
                log.error("processing_units.list.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
        else:
            pus = [p for p in _PU_STORE.values() if p["bank_id"] == bank_id]
            if is_active is not None:
                pus = [p for p in pus if p["is_active"] == is_active]
            pus.sort(key=lambda p: p["pu_id"])
            return PUListResponse(processing_units=[_pu_to_response(p) for p in pus], total=len(pus))


@router_v1.post("", response_model=PUResponse, status_code=status.HTTP_201_CREATED)
async def create_processing_unit(
    request: Request,
    payload: PUCreateRequest,
    user: dict = Depends(_require_write),
):
    with tracer.start_as_current_span("processing_units.create") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("pu_id", payload.pu_id)

        bank_id = user["bank_id"]
        now = datetime.now(timezone.utc)
        computed = _computed_fields(bank_id, payload.pu_id)
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    # Check pu_id uniqueness
                    dup = await conn.fetchrow(
                        "SELECT pu_id FROM cts.processing_units WHERE pu_id = $1", payload.pu_id
                    )
                    if dup:
                        raise HTTPException(status_code=409,
                                            detail=f"Processing Unit {payload.pu_id} already exists")
                    # Check zone uniqueness per bank
                    zone_dup = await conn.fetchrow(
                        "SELECT pu_id FROM cts.processing_units "
                        "WHERE bank_id = $1 AND clearing_zone = $2",
                        bank_id, payload.clearing_zone,
                    )
                    if zone_dup:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                f"A Processing Unit already exists for zone {payload.clearing_zone} "
                                f"— existing PU: {zone_dup['pu_id']}"
                            ),
                        )
                    await conn.execute(
                        "INSERT INTO cts.processing_units "
                        "(pu_id, bank_id, pu_name, clearing_zone, ngch_participant_code, "
                        "temporal_task_queue, kafka_inward_topic, max_agent_swarm_size, "
                        "is_active, created_at, created_by) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                        payload.pu_id, bank_id, payload.pu_name, payload.clearing_zone,
                        payload.ngch_participant_code,
                        computed["temporal_task_queue"], computed["kafka_inward_topic"],
                        payload.max_agent_swarm_size, True, now, user["user_id"],
                    )
                    row = await conn.fetchrow(
                        "SELECT pu_id, bank_id, pu_name, clearing_zone, ngch_participant_code, "
                        "temporal_task_queue, kafka_inward_topic, max_agent_swarm_size, "
                        "is_active, created_at, updated_at, created_by "
                        "FROM cts.processing_units WHERE pu_id = $1", payload.pu_id,
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("processing_units.create.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")

            _write_audit(request, AuditEventType.PU_CREATED, bank_id, {
                "pu_id": payload.pu_id,
                "pu_name": payload.pu_name,
                "clearing_zone": payload.clearing_zone,
                "created_by": user["user_id"],
            })
            return _pu_to_response(dict(row))

        else:
            if payload.pu_id in _PU_STORE:
                raise HTTPException(status_code=409,
                                    detail=f"Processing Unit {payload.pu_id} already exists")
            zone_conflict = next(
                (p for p in _PU_STORE.values()
                 if p["bank_id"] == bank_id and p["clearing_zone"] == payload.clearing_zone),
                None,
            )
            if zone_conflict:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"A Processing Unit already exists for zone {payload.clearing_zone} "
                        f"— existing PU: {zone_conflict['pu_id']}"
                    ),
                )
            pu = {
                "pu_id": payload.pu_id,
                "bank_id": bank_id,
                "pu_name": payload.pu_name,
                "clearing_zone": payload.clearing_zone,
                "ngch_participant_code": payload.ngch_participant_code,
                **computed,
                "max_agent_swarm_size": payload.max_agent_swarm_size,
                "is_active": True,
                "created_at": now.isoformat(),
                "updated_at": None,
                "created_by": user["user_id"],
            }
            _PU_STORE[payload.pu_id] = pu
            return _pu_to_response(pu)


@router_v1.get("/{pu_id}", response_model=PUResponse)
async def get_processing_unit(
    pu_id: str,
    request: Request,
    user: dict = Depends(_require_read),
):
    with tracer.start_as_current_span("processing_units.get") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("pu_id", pu_id)

        bank_id = user["bank_id"]
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT pu_id, bank_id, pu_name, clearing_zone, ngch_participant_code, "
                        "temporal_task_queue, kafka_inward_topic, max_agent_swarm_size, "
                        "is_active, created_at, updated_at, created_by "
                        "FROM cts.processing_units WHERE pu_id = $1 AND bank_id = $2",
                        pu_id, bank_id,
                    )
            except Exception as exc:
                log.error("processing_units.get.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
            if not row:
                raise HTTPException(status_code=404, detail=f"Processing Unit {pu_id} not found")
            return _pu_to_response(dict(row))
        else:
            pu = _PU_STORE.get(pu_id)
            if not pu or pu["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail=f"Processing Unit {pu_id} not found")
            return _pu_to_response(pu)


@router_v1.put("/{pu_id}", response_model=PUResponse)
async def update_processing_unit(
    pu_id: str,
    request: Request,
    payload: PUUpdateRequest,
    user: dict = Depends(_require_write),
):
    with tracer.start_as_current_span("processing_units.update") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("pu_id", pu_id)

        bank_id = user["bank_id"]
        updates = payload.model_dump(exclude_none=True)
        now = datetime.now(timezone.utc)
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT pu_id FROM cts.processing_units "
                        "WHERE pu_id = $1 AND bank_id = $2", pu_id, bank_id,
                    )
                    if not existing:
                        raise HTTPException(status_code=404,
                                            detail=f"Processing Unit {pu_id} not found")
                    if updates:
                        set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
                        set_clauses += f", updated_at = ${len(updates)+2}"
                        params = [pu_id] + list(updates.values()) + [now]
                        await conn.execute(
                            f"UPDATE cts.processing_units SET {set_clauses} WHERE pu_id = $1",
                            *params,
                        )
                    row = await conn.fetchrow(
                        "SELECT pu_id, bank_id, pu_name, clearing_zone, ngch_participant_code, "
                        "temporal_task_queue, kafka_inward_topic, max_agent_swarm_size, "
                        "is_active, created_at, updated_at, created_by "
                        "FROM cts.processing_units WHERE pu_id = $1", pu_id,
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("processing_units.update.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")

            _write_audit(request, AuditEventType.PU_UPDATED, bank_id, {
                "pu_id": pu_id,
                "changed_fields": list(updates.keys()),
                "updated_by": user["user_id"],
            })
            return _pu_to_response(dict(row))
        else:
            pu = _PU_STORE.get(pu_id)
            if not pu or pu["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail=f"Processing Unit {pu_id} not found")
            pu.update(updates)
            pu["updated_at"] = now.isoformat()
            return _pu_to_response(pu)


@router_v1.delete("/{pu_id}", response_model=PUResponse)
async def deactivate_processing_unit(
    pu_id: str,
    request: Request,
    user: dict = Depends(_require_write),
):
    with tracer.start_as_current_span("processing_units.deactivate") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("pu_id", pu_id)

        bank_id = user["bank_id"]
        now = datetime.now(timezone.utc)
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT pu_id, pu_name FROM cts.processing_units "
                        "WHERE pu_id = $1 AND bank_id = $2", pu_id, bank_id,
                    )
                    if not existing:
                        raise HTTPException(status_code=404,
                                            detail=f"Processing Unit {pu_id} not found")
                    branch_count_row = await conn.fetchrow(
                        "SELECT COUNT(*) as cnt FROM cts.branches "
                        "WHERE pu_id = $1 AND bank_id = $2 AND is_active = true",
                        pu_id, bank_id,
                    )
                    branch_count = branch_count_row["cnt"] if branch_count_row else 0
                    await conn.execute(
                        "UPDATE cts.processing_units SET is_active = false, updated_at = $2 "
                        "WHERE pu_id = $1", pu_id, now,
                    )
                    row = await conn.fetchrow(
                        "SELECT pu_id, bank_id, pu_name, clearing_zone, ngch_participant_code, "
                        "temporal_task_queue, kafka_inward_topic, max_agent_swarm_size, "
                        "is_active, created_at, updated_at, created_by "
                        "FROM cts.processing_units WHERE pu_id = $1", pu_id,
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("processing_units.deactivate.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")

            _write_audit(request, AuditEventType.PU_DEACTIVATED, bank_id, {
                "pu_id": pu_id,
                "pu_name": existing["pu_name"],
                "deactivated_by": user["user_id"],
                "branch_count": branch_count,
            })
            return _pu_to_response(dict(row))
        else:
            pu = _PU_STORE.get(pu_id)
            if not pu or pu["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail=f"Processing Unit {pu_id} not found")
            # Count branches still mapped
            from apps.api.routers.branches import _BRANCH_STORE
            branch_count = sum(
                1 for b in _BRANCH_STORE.values()
                if b.get("pu_id") == pu_id and b["bank_id"] == bank_id and b.get("is_active", True)
            )
            pu["is_active"] = False
            pu["updated_at"] = now.isoformat()
            _write_audit(request, AuditEventType.PU_DEACTIVATED, bank_id, {
                "pu_id": pu_id,
                "pu_name": pu["pu_name"],
                "deactivated_by": user["user_id"],
                "branch_count": branch_count,
            })
            return _pu_to_response(pu)


@router_v1.get("/{pu_id}/branches", response_model=PUBranchListResponse)
async def list_branches_for_pu(
    pu_id: str,
    request: Request,
    user: dict = Depends(_require_read),
):
    with tracer.start_as_current_span("processing_units.list_branches") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("pu_id", pu_id)

        bank_id = user["bank_id"]
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    pu_exists = await conn.fetchrow(
                        "SELECT pu_id FROM cts.processing_units "
                        "WHERE pu_id = $1 AND bank_id = $2", pu_id, bank_id,
                    )
                    if not pu_exists:
                        raise HTTPException(status_code=404,
                                            detail=f"Processing Unit {pu_id} not found")
                    rows = await conn.fetch(
                        "SELECT branch_id, branch_ifsc, branch_name, city, "
                        "is_scanning_enabled, is_active "
                        "FROM cts.branches WHERE pu_id = $1 AND bank_id = $2 ORDER BY branch_name",
                        pu_id, bank_id,
                    )
                    branches = [BranchSummary(**dict(r)) for r in rows]
                    return PUBranchListResponse(branches=branches, total=len(branches))
            except HTTPException:
                raise
            except Exception as exc:
                log.error("processing_units.list_branches.db_error", error=str(exc),
                          bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
        else:
            pu = _PU_STORE.get(pu_id)
            if not pu or pu["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail=f"Processing Unit {pu_id} not found")
            from apps.api.routers.branches import _BRANCH_STORE
            branches = [
                BranchSummary(
                    branch_id=b["branch_id"],
                    branch_ifsc=b["branch_ifsc"],
                    branch_name=b["branch_name"],
                    city=b.get("city"),
                    is_scanning_enabled=b.get("is_scanning_enabled", True),
                    is_active=b.get("is_active", True),
                )
                for b in _BRANCH_STORE.values()
                if b.get("pu_id") == pu_id and b["bank_id"] == bank_id
            ]
            branches.sort(key=lambda b: b.branch_name)
            return PUBranchListResponse(branches=branches, total=len(branches))
