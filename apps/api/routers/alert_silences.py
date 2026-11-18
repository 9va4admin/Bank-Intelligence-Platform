"""
Alert silences API: planned quiet periods so maintenance does not page people. All routes under /v1/admin/alert-silences/.
Read: ops_manager, bank_it_admin, compliance_officer. Create and cancel: ops_manager, bank_it_admin. Limits (maximum length, critical alerts, reason length) are bank settings.
"""
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from apps.api.dependencies import require_user_context
from shared.alerting.silences import Silence, SilenceInvalid, SilenceListing, SilenceStore
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()
router_v1 = APIRouter(prefix="/v1/admin/alert-silences", tags=["Alert silences v1"])

_READ_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer"})
_WRITE_ROLES = frozenset({"ops_manager", "bank_it_admin"})
_REFUSAL_KEYS = {"p0_not_allowed": "ALERT_API_SILENCE_P0", "too_long": "ALERT_API_SILENCE_TOO_LONG", "reason_too_short": "ALERT_API_SILENCE_REASON", "ends_before_start": "ALERT_API_SILENCE_END",
                 "no_priority": "ALERT_API_SILENCE_PRIORITY", "unknown_priority": "ALERT_API_SILENCE_PRIORITY"}


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def _require(roles: frozenset, message_key: str):
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message(message_key))
        return user
    return check


require_read = _require(_READ_ROLES, "ALERT_API_ROLE_CANNOT_READ")
require_write = _require(_WRITE_ROLES, "ALERT_API_ROLE_CANNOT_CHANGE_SILENCES")


class CreateRequest(BaseModel):
    component: str = Field("", max_length=80)                    # empty = every component
    priorities: list[str] = Field(default_factory=list, max_length=4)
    starts_at: Optional[datetime] = None                         # empty = now
    ends_at: datetime
    reason: str = Field(..., max_length=500)


def _store(request: Request) -> SilenceStore:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    return pool


async def _build(request: Request) -> SilenceStore:
    pool = _store(request)
    config = request.app.state.config_service

    async def setting(key: str, default: Any) -> Any:
        try:
            return await config.get(key)
        except Exception:  # noqa: BLE001
            return default
    allow = await setting("alerting.silence_allow_p0", False)
    return SilenceStore(pool, max_hours=int(await setting("alerting.silence_max_hours", 24)), allow_p0=allow is True or str(allow).lower() in ("true", "1", "yes"),
                        min_reason_chars=int(await setting("alerting.silence_min_reason_chars", 10)), auditor=getattr(request.app.state, "alert_auditor", None))


@router_v1.get("", response_model=SilenceListing)
async def list_silences(request: Request, user: dict = Depends(require_read)) -> SilenceListing:
    return await (await _build(request)).listing(user["bank_id"])


@router_v1.post("", response_model=Silence, status_code=status.HTTP_201_CREATED)
async def create_silence(request: Request, body: CreateRequest, user: dict = Depends(require_write)) -> Silence:
    store = await _build(request)
    try:
        return await store.create(user["bank_id"], body.component, body.priorities, body.starts_at or datetime.now(timezone.utc), body.ends_at, body.reason, user["user_id"])
    except SilenceInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=get_message(_REFUSAL_KEYS[exc.code]))


@router_v1.delete("/{silence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_silence(silence_id: str, request: Request, user: dict = Depends(require_write)) -> Response:
    if not await (await _build(request)).cancel(user["bank_id"], silence_id, user["user_id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_SILENCE_NOT_FOUND"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
