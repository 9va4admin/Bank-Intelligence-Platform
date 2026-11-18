"""
On-call API (docs/design/alerting-1b-plan.md, step 6): rotas, who is on call now, overrides (swaps and cover) and coverage gaps.

All routes under /v1/ops/oncall/. Read: ops_manager, bank_it_admin, ops_reviewer, compliance_officer. Change: ops_manager, bank_it_admin. Every change is audited with who made it.
Settings (Layer 3): alerting.oncall_gap_days, alerting.oncall_gap_step_minutes, alerting.oncall_override_days.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.alerting.oncall import OnCall, Rota
from shared.alerting.oncall_store import OnCallStore, OverrideInvalid, RotaInvalid
from shared.alerting.policy_defaults import load_calendar
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/ops/oncall", tags=["On-call v1"])

_READ_ROLES = frozenset({"ops_manager", "bank_it_admin", "ops_reviewer", "compliance_officer"})
_CHANGE_ROLES = frozenset({"ops_manager", "bank_it_admin"})
RotaName = Path(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
DEFAULT_GAP_DAYS, DEFAULT_GAP_STEP_MINUTES, DEFAULT_OVERRIDE_DAYS = 7, 30, 14


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def _require(roles: frozenset, message_key: str):
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message(message_key))
        return user
    return check


require_read = _require(_READ_ROLES, "ALERT_API_ROLE_CANNOT_READ")
require_change = _require(_CHANGE_ROLES, "ALERT_API_ROLE_CANNOT_CHANGE_ONCALL")


class SaveRotaRequest(BaseModel):
    rota: Rota


class SaveRotaResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    version: int


class OverrideRequest(BaseModel):
    user_id: str
    starts_at: datetime
    ends_at: datetime
    reason: str = ""


class OverrideCreated(BaseModel):
    model_config = ConfigDict(frozen=True)
    override_id: str


class OverrideView(BaseModel):
    model_config = ConfigDict(frozen=True)
    override_id: str
    user_id: str
    starts_at: datetime
    ends_at: datetime
    reason: str = ""
    created_by: str


class RotaSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    version: int
    updated_by: str
    updated_at: datetime
    on_call: OnCall


class RotaListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    rotas: list[RotaSummary] = []


class Gap(BaseModel):
    model_config = ConfigDict(frozen=True)
    starts_at: datetime
    ends_at: datetime


class RotaDetail(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    rota: Rota
    on_call: OnCall
    overrides: list[OverrideView] = []
    gaps: list[Gap] = []


class Removed(BaseModel):
    model_config = ConfigDict(frozen=True)
    removed: bool


def _store(request: Request) -> OnCallStore:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    return OnCallStore(pool, auditor=getattr(request.app.state, "alert_auditor", None))


async def _days(request: Request, key: str, default: int) -> int:
    try:
        return max(1, int(await request.app.state.config_service.get(key)))
    except Exception:
        return default


@router_v1.get("/rotas", response_model=RotaListResponse)
async def list_rotas(request: Request, user: dict = Depends(require_read)) -> RotaListResponse:
    store, bank = _store(request), user["bank_id"]
    calendar, now = await load_calendar(request.app.state.config_service), datetime.now(timezone.utc)
    return RotaListResponse(rotas=[RotaSummary(**row, on_call=await store.current(bank, row["name"], now, calendar)) for row in await store.list_rotas(bank)])


@router_v1.get("/rotas/{name}", response_model=RotaDetail)
async def get_rota(request: Request, name: str = RotaName, user: dict = Depends(require_read)) -> RotaDetail:
    store, bank = _store(request), user["bank_id"]
    rota = await store.get_rota(bank, name)
    if rota is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_ROTA_NOT_FOUND"))
    calendar, now = await load_calendar(request.app.state.config_service), datetime.now(timezone.utc)
    gap_days = await _days(request, "alerting.oncall_gap_days", DEFAULT_GAP_DAYS)
    step = await _days(request, "alerting.oncall_gap_step_minutes", DEFAULT_GAP_STEP_MINUTES)
    overrides = await store.overrides(bank, name, since=now, days=await _days(request, "alerting.oncall_override_days", DEFAULT_OVERRIDE_DAYS))
    gaps = await store.gaps(bank, name, calendar, start=now, days=gap_days, step_minutes=step)
    return RotaDetail(name=name, rota=rota, on_call=await store.current(bank, name, now, calendar), overrides=[OverrideView(**o) for o in overrides],
                      gaps=[Gap(starts_at=a, ends_at=b) for a, b in gaps])


@router_v1.put("/rotas/{name}", response_model=SaveRotaResponse)
async def save_rota(request: Request, body: SaveRotaRequest, name: str = RotaName, user: dict = Depends(require_change)) -> SaveRotaResponse:
    try:
        version = await _store(request).save_rota(user["bank_id"], name, body.rota, actor=user["user_id"])
    except RotaInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"message": get_message("ALERT_API_ROTA_INVALID"), "codes": exc.codes})
    return SaveRotaResponse(name=name, version=version)


@router_v1.post("/rotas/{name}/overrides", response_model=OverrideCreated, status_code=status.HTTP_201_CREATED)
async def add_override(request: Request, body: OverrideRequest, name: str = RotaName, user: dict = Depends(require_change)) -> OverrideCreated:
    try:
        oid = await _store(request).add_override(user["bank_id"], name, body.user_id, body.starts_at, body.ends_at, reason=body.reason, actor=user["user_id"])
    except OverrideInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"message": get_message("ALERT_API_OVERRIDE_INVALID"), "codes": [exc.code]})
    return OverrideCreated(override_id=oid)


@router_v1.delete("/rotas/{name}/overrides/{override_id}", response_model=Removed)
async def remove_override(request: Request, override_id: str, name: str = RotaName, user: dict = Depends(require_change)) -> Removed:
    if not await _store(request).remove_override(user["bank_id"], override_id, actor=user["user_id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_OVERRIDE_NOT_FOUND"))
    return Removed(removed=True)
