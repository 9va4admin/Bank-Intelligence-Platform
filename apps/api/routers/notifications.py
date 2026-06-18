"""
Notifications API router — send, list, and retry notifications via email and WhatsApp.

All routes versioned under /v1/notifications/.
Read access: ops_manager, bank_it_admin, compliance_officer.
Write access (send, retry): ops_manager, bank_it_admin.
ops_reviewer and fraud_analyst cannot access notification routes.

No PII in any response — recipients are referenced by user_id (ref), never raw email/phone.
Message body is never returned in list view — only delivery metadata.
"""
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/notifications", tags=["Notifications v1"])

_bearer = HTTPBearer(auto_error=False)

_READ_ROLES = {"ops_manager", "bank_it_admin", "compliance_officer"}
_WRITE_ROLES = {"ops_manager", "bank_it_admin"}


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials
    if token.startswith("test-token-"):
        bank_id = token.removeprefix("test-token-")
        return {"bank_id": bank_id, "user_id": "test-user", "role": "ops_manager"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_read_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot access notification routes",
        )
    return user


def require_write_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot send or retry notifications",
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
    queued_at: str


class NotificationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    channel: Literal["email", "whatsapp"]
    template_id: str
    recipient_ref: str          # user_id — never raw email/phone
    delivery_status: Literal["QUEUED", "SENT", "DELIVERED", "FAILED", "RETRYING"]
    attempt_count: int
    created_at: str
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
    channel: Literal["email", "whatsapp"]
    template_id: str
    recipient_ref: str          # user_id — never raw email/phone
    delivery_status: Literal["QUEUED", "SENT", "DELIVERED", "FAILED", "RETRYING"]
    attempt_count: int
    last_attempt_at: Optional[str] = None
    delivered_at: Optional[str] = None
    error_code: Optional[str] = None
    created_at: str


class NotificationRetryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    notification_id: str
    status: Literal["QUEUED", "RETRYING"]
    retried_at: str


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.post("/send", response_model=NotificationSendResponse, status_code=202)
async def send_notification(
    body: NotificationSendRequest,
    user: dict = Depends(require_write_role),
) -> NotificationSendResponse:
    bank_id = user["bank_id"]

    log.info("notifications.send",
             bank_id=bank_id,
             channel=body.channel,
             template_id=body.template_id,
             recipient_ref=body.recipient_ref)

    # In production: publish to platform.notifications Kafka topic.
    # NotificationWorkflow picks up the event, routes to email_channel or whatsapp_channel.
    # WhatsApp: only pre-approved templates permitted (Meta WA Business API requirement).
    notification_id = f"notif-{bank_id}-{body.template_id}-queued"
    return NotificationSendResponse(
        notification_id=notification_id,
        channel=body.channel,
        status="QUEUED",
        queued_at=datetime.now(timezone.utc).isoformat(),
    )


@router_v1.get("", response_model=NotificationsListResponse)
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    delivery_status: Optional[str] = Query(default=None),
    user: dict = Depends(require_read_role),
) -> NotificationsListResponse:
    bank_id = user["bank_id"]

    log.info("notifications.list",
             bank_id=bank_id,
             limit=limit,
             channel=channel,
             delivery_status=delivery_status)

    # In production: SELECT notification_id, channel, template_id, recipient_ref,
    # delivery_status, attempt_count, created_at FROM platform.notification_records
    # WHERE bank_id=? ORDER BY created_at DESC with cursor pagination.
    # Never SELECT * — no message body, no raw recipient contact details.
    return NotificationsListResponse(
        notifications=[],
        total=0,
        limit=limit,
        next_cursor=None,
    )


@router_v1.get("/{notification_id}", response_model=NotificationDetail)
async def get_notification(
    notification_id: str,
    user: dict = Depends(require_read_role),
) -> NotificationDetail:
    bank_id = user["bank_id"]

    log.info("notifications.get", bank_id=bank_id, notification_id=notification_id)

    # In production: SELECT explicit columns FROM platform.notification_records
    # WHERE notification_id=? AND bank_id=?
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")


@router_v1.post("/{notification_id}/retry", response_model=NotificationRetryResponse, status_code=202)
async def retry_notification(
    notification_id: str,
    user: dict = Depends(require_write_role),
) -> NotificationRetryResponse:
    bank_id = user["bank_id"]

    log.info("notifications.retry", bank_id=bank_id, notification_id=notification_id)

    # In production: lookup notification, verify status == FAILED, re-publish to Kafka.
    # NotificationWorkflow handles retry with exponential backoff.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
