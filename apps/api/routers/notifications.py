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

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext
from shared.event_bus.topics import PLATFORM_NOTIFICATIONS

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

    pool = getattr(request.app.state, "db_pool_platform", None)
    if pool is not None:
        try:
            cursor_data = _decode_notif_cursor(cursor) if cursor else None
            params: list[Any] = [bank_id]
            where = ["bank_id = $1"]
            if channel:
                params.append(channel)
                where.append(f"channel = ${len(params)}")
            if delivery_status:
                params.append(delivery_status)
                where.append(f"delivery_status = ${len(params)}")
            if cursor_data:
                params.append(cursor_data["created_at"])
                params.append(cursor_data["notification_id"])
                where.append(
                    f"(created_at, notification_id::text) < (${len(params)-1}::timestamptz, ${len(params)})"
                )
            params.append(limit + 1)
            query = f"""
                SELECT notification_id, channel, template_id, recipient_ref,
                       delivery_status, attempt_count, created_at
                FROM platform.notification_records
                WHERE {" AND ".join(where)}
                ORDER BY created_at DESC, notification_id DESC
                LIMIT ${len(params)}
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            dicts = [dict(r) for r in rows]
            has_more = len(dicts) > limit
            page = dicts[:limit]
            next_cursor = None
            if has_more and page:
                last = page[-1]
                next_cursor = _encode_notif_cursor(last["created_at"], str(last["notification_id"]))
            async with pool.acquire() as conn:
                total_row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM platform.notification_records WHERE bank_id = $1",
                    bank_id,
                )
            total = int(total_row["cnt"]) if total_row else 0
            return NotificationsListResponse(
                notifications=[
                    NotificationSummary(
                        notification_id=str(r["notification_id"]),
                        channel=r["channel"],
                        template_id=r["template_id"],
                        recipient_ref=r["recipient_ref"],
                        delivery_status=r["delivery_status"],
                        attempt_count=int(r["attempt_count"] or 0),
                        created_at=str(r["created_at"]),
                    )
                    for r in page
                ],
                total=total,
                limit=limit,
                next_cursor=next_cursor,
            )
        except Exception:
            log.warning("notifications.list.db_error", bank_id=bank_id)

    return NotificationsListResponse(notifications=[], total=0, limit=limit, next_cursor=None)


@router_v1.get("/{notification_id}", response_model=NotificationDetail)
async def get_notification(
    request: Request,
    notification_id: str,
    user: dict = Depends(require_read_role),
) -> NotificationDetail:
    bank_id = user["bank_id"]
    log.info("notifications.get", bank_id=bank_id, notification_id=notification_id)

    pool = getattr(request.app.state, "db_pool_platform", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT notification_id, channel, template_id, recipient_ref,
                           delivery_status, attempt_count, last_attempt_at,
                           delivered_at, error_code, created_at
                    FROM platform.notification_records
                    WHERE notification_id = $1::uuid AND bank_id = $2
                    """,
                    notification_id, bank_id,
                )
            if row:
                r = dict(row)
                return NotificationDetail(
                    notification_id=str(r["notification_id"]),
                    channel=r["channel"],
                    template_id=r["template_id"],
                    recipient_ref=r["recipient_ref"],
                    delivery_status=r["delivery_status"],
                    attempt_count=int(r["attempt_count"] or 0),
                    last_attempt_at=str(r["last_attempt_at"]) if r.get("last_attempt_at") else None,
                    delivered_at=str(r["delivered_at"]) if r.get("delivered_at") else None,
                    error_code=r.get("error_code"),
                    created_at=str(r["created_at"]),
                )
        except Exception:
            log.warning("notifications.get.db_error", bank_id=bank_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")


@router_v1.post("/{notification_id}/retry", response_model=NotificationRetryResponse, status_code=202)
async def retry_notification(
    request: Request,
    notification_id: str,
    user: dict = Depends(require_write_role),
) -> NotificationRetryResponse:
    bank_id = user["bank_id"]
    log.info("notifications.retry", bank_id=bank_id, notification_id=notification_id)

    retried_at = datetime.now(timezone.utc).isoformat()
    producer = getattr(request.app.state, "kafka_producer", None)

    pool = getattr(request.app.state, "db_pool_platform", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT notification_id, channel, template_id, recipient_ref,
                           delivery_status, event_data
                    FROM platform.notification_records
                    WHERE notification_id = $1::uuid AND bank_id = $2
                    """,
                    notification_id, bank_id,
                )
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
            if row["delivery_status"] not in ("FAILED", "RETRYING"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot retry notification in status '{row['delivery_status']}'",
                )
            # Re-publish to Kafka for retry handling
            if producer is not None:
                event = {
                    "notification_id": str(row["notification_id"]),
                    "bank_id": bank_id,
                    "channel": row["channel"],
                    "recipient_ref": row["recipient_ref"],
                    "template_id": row["template_id"],
                    "context": row.get("event_data") or {},
                    "queued_at": retried_at,
                    "schema_version": "1.0",
                    "is_retry": True,
                }
                await producer.send_and_wait(
                    PLATFORM_NOTIFICATIONS,
                    value=json.dumps(event).encode(),
                    key=str(row["notification_id"]).encode(),
                )
            return NotificationRetryResponse(
                notification_id=str(row["notification_id"]),
                status="RETRYING",
                retried_at=retried_at,
            )
        except HTTPException:
            raise
        except Exception:
            log.warning("notifications.retry.db_error", bank_id=bank_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
