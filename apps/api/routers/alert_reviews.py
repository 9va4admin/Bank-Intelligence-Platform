"""
Post-incident reviews and mitigation actions API. All routes under /v1/ops/alert-reviews/.
Read: ops_manager, bank_it_admin, compliance_officer, rbi_examiner. Change (submit a review, add an action, move an action on): ops_manager, bank_it_admin, compliance_officer.
An action is verified by a DIFFERENT person from the one who finished it. The effectiveness field is a hint worked out from recurrence, never a verdict.
"""
from datetime import date
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.alerting.reviews import Action, Review, ReviewInvalid, ReviewStore
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()
router_v1 = APIRouter(prefix="/v1/ops/alert-reviews", tags=["Alert reviews v1"])

_READ_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer", "rbi_examiner"})
_WRITE_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer"})
_NOT_FOUND, _UNPROCESSABLE, _CONFLICT = status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_ENTITY, status.HTTP_409_CONFLICT
_REFUSALS = {
    "not_found": (_NOT_FOUND, "ALERT_API_REVIEW_NOT_FOUND"), "bad_category": (_UNPROCESSABLE, "ALERT_API_REVIEW_CATEGORY"), "narrative_short": (_UNPROCESSABLE, "ALERT_API_REVIEW_NARRATIVE"),
    "unknown_risk": (_UNPROCESSABLE, "ALERT_API_REVIEW_RISK"), "already_submitted": (_CONFLICT, "ALERT_API_REVIEW_SUBMITTED"), "review_not_submitted": (_CONFLICT, "ALERT_API_REVIEW_NOT_SUBMITTED"),
    "bad_action": (_UNPROCESSABLE, "ALERT_API_ACTION_INVALID"), "due_in_past": (_UNPROCESSABLE, "ALERT_API_ACTION_DUE"), "bad_transition": (_CONFLICT, "ALERT_API_ACTION_TRANSITION"),
    "evidence_required": (_UNPROCESSABLE, "ALERT_API_ACTION_EVIDENCE"), "note_required": (_UNPROCESSABLE, "ALERT_API_ACTION_NOTE"), "same_person": (_CONFLICT, "ALERT_API_ACTION_SAME_PERSON"),
}


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def _require(roles: frozenset, message_key: str):
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message(message_key))
        return user
    return check


require_read = _require(_READ_ROLES, "ALERT_API_ROLE_CANNOT_READ")
require_write = _require(_WRITE_ROLES, "ALERT_API_ROLE_CANNOT_CHANGE_REVIEWS")


class SubmitRequest(BaseModel):
    category: str = Field(..., max_length=40)
    narrative: str = Field(..., max_length=4000)
    contributing_factors: str = Field("", max_length=2000)
    detection_gap: str = Field("", max_length=2000)
    impact: str = Field("", max_length=2000)
    risk_id: Optional[str] = Field(None, max_length=80)


class ActionRequest(BaseModel):
    kind: Literal["corrective", "preventive"]
    description: str = Field(..., max_length=2000)
    owner: str = Field(..., max_length=200)
    due_on: date


class StatusRequest(BaseModel):
    status: Literal["IN_PROGRESS", "DONE", "VERIFIED", "WONT_FIX"]
    evidence: str = Field("", max_length=2000)
    note: str = Field("", max_length=2000)


class ReviewsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    reviews: list[Review]


class ActionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    actions: list[Action]


async def _store(request: Request) -> ReviewStore:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    config = request.app.state.config_service

    async def number(key: str, default: int) -> int:
        try:
            return int(await config.get(key))
        except Exception:  # noqa: BLE001
            return default
    return ReviewStore(pool, due_days={"P0": await number("alerting.pir_due_days_p0", 3), "P1": await number("alerting.pir_due_days_p1", 7)},
                       effectiveness_days=await number("alerting.effectiveness_days", 30), min_narrative_chars=await number("alerting.review_min_narrative_chars", 20),
                       auditor=getattr(request.app.state, "alert_auditor", None))


def _refuse(exc: ReviewInvalid) -> HTTPException:
    code, key = _REFUSALS.get(exc.code, (_UNPROCESSABLE, "ALERT_API_ACTION_INVALID"))
    return HTTPException(status_code=code, detail=get_message(key))


@router_v1.get("/reviews", response_model=ReviewsResponse)
async def list_reviews(request: Request, status_filter: Optional[Literal["DUE", "SUBMITTED"]] = Query(None, alias="status"), user: dict = Depends(require_read)) -> ReviewsResponse:
    return ReviewsResponse(reviews=await (await _store(request)).list_reviews(user["bank_id"], status=status_filter))


@router_v1.post("/reviews/{review_id}/submit", response_model=Review)
async def submit_review(review_id: str, body: SubmitRequest, request: Request, user: dict = Depends(require_write)) -> Review:
    try:
        return await (await _store(request)).submit(user["bank_id"], review_id, user["user_id"], category=body.category, narrative=body.narrative, contributing=body.contributing_factors,
                                                     detection_gap=body.detection_gap, impact=body.impact, risk_id=body.risk_id)
    except ReviewInvalid as exc:
        raise _refuse(exc)


@router_v1.post("/reviews/{review_id}/actions", response_model=Action, status_code=status.HTTP_201_CREATED)
async def add_action(review_id: str, body: ActionRequest, request: Request, user: dict = Depends(require_write)) -> Action:
    try:
        return await (await _store(request)).add_action(user["bank_id"], review_id, user["user_id"], body.kind, body.description, body.owner, body.due_on)
    except ReviewInvalid as exc:
        raise _refuse(exc)


@router_v1.get("/actions", response_model=ActionsResponse)
async def list_actions(request: Request, user: dict = Depends(require_read)) -> ActionsResponse:
    return ActionsResponse(actions=await (await _store(request)).list_actions(user["bank_id"]))


@router_v1.post("/actions/{action_id}/status", response_model=Action)
async def set_action_status(action_id: str, body: StatusRequest, request: Request, user: dict = Depends(require_write)) -> Action:
    try:
        return await (await _store(request)).set_status(user["bank_id"], action_id, user["user_id"], body.status, evidence=body.evidence, note=body.note)
    except ReviewInvalid as exc:
        raise _refuse(exc)
