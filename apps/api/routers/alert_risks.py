"""
Alert risk register API: the risks to alerting itself. All routes under /v1/admin/alert-risks/.
Read: ops_manager, bank_it_admin, compliance_officer, rbi_examiner. Change (seed, owner, mitigation, declare, verify, reopen): ops_manager, bank_it_admin, compliance_officer.
Only a person declares a risk mitigated and a DIFFERENT person verifies it; the system never closes a risk by itself.
"""
from datetime import date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.alerting.risks import Risk, RiskInvalid, RiskStore, RiskSummary
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()
router_v1 = APIRouter(prefix="/v1/admin/alert-risks", tags=["Alert risks v1"])

_READ_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer", "rbi_examiner"})
_WRITE_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer"})
_REFUSALS = {"not_found": (status.HTTP_404_NOT_FOUND, "ALERT_API_RISK_NOT_FOUND"), "bad_rating": (status.HTTP_422_UNPROCESSABLE_ENTITY, "ALERT_API_RISK_RATING"),
             "bad_owner": (status.HTTP_422_UNPROCESSABLE_ENTITY, "ALERT_API_RISK_OWNER"), "bad_review_date": (status.HTTP_422_UNPROCESSABLE_ENTITY, "ALERT_API_RISK_REVIEW_DATE"),
             "needs_owner_and_mitigation": (status.HTTP_409_CONFLICT, "ALERT_API_RISK_NEEDS_OWNER"), "same_person": (status.HTTP_409_CONFLICT, "ALERT_API_RISK_SAME_PERSON"),
             "not_mitigated": (status.HTTP_409_CONFLICT, "ALERT_API_RISK_NOT_MITIGATED")}


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def _require(roles: frozenset, message_key: str):
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message(message_key))
        return user
    return check


require_read = _require(_READ_ROLES, "ALERT_API_ROLE_CANNOT_READ")
require_write = _require(_WRITE_ROLES, "ALERT_API_ROLE_CANNOT_CHANGE_RISKS")


class RisksResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    risks: list[dict[str, Any]]
    summary: RiskSummary


class SeededResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    added: int


class UpdateRequest(BaseModel):
    owner: Optional[str] = Field(None, max_length=200)
    mitigation: Optional[str] = Field(None, max_length=4000)
    likelihood: Optional[int] = None
    impact: Optional[int] = None
    next_review_on: Optional[date] = None


async def _store(request: Request) -> RiskStore:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    try:
        days = int(await request.app.state.config_service.get("alerting.risk_review_days"))
    except Exception:  # noqa: BLE001
        days = 90
    return RiskStore(pool, review_days=days, auditor=getattr(request.app.state, "alert_auditor", None))


def _refuse(exc: RiskInvalid) -> HTTPException:
    code, key = _REFUSALS.get(exc.code, (status.HTTP_422_UNPROCESSABLE_ENTITY, "ALERT_API_RISK_OWNER"))
    return HTTPException(status_code=code, detail=get_message(key))


def _view(risk: Risk) -> dict[str, Any]:
    return {**risk.model_dump(mode="json"), "rating": risk.rating}


@router_v1.get("", response_model=RisksResponse)
async def list_risks(request: Request, user: dict = Depends(require_read)) -> RisksResponse:
    store = await _store(request)
    return RisksResponse(risks=[_view(r) for r in await store.list(user["bank_id"])], summary=await store.summary(user["bank_id"]))


@router_v1.post("/seed", response_model=SeededResponse)
async def seed(request: Request, user: dict = Depends(require_write)) -> SeededResponse:
    return SeededResponse(added=await (await _store(request)).seed(user["bank_id"], user["user_id"]))


@router_v1.patch("/{risk_id}")
async def update_risk(risk_id: str, body: UpdateRequest, request: Request, user: dict = Depends(require_write)) -> dict[str, Any]:
    try:
        return _view(await (await _store(request)).update(user["bank_id"], risk_id, user["user_id"], owner=body.owner, mitigation=body.mitigation, likelihood=body.likelihood,
                                                            impact=body.impact, next_review_on=body.next_review_on))
    except RiskInvalid as exc:
        raise _refuse(exc)


@router_v1.post("/{risk_id}/declare-mitigated")
async def declare(risk_id: str, request: Request, user: dict = Depends(require_write)) -> dict[str, Any]:
    try:
        return _view(await (await _store(request)).declare_mitigated(user["bank_id"], risk_id, user["user_id"]))
    except RiskInvalid as exc:
        raise _refuse(exc)


@router_v1.post("/{risk_id}/verify")
async def verify(risk_id: str, request: Request, user: dict = Depends(require_write)) -> dict[str, Any]:
    try:
        return _view(await (await _store(request)).verify(user["bank_id"], risk_id, user["user_id"]))
    except RiskInvalid as exc:
        raise _refuse(exc)


@router_v1.post("/{risk_id}/reopen")
async def reopen(risk_id: str, request: Request, user: dict = Depends(require_write)) -> dict[str, Any]:
    try:
        return _view(await (await _store(request)).reopen(user["bank_id"], risk_id, user["user_id"]))
    except RiskInvalid as exc:
        raise _refuse(exc)
