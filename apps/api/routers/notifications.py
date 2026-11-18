"""
Notifications API router — send, list, and retry notifications via email and WhatsApp.

All routes versioned under /v1/notifications/.
Read access: ops_manager, bank_it_admin, compliance_officer.
Write access (send, retry): ops_manager, bank_it_admin.
ops_reviewer and fraud_analyst cannot access notification routes.

No PII in any response — recipients are referenced by user_id (ref), never raw email/phone.
Message body is never returned in list view — only delivery metadata.
"""
import base64
import json
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from apps.api.schemas.types import IsoTimestamp, OptIsoTimestamp

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext
from shared.alerting.delivery import DeliveryStore
from shared.event_bus.topics import PLATFORM_NOTIFICATIONS
from shared.messages import get_message

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/notifications", tags=["Notifications v1"])

_READ_ROLES = {"ops_manager", "bank_it_admin", "compliance_officer"}
_WRITE_ROLES = {"ops_manager", "bank_it_admin"}


async def get_current_user(
    ctx: UserContext = Depends(require_user_context),
) -> dict[str, Any]:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.
    Re-shaped to this router's existing dict-based downstream code.
    No token parsing, no test-token backdoor. ASTRA-01.
    """
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def require_read_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_message("API_ROLE_CANNOT_ACCESS_NOTIFICATION_ROUT", user=user.get('role')),
        )
    return user


def require_write_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_message("API_ROLE_CANNOT_SEND_OR_RETRY", user=user.get('role')),
        )
    return user


# ── Response models ──────────────────────────────────────────────────────────

class NotificationSendRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    channel: Literal["email", "whatsapp"]
    recipient_ref: str          # user_id only — never raw email or phone number
    template_id: str            # pre-approved template (WhatsApp requires pre-approved templates)
    context: dict[str, Any]     # template variables — must not include PII values


class NotificationSendResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    channel: Literal["email", "whatsapp"]
    status: Literal["QUEUED", "SENT", "FAILED"]
    queued_at: IsoTimestamp


class NotificationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    channel: Literal["email", "whatsapp", "bell", "sms", "webhook", "syslog"]
    template_id: str
    recipient_ref: str          # user_id — never raw email/phone
    delivery_status: Literal["QUEUED", "SENT", "DELIVERED", "FAILED", "RETRYING"]
    attempt_count: int
    created_at: IsoTimestamp
    # No message body in list view — only metadata


class NotificationsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    notifications: list[NotificationSummary]
    total: int
    limit: int
    next_cursor: Optional[str] = None


class NotificationDetail(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    channel: Literal["email", "whatsapp", "bell", "sms", "webhook", "syslog"]
    template_id: str
    recipient_ref: str          # user_id — never raw email/phone
    delivery_status: Literal["QUEUED", "SENT", "DELIVERED", "FAILED", "RETRYING"]
    attempt_count: int
    last_attempt_at: OptIsoTimestamp = None
    delivered_at: OptIsoTimestamp = None
    error_code: Optional[str] = None
    created_at: IsoTimestamp


class NotificationRetryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    status: Literal["QUEUED", "RETRYING"]
    retried_at: IsoTimestamp


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.post("/send", response_model=NotificationSendResponse, status_code=202)
async def send_notification(
    request: Request,
    body: NotificationSendRequest,
    user: dict = Depends(require_write_role),
) -> NotificationSendResponse:
    bank_id = user["bank_id"]
    notification_id = f"notif-{bank_id}-{str(_uuid.uuid4())[:8]}"
    queued_at = datetime.now(timezone.utc).isoformat()

    log.info("notifications.send",
             bank_id=bank_id,
             channel=body.channel,
             template_id=body.template_id,
             recipient_ref=body.recipient_ref,
             notification_id=notification_id)

    # Publish to platform.notifications — NotificationWorkflow routes to channel.
    # WhatsApp: only pre-approved templates permitted (Meta WA Business API requirement).
    producer = getattr(request.app.state, "kafka_producer", None)
    if producer is not None:
        try:
            event = {
                "notification_id": notification_id,
                "bank_id": bank_id,
                "channel": body.channel,
                "recipient_ref": body.recipient_ref,
                "template_id": body.template_id,
                "context": body.context,
                "queued_at": queued_at,
                "schema_version": "1.0",
            }
            await producer.send_and_wait(
                PLATFORM_NOTIFICATIONS,
                value=json.dumps(event).encode(),
                key=notification_id.encode(),
            )
            log.info("notifications.published", notification_id=notification_id, bank_id=bank_id)
        except Exception as exc:
            log.error("notifications.publish_failed", notification_id=notification_id, error=str(exc))

    return NotificationSendResponse(
        notification_id=notification_id,
        channel=body.channel,
        status="QUEUED",
        queued_at=queued_at,
    )


def _encode_notif_cursor(created_at: Any, notification_id: str) -> str:
    payload = json.dumps({"created_at": str(created_at), "notification_id": notification_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_notif_cursor(cursor: str) -> Optional[dict]:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        return None


# The one delivery log is platform.alert_deliveries (the outbox). Its statuses are shown with the names this API has always used.
_STATUS_VIEW = {"PENDING": "QUEUED", "SENDING": "QUEUED", "SENT": "SENT", "FAILED": "RETRYING", "UNDELIVERED": "FAILED", "SKIPPED": "FAILED"}
_STATUS_FILTER = {"QUEUED": ["PENDING", "SENDING"], "SENT": ["SENT"], "DELIVERED": ["SENT"], "RETRYING": ["FAILED"], "FAILED": ["UNDELIVERED", "SKIPPED"]}


def _delivery_pool(request: Request) -> Any:
    return getattr(request.app.state, "db_pool_cts", None) or getattr(request.app.state, "db_pool_platform", None)


@router_v1.get("", response_model=NotificationsListResponse)
async def list_notifications(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    delivery_status: Optional[str] = Query(default=None),
    user: dict = Depends(require_read_role),
) -> NotificationsListResponse:
    bank_id = user["bank_id"]
    log.info("notifications.list", bank_id=bank_id, limit=limit, channel=channel)
    pool = _delivery_pool(request)
    if pool is None:
        return NotificationsListResponse(notifications=[], total=0, limit=limit, next_cursor=None)
    store = DeliveryStore(pool)
    statuses = _STATUS_FILTER.get(delivery_status or "", None) if delivery_status else None
    if delivery_status and statuses is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=get_message("API_NOTIFICATION_NOT_FOUND"))
    try:
        page = await store.list_deliveries(bank_id, limit=limit, cursor=cursor, statuses=statuses, channel=channel)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=get_message("ALERT_API_BAD_CURSOR"))
    except Exception:
        log.warning("notifications.list.db_error", bank_id=bank_id)
        return NotificationsListResponse(notifications=[], total=0, limit=limit, next_cursor=None)
    return NotificationsListResponse(
        notifications=[
            NotificationSummary(notification_id=r["delivery_id"], channel=r["channel"], template_id=r["template_id"] or "", recipient_ref=r["recipient_ref"],
                                delivery_status=_STATUS_VIEW[r["status"]], attempt_count=int(r["attempt"] or 0), created_at=str(r["created_at"]))
            for r in page.items],
        total=await store.count_deliveries(bank_id), limit=limit, next_cursor=page.next_cursor)


@router_v1.get("/{notification_id}", response_model=NotificationDetail)
async def get_notification(
    request: Request,
    notification_id: str,
    user: dict = Depends(require_read_role),
) -> NotificationDetail:
    bank_id = user["bank_id"]
    log.info("notifications.get", bank_id=bank_id, notification_id=notification_id)
    pool = _delivery_pool(request)
    r = await DeliveryStore(pool).get_delivery(bank_id, notification_id) if pool is not None else None
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("API_NOTIFICATION_NOT_FOUND"))
    return NotificationDetail(
        notification_id=r["delivery_id"], channel=r["channel"], template_id=r["template_id"] or "", recipient_ref=r["recipient_ref"],
        delivery_status=_STATUS_VIEW[r["status"]], attempt_count=int(r["attempt"] or 0),
        last_attempt_at=str(r["completed_at"]) if r.get("completed_at") else None,
        delivered_at=str(r["completed_at"]) if r["status"] == "SENT" and r.get("completed_at") else None,
        error_code=r.get("provider_class"), created_at=str(r["created_at"]))


@router_v1.post("/{notification_id}/retry", response_model=NotificationRetryResponse, status_code=202)
async def retry_notification(
    request: Request,
    notification_id: str,
    user: dict = Depends(require_write_role),
) -> NotificationRetryResponse:
    """Send a failed or given-up delivery again: it becomes due at once and the next outbox run (within a minute) sends it."""
    bank_id = user["bank_id"]
    log.info("notifications.retry", bank_id=bank_id, notification_id=notification_id)
    pool = _delivery_pool(request)
    store = DeliveryStore(pool) if pool is not None else None
    if store is None or await store.get_delivery(bank_id, notification_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("API_NOTIFICATION_NOT_FOUND"))
    if not await store.retry_now(bank_id, notification_id):
        current = (await store.get_delivery(bank_id, notification_id))["status"]
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=get_message("API_CANNOT_RETRY_NOTIFICATION_IN_STATUS", row=current))
    return NotificationRetryResponse(notification_id=notification_id, status="RETRYING", retried_at=datetime.now(timezone.utc).isoformat())
