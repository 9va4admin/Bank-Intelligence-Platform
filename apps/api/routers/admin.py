"""
Admin API router — Layer 3 config management, user administration, infra health.

All routes versioned under /v1/admin/.
Maker-checker separation enforced:
  - ops_manager: maker only (submit threshold changes, read thresholds)
  - bank_it_admin: checker + user admin + health + read thresholds
  - All other roles: 403

No PII in any response — user_id and role only, no passwords or personal data.

Wiring (every config change):
  submit  → DB write → Immudb (CONFIG_CHANGE) → notification to bank_it_admin
  approve → DB write → Immudb (CONFIG_CHANGE) → Kafka platform.config.changed
            → notification to ops_manager (approved)
  reject  → DB write → Immudb (CONFIG_CHANGE) → notification to ops_manager (rejected)
  layer2  → DB write → Immudb (CONFIG_L2_CHANGE_REQUESTED) → notification to ASTRA support
"""
import secrets as _secrets
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.audit.audit_event import AuditEvent, AuditEventType
from shared.auth.rbac import UserContext
from shared.event_bus.topics import PLATFORM_CONFIG_CHANGED, PLATFORM_NOTIFICATIONS
from shared.messages import get_message

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/admin", tags=["Admin v1"])

# ── Layer 3 config schema (canonical — values overlaid from DB/config_service) ──
# Descriptions, layer, and default values live here.
# The list_thresholds route returns these with current_value from config_service.

_LAYER3_SCHEMA = [
    {"config_key": "stp_mode",                     "layer": "LAYER_3", "default": "FULL_MANUAL",
     "description": "STP mode: FULL_MANUAL | SUPERVISED | SELECTIVE | FULL_STP"},
    {"config_key": "stp_auto_confirm_threshold",   "layer": "LAYER_3", "default": "0.92",
     "description": "Fraud score below this auto-confirms (SELECTIVE/FULL_STP modes only)"},
    {"config_key": "human_review_fraud_threshold", "layer": "LAYER_3", "default": "0.72",
     "description": "Fraud score above this routes to human review"},
    {"config_key": "queue_tier_high_value_threshold",  "layer": "LAYER_3", "default": "100000",
     "description": "Cheques above this go to high_value Kafka topic and task queue"},
    {"config_key": "queue_tier_very_high_threshold",   "layer": "LAYER_3", "default": "1000000",
     "description": "Cheques above this go to very_high Kafka topic and task queue"},
    {"config_key": "allocation_mode",              "layer": "LAYER_3", "default": "HYBRID",
     "description": "Reviewer allocation: SELF | HYBRID | AUTO"},
    {"config_key": "allocation_lock_ttl_minutes",  "layer": "LAYER_3", "default": "10",
     "description": "Redis lock TTL for reviewer-claimed instruments (minutes)"},
    {"config_key": "iet_minutes",                  "layer": "LAYER_3", "default": "180",
     "description": "IET window in minutes (RBI mandated). Watchdog fires at T-30s regardless."},
    {"config_key": "ocr_min_confidence",           "layer": "LAYER_3", "default": "0.90",
     "description": "GOT-OCR2.0 confidence below this → human review"},
    {"config_key": "signature_min_match_score",    "layer": "LAYER_3", "default": "0.87",
     "description": "Siamese network score below this → human review"},
    {"config_key": "high_value_amount_threshold",  "layer": "LAYER_3", "default": "500000",
     "description": "Dual-approval threshold for high-value cheques (₹)"},
    {"config_key": "vault_miss_action",            "layer": "LAYER_1", "default": "HUMAN_REVIEW",
     "description": "LOCKED — vault miss always routes to human review (Layer 1 constraint)"},
    {"config_key": "outward_frozen_payee_action",  "layer": "LAYER_3", "default": "HUMAN_REVIEW",
     "description": "Payee account FROZEN on outward deposit: HUMAN_REVIEW (default) | AUTO_RETURN. FROZEN may be temporary (court/regulatory hold) — default sends to mismatch queue for ops review."},
    {"config_key": "outward_dormant_payee_action", "layer": "LAYER_3", "default": "HUMAN_REVIEW",
     "description": "Payee account DORMANT (no txns >2yr) on outward deposit: HUMAN_REVIEW (default) | AUTO_RETURN. Account may be reactivatable — human review avoids rejecting a recoverable instrument."},
    {"config_key": "outward_npa_payee_action",     "layer": "LAYER_3", "default": "HUMAN_REVIEW",
     "description": "Payee account NPA on outward deposit: HUMAN_REVIEW (default) | AUTO_RETURN. NPA is a credit classification — a deposit to the account may still be valid. Ops_manager must confirm return."},
]

_ADMIN_ROLES = {"bank_it_admin", "ops_manager"}
_CHECKER_ONLY = {"bank_it_admin"}
_MAKER_ONLY = {"ops_manager"}

_VALID_ROLES = {
    "ops_reviewer",
    "fraud_analyst",
    "ops_manager",
    "bank_it_admin",
    "compliance_officer",
    "rbi_examiner",
    "ml_engineer",
}


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


def require_admin_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot access admin routes",
        )
    return user


def require_checker_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _CHECKER_ONLY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot perform checker actions",
        )
    return user


def require_maker_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _MAKER_ONLY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot submit threshold changes",
        )
    return user


# ── Infrastructure DI (Kafka, Immudb audit stream, notifications) ─────────────
# Same pattern as mcp_connections.py — stubs in dev/test, real producers in prod.
# Tests override via app.dependency_overrides.

async def _default_event_publisher(topic: str, payload: dict) -> None:
    log.info("admin.kafka_stub", topic=topic, event_type=payload.get("event_type"))


def get_event_publisher(request: Request) -> Callable:
    from shared.event_bus.producer import EventProducer as KafkaEventProducer
    producer: Optional[KafkaEventProducer] = getattr(
        request.app.state, "kafka_producer_cts", None
    )
    if producer is None:
        return _default_event_publisher

    async def _real(topic: str, payload: dict) -> None:
        try:
            await producer.publish(
                topic=topic,
                event_type=payload.get("event_type", "CONFIG_EVENT"),
                payload=payload,
                schema_version="1.0",
            )
        except Exception as exc:
            log.error("admin.kafka_publish_failed", topic=topic, error=str(exc))

    return _real


async def _default_audit_stream_writer(**kwargs: Any) -> None:
    log.info("admin.audit_stream_stub", event_type=kwargs.get("event_type"))


def get_audit_stream_writer(request: Request) -> Callable:
    redis_cts = getattr(request.app.state, "redis_cts", None)
    if redis_cts is None:
        return _default_audit_stream_writer

    async def _real(**kwargs: Any) -> None:
        try:
            from shared.audit.stream_buffer import buffer_audit_event
            await buffer_audit_event(redis=redis_cts, **kwargs)
        except Exception as exc:
            log.error("admin.audit_stream_failed", event_type=kwargs.get("event_type"), error=str(exc))

    return _real


async def _default_notification_publisher(topic: str, payload: dict) -> None:
    log.info("admin.notification_stub", topic=topic, template=payload.get("template_id"))


def get_notification_publisher(request: Request) -> Callable:
    from shared.event_bus.producer import EventProducer as KafkaEventProducer
    producer: Optional[KafkaEventProducer] = getattr(
        request.app.state, "kafka_producer_cts", None
    )
    if producer is None:
        return _default_notification_publisher

    async def _real(topic: str, payload: dict) -> None:
        try:
            await producer.publish(
                topic=topic,
                event_type="NOTIFICATION_REQUEST",
                payload=payload,
                schema_version="1.0",
            )
        except Exception as exc:
            log.error("admin.notification_publish_failed", topic=topic, error=str(exc))

    return _real


# ── Response models ──────────────────────────────────────────────────────────

class ThresholdEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    config_key: str
    current_value: str
    layer: Literal["LAYER_1", "LAYER_2", "LAYER_3"]
    description: str
    last_changed_at: Optional[str] = None
    last_changed_by: Optional[str] = None


class ThresholdsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    thresholds: list[ThresholdEntry]
    total: int
    bank_id: str


class ThresholdChangeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    config_key: str
    new_value: str
    reason: str = Field(..., min_length=10)


class ThresholdChangeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    change_id: str
    config_key: str
    new_value: str
    status: Literal["PENDING_APPROVAL", "APPROVED", "REJECTED"]
    submitted_by: str
    submitted_at: str


class ChangeActionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    change_id: str
    status: Literal["APPROVED", "REJECTED"]
    actioned_by: str
    actioned_at: str


class RejectBody(BaseModel):
    model_config = ConfigDict(frozen=True)
    reason: str = Field(default="No reason provided", min_length=1)


class Layer2ChangeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    config_key: str
    current_value: str
    requested_value: str
    reason: str = Field(..., min_length=10)
    cab_ticket: str


class Layer2ChangeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    request_id: str
    config_key: str
    requested_value: str
    status: Literal["PENDING_ASTRA_REVIEW"]
    submitted_by: str
    submitted_at: str
    cab_ticket: str


class UserSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    role: str
    clearing_zone: Optional[str] = None
    active: bool


class UsersListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    users: list[UserSummary]
    total: int
    bank_id: str


class RoleAssignRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: Literal[
        "ops_reviewer",
        "fraud_analyst",
        "ops_manager",
        "bank_it_admin",
        "compliance_officer",
        "rbi_examiner",
        "ml_engineer",
    ]


class RoleAssignResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    role: str
    assigned_by: str
    assigned_at: str


class ServiceHealthEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    service: str
    status: Literal["HEALTHY", "DEGRADED", "UNKNOWN"]
    details: Optional[str] = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    overall_status: Literal["HEALTHY", "DEGRADED", "UNKNOWN"]
    services: list[ServiceHealthEntry]
    bank_id: str
    checked_at: str


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.get("/config/thresholds", response_model=ThresholdsListResponse)
async def list_thresholds(
    request: Request,
    user: dict = Depends(require_admin_role),
) -> ThresholdsListResponse:
    bank_id = user["bank_id"]
    log.info("admin.list_thresholds", bank_id=bank_id, role=user["role"])

    # Try to overlay live values from the config table; fall back to schema defaults
    # when the DB is unreachable (test / cold-start paths).
    live_values: dict[str, str] = {}
    pool = getattr(request.app.state, "db_pool_platform", None) or getattr(
        request.app.state, "db_pool_cts", None
    )
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT config_key, config_value, updated_at, updated_by
                    FROM platform.config_values
                    WHERE bank_id = $1
                    """,
                    bank_id,
                )
            for r in rows:
                live_values[r["config_key"]] = r["config_value"]
        except Exception:
            log.warning("admin.list_thresholds.db_unavailable", bank_id=bank_id)

    thresholds = [
        ThresholdEntry(
            config_key=s["config_key"],
            current_value=live_values.get(s["config_key"], s["default"]),
            layer=s["layer"],
            description=s["description"],
        )
        for s in _LAYER3_SCHEMA
    ]
    return ThresholdsListResponse(thresholds=thresholds, total=len(thresholds), bank_id=bank_id)


@router_v1.post("/config/thresholds", response_model=ThresholdChangeResponse, status_code=202)
async def submit_threshold_change(
    request: Request,
    body: ThresholdChangeRequest,
    user: dict = Depends(require_maker_role),
    event_publisher: Callable = Depends(get_event_publisher),
    audit_stream_writer: Callable = Depends(get_audit_stream_writer),
    notification_publisher: Callable = Depends(get_notification_publisher),
) -> ThresholdChangeResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]

    _known_keys = {s["config_key"] for s in _LAYER3_SCHEMA}
    _editable_keys = {s["config_key"] for s in _LAYER3_SCHEMA if s["layer"] == "LAYER_3"}
    if body.config_key not in _known_keys:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Unknown config_key: {body.config_key}")
    if body.config_key not in _editable_keys:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"{body.config_key} is a Layer 1 platform constraint and cannot be changed")

    log.info("admin.submit_threshold_change",
             bank_id=bank_id, config_key=body.config_key, submitted_by=user_id)

    change_id = f"chg-{bank_id}-{_secrets.token_hex(8)}"
    now = datetime.now(timezone.utc).isoformat()

    # 1. Write pending change to DB
    pool = getattr(request.app.state, "db_pool_platform", None) or getattr(
        request.app.state, "db_pool_cts", None
    )
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO platform.config_pending_changes
                    (change_id, bank_id, config_key, new_value, reason,
                     status, submitted_by, submitted_at)
                    VALUES ($1, $2, $3, $4, $5, 'PENDING_APPROVAL', $6, NOW())
                    """,
                    change_id, bank_id, body.config_key, body.new_value,
                    body.reason, user_id,
                )
        except Exception:
            log.warning("admin.submit_threshold_change.db_error",
                        bank_id=bank_id, change_id=change_id)

    # 2. Immudb audit — CONFIG_CHANGE, always fires
    await audit_stream_writer(
        event_type=AuditEventType.CONFIG_CHANGE.value,
        bank_id=bank_id,
        payload={
            "action": "SUBMITTED",
            "change_id": change_id,
            "config_key": body.config_key,
            "new_value": body.new_value,
            "reason": body.reason,
            "submitted_by": user_id,
            "submitted_at": now,
        },
    )

    # 3. Notify bank_it_admin (checker) that a change is pending their approval
    await notification_publisher(
        PLATFORM_NOTIFICATIONS,
        {
            "event_type": "NOTIFICATION_REQUEST",
            "template_id": "PLATFORM_CONFIG_CHANGE_SUBMITTED",
            "message_body": get_message(
                "PLATFORM_CONFIG_CHANGE_SUBMITTED",
                submitted_by=user_id,
                config_key=body.config_key,
                new_value=body.new_value,
            ),
            "bank_id": bank_id,
            "recipient_role": "bank_it_admin",
            "context": {
                "change_id": change_id,
                "config_key": body.config_key,
                "new_value": body.new_value,
                "submitted_by": user_id,
            },
        },
    )

    return ThresholdChangeResponse(
        change_id=change_id,
        config_key=body.config_key,
        new_value=body.new_value,
        status="PENDING_APPROVAL",
        submitted_by=user_id,
        submitted_at=now,
    )


@router_v1.post("/config/thresholds/{change_id}/approve", response_model=ChangeActionResponse)
async def approve_threshold_change(
    request: Request,
    change_id: str,
    user: dict = Depends(require_checker_role),
    event_publisher: Callable = Depends(get_event_publisher),
    audit_stream_writer: Callable = Depends(get_audit_stream_writer),
    notification_publisher: Callable = Depends(get_notification_publisher),
) -> ChangeActionResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]
    now = datetime.now(timezone.utc).isoformat()

    log.info("admin.approve_threshold_change",
             bank_id=bank_id, change_id=change_id, approved_by=user_id)

    # 1. DB update — always attempt, 404 if missing
    actioned_at = now
    pool = getattr(request.app.state, "db_pool_platform", None) or getattr(
        request.app.state, "db_pool_cts", None
    )
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    UPDATE platform.config_pending_changes
                    SET status = 'APPROVED', actioned_by = $1, actioned_at = NOW()
                    WHERE change_id = $2 AND bank_id = $3
                      AND status = 'PENDING_APPROVAL'
                      AND submitted_by != $1
                    RETURNING change_id, config_key, new_value, submitted_by, actioned_at
                    """,
                    user_id, change_id, bank_id,
                )
            if result is None:
                # Distinguish self-approval block from not-found — both audited
                conflict = await conn.fetchrow(
                    "SELECT submitted_by FROM platform.config_pending_changes "
                    "WHERE change_id = $1 AND bank_id = $2 AND status = 'PENDING_APPROVAL'",
                    change_id, bank_id,
                )
                if conflict and conflict["submitted_by"] == user_id:
                    await audit_stream_writer(
                        event_type=AuditEventType.CONFIG_CHANGE.value,
                        bank_id=bank_id,
                        payload={"action": "SELF_APPROVAL_BLOCKED", "change_id": change_id,
                                 "attempted_by": user_id},
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Maker cannot approve their own change — four-eyes principle",
                    )
                await audit_stream_writer(
                    event_type=AuditEventType.CONFIG_CHANGE.value,
                    bank_id=bank_id,
                    payload={"action": "APPROVE_NOT_FOUND", "change_id": change_id,
                             "approved_by": user_id},
                )
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail="Change not found or already actioned")
            config_key = result["config_key"]
            new_value = result["new_value"]
            submitted_by = result["submitted_by"]
            actioned_at = str(result["actioned_at"])
        except HTTPException:
            raise
        except Exception:
            log.warning("admin.approve_threshold_change.db_error",
                        bank_id=bank_id, change_id=change_id)
            config_key = "unknown"
            new_value = "unknown"
            submitted_by = "unknown"
    else:
        config_key = "unknown"
        new_value = "unknown"
        submitted_by = "unknown"

    # 2. Immudb audit
    await audit_stream_writer(
        event_type=AuditEventType.CONFIG_CHANGE.value,
        bank_id=bank_id,
        payload={
            "action": "APPROVED",
            "change_id": change_id,
            "config_key": config_key,
            "new_value": new_value,
            "approved_by": user_id,
            "actioned_at": actioned_at,
        },
    )

    # 3. Kafka platform.config.changed → config_service Redis invalidation → 30s hot-reload
    await event_publisher(
        PLATFORM_CONFIG_CHANGED,
        {
            "event_type": "CONFIG_CHANGED",
            "bank_id": bank_id,
            "config_key": config_key,
            "new_value": new_value,
            "changed_by": user_id,
            "change_id": change_id,
            "schema_version": "1.0",
        },
    )

    # 4. Notify maker (ops_manager) that their change is live
    await notification_publisher(
        PLATFORM_NOTIFICATIONS,
        {
            "event_type": "NOTIFICATION_REQUEST",
            "template_id": "PLATFORM_CONFIG_CHANGE_APPROVED",
            "message_body": get_message(
                "PLATFORM_CONFIG_CHANGE_APPROVED",
                approved_by=user_id,
                config_key=config_key,
                new_value=new_value,
            ),
            "bank_id": bank_id,
            "recipient_role": "ops_manager",
            "recipient_user_id": submitted_by,
            "context": {
                "change_id": change_id,
                "config_key": config_key,
                "new_value": new_value,
                "approved_by": user_id,
            },
        },
    )

    return ChangeActionResponse(
        change_id=change_id,
        status="APPROVED",
        actioned_by=user_id,
        actioned_at=actioned_at,
    )


@router_v1.post("/config/thresholds/{change_id}/reject", response_model=ChangeActionResponse)
async def reject_threshold_change(
    request: Request,
    change_id: str,
    body: RejectBody = RejectBody(),
    user: dict = Depends(require_checker_role),
    audit_stream_writer: Callable = Depends(get_audit_stream_writer),
    notification_publisher: Callable = Depends(get_notification_publisher),
) -> ChangeActionResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]
    now = datetime.now(timezone.utc).isoformat()

    log.info("admin.reject_threshold_change",
             bank_id=bank_id, change_id=change_id, rejected_by=user_id)

    actioned_at = now
    submitted_by = "unknown"
    config_key = "unknown"

    pool = getattr(request.app.state, "db_pool_platform", None) or getattr(
        request.app.state, "db_pool_cts", None
    )
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    UPDATE platform.config_pending_changes
                    SET status = 'REJECTED', actioned_by = $1, actioned_at = NOW()
                    WHERE change_id = $2 AND bank_id = $3 AND status = 'PENDING_APPROVAL'
                    RETURNING change_id, config_key, submitted_by, actioned_at
                    """,
                    user_id, change_id, bank_id,
                )
            if result is None:
                await audit_stream_writer(
                    event_type=AuditEventType.CONFIG_CHANGE.value,
                    bank_id=bank_id,
                    payload={"action": "REJECT_NOT_FOUND", "change_id": change_id,
                             "rejected_by": user_id},
                )
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail="Change not found or already actioned")
            config_key = result["config_key"]
            submitted_by = result["submitted_by"]
            actioned_at = str(result["actioned_at"])
        except HTTPException:
            raise
        except Exception:
            log.warning("admin.reject_threshold_change.db_error",
                        bank_id=bank_id, change_id=change_id)

    # Immudb audit
    await audit_stream_writer(
        event_type=AuditEventType.CONFIG_CHANGE.value,
        bank_id=bank_id,
        payload={
            "action": "REJECTED",
            "change_id": change_id,
            "config_key": config_key,
            "rejected_by": user_id,
            "actioned_at": actioned_at,
        },
    )

    # Notify maker (ops_manager) that their change was rejected
    await notification_publisher(
        PLATFORM_NOTIFICATIONS,
        {
            "event_type": "NOTIFICATION_REQUEST",
            "template_id": "PLATFORM_CONFIG_CHANGE_REJECTED",
            "message_body": get_message(
                "PLATFORM_CONFIG_CHANGE_REJECTED",
                rejected_by=user_id,
                config_key=config_key,
                rejection_reason=body.reason,
            ),
            "bank_id": bank_id,
            "recipient_role": "ops_manager",
            "recipient_user_id": submitted_by,
            "context": {
                "change_id": change_id,
                "config_key": config_key,
                "rejected_by": user_id,
                "rejection_reason": body.reason,
            },
        },
    )

    return ChangeActionResponse(
        change_id=change_id,
        status="REJECTED",
        actioned_by=user_id,
        actioned_at=actioned_at,
    )


class ConfigChangeEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    change_id: str
    config_key: str
    old_value: Optional[str] = None
    new_value: str
    reason: str
    status: Literal["PENDING_APPROVAL", "APPROVED", "REJECTED"]
    submitted_by: str
    submitted_at: str
    actioned_by: Optional[str] = None
    actioned_at: Optional[str] = None


class ConfigChangesListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    changes: list[ConfigChangeEntry]
    total: int
    bank_id: str


@router_v1.get("/config/thresholds/changes", response_model=ConfigChangesListResponse)
async def list_threshold_changes(
    request: Request,
    user: dict = Depends(require_admin_role),
    limit: int = Query(default=50, le=100),
) -> ConfigChangesListResponse:
    bank_id = user["bank_id"]
    pool = getattr(request.app.state, "db_pool_platform", None) or getattr(
        request.app.state, "db_pool_cts", None
    )
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT change_id, config_key, new_value, reason, status,
                           submitted_by, submitted_at, actioned_by, actioned_at
                    FROM platform.config_pending_changes
                    WHERE bank_id = $1
                    ORDER BY submitted_at DESC
                    LIMIT $2
                    """,
                    bank_id, limit,
                )
            changes = [
                ConfigChangeEntry(
                    change_id=str(r["change_id"]),
                    config_key=r["config_key"],
                    new_value=r["new_value"],
                    reason=r["reason"],
                    status=r["status"],
                    submitted_by=r["submitted_by"],
                    submitted_at=str(r["submitted_at"]),
                    actioned_by=r.get("actioned_by"),
                    actioned_at=str(r["actioned_at"]) if r.get("actioned_at") else None,
                )
                for r in rows
            ]
            return ConfigChangesListResponse(changes=changes, total=len(changes), bank_id=bank_id)
        except Exception:
            log.warning("admin.list_threshold_changes.db_error", bank_id=bank_id)

    return ConfigChangesListResponse(changes=[], total=0, bank_id=bank_id)


@router_v1.post(
    "/config/platform/change-request",
    response_model=Layer2ChangeResponse,
    status_code=202,
)
async def submit_layer2_change_request(
    request: Request,
    body: Layer2ChangeRequest,
    user: dict = Depends(require_checker_role),
    audit_stream_writer: Callable = Depends(get_audit_stream_writer),
    notification_publisher: Callable = Depends(get_notification_publisher),
) -> Layer2ChangeResponse:
    """
    Bank IT admin raises a Layer 2 configuration change request.
    Layer 2 changes (replicas, connection pool sizes, topology) require a
    Helm upgrade by ASTRA vendor after CAB approval — they are NOT hot-reloaded.
    This endpoint records the request, audits it, and notifies ASTRA support.
    """
    bank_id = user["bank_id"]
    user_id = user["user_id"]
    now = datetime.now(timezone.utc).isoformat()
    request_id = f"l2req-{bank_id}-{_secrets.token_hex(8)}"

    log.info("admin.layer2_change_request",
             bank_id=bank_id, config_key=body.config_key, requested_by=user_id,
             cab_ticket=body.cab_ticket)

    # 1. Write to DB
    pool = getattr(request.app.state, "db_pool_platform", None) or getattr(
        request.app.state, "db_pool_cts", None
    )
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO platform.layer2_change_requests
                    (request_id, bank_id, config_key, current_value, requested_value,
                     reason, cab_ticket, status, submitted_by, submitted_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'PENDING_ASTRA_REVIEW', $8, NOW())
                    """,
                    request_id, bank_id, body.config_key, body.current_value,
                    body.requested_value, body.reason, body.cab_ticket, user_id,
                )
        except Exception:
            log.warning("admin.layer2_change_request.db_error",
                        bank_id=bank_id, request_id=request_id)

    # 2. Immudb audit
    await audit_stream_writer(
        event_type=AuditEventType.CONFIG_L2_CHANGE_REQUESTED.value,
        bank_id=bank_id,
        payload={
            "request_id": request_id,
            "config_key": body.config_key,
            "current_value": body.current_value,
            "requested_value": body.requested_value,
            "reason": body.reason,
            "cab_ticket": body.cab_ticket,
            "submitted_by": user_id,
            "submitted_at": now,
        },
    )

    # 3. Notify ASTRA support + bank_it_admin (self-notification for audit trail)
    await notification_publisher(
        PLATFORM_NOTIFICATIONS,
        {
            "event_type": "NOTIFICATION_REQUEST",
            "template_id": "PLATFORM_CONFIG_L2_REQUESTED",
            "message_body": get_message(
                "PLATFORM_CONFIG_L2_REQUESTED",
                requested_by=user_id,
                config_key=body.config_key,
                current_value=body.current_value,
                requested_value=body.requested_value,
                cab_ticket=body.cab_ticket,
            ),
            "bank_id": bank_id,
            "recipient_role": "astra_support",
            "context": {
                "request_id": request_id,
                "bank_id": bank_id,
                "config_key": body.config_key,
                "current_value": body.current_value,
                "requested_value": body.requested_value,
                "cab_ticket": body.cab_ticket,
                "submitted_by": user_id,
            },
        },
    )

    return Layer2ChangeResponse(
        request_id=request_id,
        config_key=body.config_key,
        requested_value=body.requested_value,
        status="PENDING_ASTRA_REVIEW",
        submitted_by=user_id,
        submitted_at=now,
        cab_ticket=body.cab_ticket,
    )


class Layer2ChangeEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    request_id: str
    config_key: str
    current_value: str
    requested_value: str
    reason: str
    cab_ticket: str
    status: str
    submitted_by: str
    submitted_at: str


class Layer2ChangesListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    requests: list[Layer2ChangeEntry]
    total: int
    bank_id: str


@router_v1.get("/config/platform/change-requests", response_model=Layer2ChangesListResponse)
async def list_layer2_change_requests(
    request: Request,
    user: dict = Depends(require_checker_role),
    limit: int = Query(default=50, le=100),
) -> Layer2ChangesListResponse:
    bank_id = user["bank_id"]
    pool = getattr(request.app.state, "db_pool_platform", None) or getattr(
        request.app.state, "db_pool_cts", None
    )
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT request_id, config_key, current_value, requested_value,
                           reason, cab_ticket, status, submitted_by, submitted_at
                    FROM platform.layer2_change_requests
                    WHERE bank_id = $1
                    ORDER BY submitted_at DESC
                    LIMIT $2
                    """,
                    bank_id, limit,
                )
            reqs = [
                Layer2ChangeEntry(
                    request_id=str(r["request_id"]),
                    config_key=r["config_key"],
                    current_value=r["current_value"],
                    requested_value=r["requested_value"],
                    reason=r["reason"],
                    cab_ticket=r["cab_ticket"],
                    status=r["status"],
                    submitted_by=r["submitted_by"],
                    submitted_at=str(r["submitted_at"]),
                )
                for r in rows
            ]
            return Layer2ChangesListResponse(requests=reqs, total=len(reqs), bank_id=bank_id)
        except Exception:
            log.warning("admin.list_layer2_change_requests.db_error", bank_id=bank_id)

    return Layer2ChangesListResponse(requests=[], total=0, bank_id=bank_id)


@router_v1.get("/users", response_model=UsersListResponse)
async def list_users(
    request: Request,
    user: dict = Depends(require_checker_role),
) -> UsersListResponse:
    bank_id = user["bank_id"]
    log.info("admin.list_users", bank_id=bank_id)

    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT user_id, role, clearing_zones, is_active
                    FROM platform.local_auth_accounts
                    WHERE bank_id = $1
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    bank_id,
                )
            users = [
                UserSummary(
                    user_id=str(r["user_id"]),
                    role=r["role"],
                    clearing_zone=(r["clearing_zones"] or [])[0] if r["clearing_zones"] else None,
                    active=bool(r["is_active"]),
                )
                for r in rows
            ]
            return UsersListResponse(users=users, total=len(users), bank_id=bank_id)
        except Exception:
            log.warning("admin.list_users.db_error", bank_id=bank_id)

    return UsersListResponse(users=[], total=0, bank_id=bank_id)


@router_v1.post("/users/{user_id}/role", response_model=RoleAssignResponse)
async def assign_user_role(
    request: Request,
    user_id: str,
    body: RoleAssignRequest,
    user: dict = Depends(require_checker_role),
) -> RoleAssignResponse:
    bank_id = user["bank_id"]
    admin_id = user["user_id"]

    log.info("admin.assign_role", bank_id=bank_id, target_user=user_id, role=body.role)

    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    UPDATE platform.local_auth_accounts
                    SET role = $1
                    WHERE user_id = $2 AND bank_id = $3
                    RETURNING user_id
                    """,
                    body.role, user_id, bank_id,
                )
            if result:
                return RoleAssignResponse(
                    user_id=user_id,
                    role=body.role,
                    assigned_by=admin_id,
                    assigned_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            log.warning("admin.assign_role.db_error", bank_id=bank_id, user_id=user_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


async def _probe_service(name: str, probe_fn: Any) -> ServiceHealthEntry:
    try:
        await probe_fn()
        return ServiceHealthEntry(service=name, status="HEALTHY")
    except Exception as exc:
        return ServiceHealthEntry(service=name, status="DEGRADED", details=str(exc)[:120])


@router_v1.get("/health", response_model=HealthResponse)
async def get_infra_health(
    request: Request,
    user: dict = Depends(require_checker_role),
) -> HealthResponse:
    bank_id = user["bank_id"]
    log.info("admin.infra_health", bank_id=bank_id)

    services: list[ServiceHealthEntry] = []

    pool_cts = getattr(request.app.state, "db_pool_cts", None)
    if pool_cts is not None:
        async def _probe_db():
            async with pool_cts.acquire() as conn:
                await conn.fetchval("SELECT 1")
        services.append(await _probe_service("yugabyte", _probe_db))
    else:
        services.append(ServiceHealthEntry(service="yugabyte", status="UNKNOWN"))

    redis_cts = getattr(request.app.state, "redis_cts", None)
    if redis_cts is not None:
        async def _probe_redis_cts():
            await redis_cts.ping()
        services.append(await _probe_service("redis-cts", _probe_redis_cts))
    else:
        services.append(ServiceHealthEntry(service="redis-cts", status="UNKNOWN"))

    services.append(ServiceHealthEntry(service="redis-ej", status="UNKNOWN"))
    services.append(ServiceHealthEntry(service="kafka", status="UNKNOWN"))
    services.append(ServiceHealthEntry(service="temporal", status="UNKNOWN"))
    services.append(ServiceHealthEntry(service="vault", status="UNKNOWN"))
    services.append(ServiceHealthEntry(service="immudb", status="UNKNOWN"))

    known = [s for s in services if s.status != "UNKNOWN"]
    overall = (
        "DEGRADED" if any(s.status == "DEGRADED" for s in known)
        else "HEALTHY" if known
        else "UNKNOWN"
    )

    return HealthResponse(
        overall_status=overall,
        services=services,
        bank_id=bank_id,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Security violations ───────────────────────────────────────────────────────

class SecurityViolationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    timestamp_iso: str
    violation_type: str
    suspended: bool
    user_id: str
    bank_id: str
    bank_type: str
    role: str
    endpoint: str
    method: str
    client_ip: str
    incident_id: Optional[str] = None
    request_id: Optional[str] = None


class SecurityViolationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    violations: list[SecurityViolationEvent]
    total: int
    suspended_count: int
    bank_id: str


@router_v1.get("/security-violations", response_model=SecurityViolationsResponse)
async def list_security_violations(
    limit: int = Query(default=50, le=100),
    user: dict = Depends(require_checker_role),
) -> SecurityViolationsResponse:
    """
    Returns recent security violation events visible to this bank's IT admin.
    Only bank_it_admin may call this endpoint (require_checker_role).
    SB admin sees all violations where sb_bank_id matches their bank_id.
    """
    from apps.api.middleware.security_violations import violation_store, suspension_store

    bank_id = user["bank_id"]
    raw = violation_store.get_for_bank(sb_bank_id=bank_id, limit=limit)

    # Also include violations where the violating bank_id is this bank (SB seeing own users)
    own = [e for e in violation_store.get_all(limit=500) if e.get("bank_id") == bank_id]
    merged = {e["id"]: e for e in [*raw, *own]}.values()
    events = sorted(merged, key=lambda e: e.get("timestamp", 0), reverse=True)[:limit]

    violations = [
        SecurityViolationEvent(
            id=e["id"],
            timestamp_iso=e.get("timestamp_iso", ""),
            violation_type=e.get("violation_type", ""),
            suspended=e.get("suspended", False),
            user_id=e.get("user_id", ""),
            bank_id=e.get("bank_id", ""),
            bank_type=e.get("bank_type", ""),
            role=e.get("role", ""),
            endpoint=e.get("endpoint", ""),
            method=e.get("method", ""),
            client_ip=e.get("client_ip", ""),
            request_id=e.get("request_id"),
        )
        for e in events
    ]

    return SecurityViolationsResponse(
        violations=violations,
        total=len(violations),
        suspended_count=len(suspension_store.all_suspended()),
        bank_id=bank_id,
    )


# ---------------------------------------------------------------------------
# Vault management dependencies (injectable for testing)
# ---------------------------------------------------------------------------

async def get_vault_db_pool():
    """Returns the CTS DB pool. Overridden in tests."""
    from shared.config.config_service import config_service
    import asyncpg
    dsn = config_service.get("db.cts.dsn")
    return await asyncpg.create_pool(dsn, min_size=1, max_size=3)


def get_vault_redis():
    """Returns the CTS Redis client. Overridden in tests."""
    from shared.config.config_service import config_service
    import redis as _redis
    return _redis.Redis.from_url(config_service.get("redis.cts.url"))


def get_vault_warm_trigger():
    """Returns an async callable that triggers warm_redis_from_db. Overridden in tests."""
    async def _trigger(bank_id: str) -> dict:
        from temporalio.client import Client
        from modules.cts.workflows.vault_sync_workflow import warm_redis_from_db
        from shared.config.config_service import config_service
        from datetime import datetime, timezone

        temporal_url = config_service.get("temporal.server_url")
        client = await Client.connect(temporal_url)
        workflow_id = f"cts-warmredis-{bank_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        await client.execute_workflow(
            "WarmRedisRecoveryWorkflow",
            args=[bank_id],
            id=workflow_id,
            task_queue=f"cts-processing-{bank_id}",
        )
        return {"workflow_id": workflow_id, "status": "TRIGGERED"}

    return _trigger


# ---------------------------------------------------------------------------
# Vault response models
# ---------------------------------------------------------------------------

class VaultSigSyncStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    yugabyte_accounts: int
    yugabyte_specimens: int
    redis_sig_keys: int
    coverage_pct: float
    gap_accounts: int
    last_sync_at: Optional[str] = None
    request_id: str


class VaultWarmRedisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    status: str
    triggered_at: str
    request_id: str


# ---------------------------------------------------------------------------
# GET /v1/admin/vault/sig-sync-status
# ---------------------------------------------------------------------------

@router_v1.get("/vault/sig-sync-status", response_model=VaultSigSyncStatusResponse)
async def get_vault_sig_sync_status(
    request: Request,
    user: dict = Depends(require_admin_role),
    db_pool=Depends(get_vault_db_pool),
    redis_client=Depends(get_vault_redis),
) -> VaultSigSyncStatusResponse:
    """
    Returns the current sync state of the signature vault:
      - How many distinct accounts are stored in YugabyteDB (durable)
      - How many signature keys are in Redis (hot cache)
      - Coverage percentage and gap count

    Accessible by both bank_it_admin and ops_manager.
    Use gap_accounts > 0 as the trigger signal for POST /vault/warm-redis.
    """
    bank_id = user["bank_id"]
    request_id = request.headers.get("X-Request-Id", _secrets.token_hex(8))

    # YugabyteDB counts
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(DISTINCT account_hash) AS accounts,
                COUNT(*)                     AS specimens
            FROM cts.signature_embeddings
            WHERE bank_id = $1
            """,
            bank_id,
        )
        last_sync_at_row = await conn.fetchval(
            """
            SELECT MAX(updated_at) FROM cts.signature_embeddings WHERE bank_id = $1
            """,
            bank_id,
        )

    yugabyte_accounts = int(row["accounts"] or 0)
    yugabyte_specimens = int(row["specimens"] or 0)
    last_sync_at = last_sync_at_row.isoformat() if last_sync_at_row else None

    # Redis key count — scan for sig:{bank_id}:* keys only
    redis_sig_keys = sum(1 for _ in redis_client.scan_iter(match=f"sig:{bank_id}:*", count=1000))

    coverage_pct = round(
        min(100.0, (redis_sig_keys / yugabyte_accounts * 100)) if yugabyte_accounts > 0 else 100.0,
        2,
    )
    gap_accounts = max(0, yugabyte_accounts - redis_sig_keys)

    log.info(
        "admin.vault_sync_status_queried",
        bank_id=bank_id,
        yugabyte_accounts=yugabyte_accounts,
        redis_sig_keys=redis_sig_keys,
        coverage_pct=coverage_pct,
    )

    return VaultSigSyncStatusResponse(
        yugabyte_accounts=yugabyte_accounts,
        yugabyte_specimens=yugabyte_specimens,
        redis_sig_keys=redis_sig_keys,
        coverage_pct=coverage_pct,
        gap_accounts=gap_accounts,
        last_sync_at=last_sync_at,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# POST /v1/admin/vault/warm-redis
# ---------------------------------------------------------------------------

@router_v1.post("/vault/warm-redis", response_model=VaultWarmRedisResponse, status_code=202)
async def trigger_vault_warm_redis(
    request: Request,
    user: dict = Depends(require_maker_role),
    trigger_fn=Depends(get_vault_warm_trigger),
) -> VaultWarmRedisResponse:
    """
    Triggers warm_redis_from_db: reads cts.signature_embeddings from YugabyteDB
    and pipeline-writes packed float32 embeddings into Redis.

    Use after a Redis cold restart when sig-sync-status shows gap_accounts > 0.
    Returns immediately with a workflow_id — warm runs asynchronously.

    Accessible by ops_manager only (maker action).
    """
    bank_id = user["bank_id"]
    request_id = request.headers.get("X-Request-Id", _secrets.token_hex(8))

    result = await trigger_fn(bank_id)

    log.info(
        "admin.vault_warm_redis_triggered",
        bank_id=bank_id,
        workflow_id=result["workflow_id"],
        triggered_by=user["user_id"],
    )

    return VaultWarmRedisResponse(
        workflow_id=result["workflow_id"],
        status=result["status"],
        triggered_at=datetime.now(timezone.utc).isoformat(),
        request_id=request_id,
    )


@router_v1.post("/security-violations/{user_id}/reinstate", response_model=dict)
async def reinstate_user(
    user_id: str,
    user: dict = Depends(require_checker_role),
) -> dict:
    """
    bank_it_admin reinstates a suspended user. Requires a change-management justification
    in production (audit trail). Here we record the action and clear the suspension.
    """
    from apps.api.middleware.security_violations import suspension_store
    suspension_store.reinstate(user_id)
    log.info("admin.user_reinstated", target_user=user_id, admin_id=user["user_id"], bank_id=user["bank_id"])
    return {"reinstated": True, "user_id": user_id}
