"""
Inbox API (the bell): each user's own notifications.

All routes versioned under /v1/inbox/. Any signed-in user reads and manages their OWN inbox only; every query is scoped to bank and user, and
another person's notification is a 404 (never a hint that it exists). Acknowledging a critical notification also acknowledges its incident when the
user's role may do that.
"""
from datetime import datetime
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from modules.cts.workflows.escalation_control import stop_escalation
from shared.alerting.inbox import InboxStore
from shared.alerting.incidents import MAX_LIST, IncidentStore
from shared.audit.audit_event import AuditEventType
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/inbox", tags=["Inbox v1"])

_INCIDENT_ACK_ROLES = frozenset({"ops_manager", "bank_it_admin"})
Severity = Literal["P0", "P1", "P2", "P3"]


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    """The central auth chokepoint (session cookie, CSRF, bank scope), re-shaped for this router."""
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


class NotificationItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    incident_id: Optional[str] = None
    severity: Severity
    title: str
    body: str = ""
    action_link: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None
    acked_at: Optional[datetime] = None


class UnreadCounts(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int = 0
    P0: int = 0
    P1: int = 0
    P2: int = 0
    P3: int = 0


class InboxSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    unread: UnreadCounts
    pinned: list[NotificationItem] = []        # critical and not yet acknowledged: shown above every page


class InboxPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    notifications: list[NotificationItem] = []
    next_cursor: Optional[str] = None


class MarkedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    marked: int


class AckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    incident_acknowledged: bool


def _pool(request: Request) -> Any:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    return pool


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_NOTIFICATION_NOT_FOUND"))


@router_v1.get("/summary", response_model=InboxSummary)
async def summary(request: Request, pinned_limit: int = Query(5, ge=1, le=MAX_LIST), user: dict = Depends(get_current_user)) -> InboxSummary:
    store = InboxStore(_pool(request))
    counts = await store.unread_counts(user["bank_id"], user["user_id"])
    pinned = await store.pinned(user["bank_id"], user["user_id"], limit=pinned_limit)
    return InboxSummary(unread=UnreadCounts(**counts), pinned=[NotificationItem(**row) for row in pinned])


@router_v1.get("", response_model=InboxPage)
async def list_inbox(
    request: Request,
    limit: int = Query(30, ge=1, le=MAX_LIST),
    cursor: Optional[str] = None,
    unread_only: bool = False,
    user: dict = Depends(get_current_user),
) -> InboxPage:
    try:
        page = await InboxStore(_pool(request)).list_for_user(user["bank_id"], user["user_id"], limit=limit, cursor=cursor, unread_only=unread_only)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=get_message("ALERT_API_BAD_CURSOR"))
    return InboxPage(notifications=[NotificationItem(**row) for row in page.items], next_cursor=page.next_cursor)


@router_v1.post("/read-all", response_model=MarkedResponse)
async def read_all(request: Request, user: dict = Depends(get_current_user)) -> MarkedResponse:
    return MarkedResponse(marked=await InboxStore(_pool(request)).mark_all_read(user["bank_id"], user["user_id"]))


@router_v1.post("/{notification_id}/read", response_model=MarkedResponse)
async def read_one(request: Request, notification_id: str, user: dict = Depends(get_current_user)) -> MarkedResponse:
    if not await InboxStore(_pool(request)).mark_read(user["bank_id"], user["user_id"], notification_id):
        raise _not_found()
    return MarkedResponse(marked=1)


@router_v1.post("/{notification_id}/acknowledge", response_model=AckResult)
async def acknowledge(request: Request, notification_id: str, user: dict = Depends(get_current_user)) -> AckResult:
    pool = _pool(request)
    bank_id, who = user["bank_id"], user["user_id"]
    inbox = InboxStore(pool)
    acked = await inbox.acknowledge(bank_id, who, notification_id)
    if acked is None:
        if not await inbox.exists(bank_id, who, notification_id):
            raise _not_found()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=get_message("ALERT_API_ALREADY_ACKNOWLEDGED"))
    incident_acknowledged = False
    incident_id = acked.get("incident_id")
    if incident_id and user["role"] in _INCIDENT_ACK_ROLES:
        incident_acknowledged = await IncidentStore(pool).acknowledge(bank_id, incident_id, who)
        auditor = getattr(request.app.state, "alert_auditor", None)
        if incident_acknowledged:
            await stop_escalation(getattr(request.app.state, "temporal_client", None), bank_id, incident_id, "acknowledged")
        if incident_acknowledged and auditor is not None:
            await auditor.lifecycle(AuditEventType.ALERT_ACKNOWLEDGED, bank_id=bank_id, incident_id=incident_id, actor=who,
                                    detail={"via": "inbox"})
    log.info("inbox.acknowledged", bank_id=bank_id, incident_acknowledged=incident_acknowledged)
    return AckResult(notification_id=notification_id, incident_acknowledged=incident_acknowledged)
