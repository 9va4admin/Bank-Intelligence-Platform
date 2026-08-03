"""
Security violation middleware.

When a request raises TenantIsolationError, BankIsolationError, or AccessDeniedError
(all subclasses of PermissionError from shared/auth/exceptions.py) the middleware:

  1. Records the violation in the in-process ViolationStore (module-level list — survives
     request lifetime, cleared on pod restart, replaced by a real DB/Kafka sink in prod).
  2. Marks the violating user as suspended in the SuspensionStore.
  3. Returns HTTP 403 with error_code SECURITY_VIOLATION and a safe message.

Production extension points (annotated, not implemented here):
  - Replace ViolationStore._events with a Kafka publish to platform.notifications
  - Replace SuspensionStore._suspended with a YugabyteDB UPDATE users SET suspended = true
  - The GET /v1/admin/security-violations endpoint reads from ViolationStore
"""
import asyncio
import json
import time
import uuid
from collections import deque
from typing import Optional

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.auth.exceptions import (
    AccessDeniedError,
    BankIsolationError,
    EngagementExpiredError,
    TenantIsolationError,
)
from shared.event_bus.topics import PLATFORM_NOTIFICATIONS

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# In-process stores (replaced by DB/Kafka in production)
# --------------------------------------------------------------------------- #

class ViolationStore:
    """Thread-safe ring buffer of recent security violation events."""

    def __init__(self, maxlen: int = 500):
        self._events: deque = deque(maxlen=maxlen)

    def record(self, event: dict) -> None:
        self._events.appendleft(event)

    def get_all(self, limit: int = 100) -> list[dict]:
        return list(self._events)[:limit]

    def get_for_bank(self, sb_bank_id: str, limit: int = 100) -> list[dict]:
        return [e for e in self._events if e.get("sb_bank_id") == sb_bank_id][:limit]


class SuspensionStore:
    """Tracks suspended user IDs. In production: YugabyteDB users.suspended column."""

    def __init__(self):
        self._suspended: set[str] = set()

    def suspend(self, user_id: str) -> None:
        self._suspended.add(user_id)

    def is_suspended(self, user_id: str) -> bool:
        return user_id in self._suspended

    def reinstate(self, user_id: str) -> None:
        self._suspended.discard(user_id)

    def all_suspended(self) -> list[str]:
        return list(self._suspended)


# Module-level singletons — shared across all requests in this process
violation_store = ViolationStore()
suspension_store = SuspensionStore()

# Violation types that trigger immediate account suspension
_SUSPENSION_ERRORS = (TenantIsolationError, BankIsolationError)

# Violation types that are recorded but do not auto-suspend (legitimate expired engagement)
_RECORD_ONLY_ERRORS = (AccessDeniedError, EngagementExpiredError)


# --------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------- #

class SecurityViolationMiddleware(BaseHTTPMiddleware):
    """
    Catches all security exceptions that escape route handlers and:
      - Records the event with full context (user, bank, endpoint, IP)
      - Suspends the user immediately for TenantIsolationError / BankIsolationError
      - Returns a standardised 403 JSON response
    """

    async def dispatch(self, request: Request, call_next):
        # Check if the user is already suspended (extracted from request state if set
        # by auth dependency — otherwise skip, auth will 401 first)
        user_ctx: Optional[object] = getattr(request.state, "user_context", None)
        if user_ctx and suspension_store.is_suspended(user_ctx.user_id):
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "ACCOUNT_SUSPENDED",
                    "message": "Your account has been suspended due to a security violation. "
                               "Contact your bank IT administrator.",
                    "request_id": request.headers.get("X-Request-Id", str(uuid.uuid4())),
                },
            )

        try:
            response = await call_next(request)
            return response

        except (*_SUSPENSION_ERRORS, *_RECORD_ONLY_ERRORS) as exc:
            return await self._handle_violation(request, exc)

        except Exception:
            # Let FastAPI's default exception handler deal with everything else
            raise

    async def _handle_violation(self, request: Request, exc: Exception) -> JSONResponse:
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        user_ctx = getattr(request.state, "user_context", None)
        user_id  = user_ctx.user_id  if user_ctx else "unknown"
        bank_id  = user_ctx.bank_id  if user_ctx else "unknown"
        bank_type = str(user_ctx.bank_type.value) if user_ctx else "unknown"
        role     = str(user_ctx.role.value) if user_ctx else "unknown"

        is_suspension_event = isinstance(exc, _SUSPENSION_ERRORS)
        violation_type = type(exc).__name__

        event = {
            "id":             str(uuid.uuid4()),
            "timestamp":      time.time(),
            "timestamp_iso":  _iso_now(),
            "violation_type": violation_type,
            "suspended":      is_suspension_event,
            "user_id":        user_id,
            "bank_id":        bank_id,
            "bank_type":      bank_type,
            "role":           role,
            # SB that needs to see this notification (the attacker's sponsor bank for SMB,
            # or the same bank for SB users attempting cross-bank access)
            "sb_bank_id":     _resolve_sb_bank_id(user_ctx),
            "endpoint":       str(request.url.path),
            "method":         request.method,
            "client_ip":      request.client.host if request.client else "unknown",
            "detail":         str(exc),
            "request_id":     request_id,
        }

        violation_store.record(event)

        if is_suspension_event:
            suspension_store.suspend(user_id)
            log.critical(
                "security.isolation_violation.account_suspended",
                user_id=user_id,
                bank_id=bank_id,
                violation_type=violation_type,
                endpoint=event["endpoint"],
                request_id=request_id,
            )
        else:
            log.warning(
                "security.access_denied",
                user_id=user_id,
                bank_id=bank_id,
                violation_type=violation_type,
                endpoint=event["endpoint"],
                request_id=request_id,
            )

        # Publish to platform.notifications so bank_it_admin receives WhatsApp/email alert.
        await self._publish_violation_alert(request, event, is_suspension_event)

        error_code = "SECURITY_VIOLATION" if is_suspension_event else "ACCESS_DENIED"
        message = (
            "Cross-bank data access detected. Your account has been suspended immediately. "
            "This incident has been reported to your bank administrator."
            if is_suspension_event else
            "Access denied. You do not have permission to perform this operation."
        )

        return JSONResponse(
            status_code=403,
            content={
                "error_code": error_code,
                "message": message,
                "incident_id": event["id"],
                "request_id": request_id,
            },
        )


    async def _publish_violation_alert(
        self,
        request: Request,
        event: dict,
        is_suspension: bool,
    ) -> None:
        """
        Fire-and-forget: publish a security violation notification to Kafka and
        persist the event to YugabyteDB (platform.security_violations).
        Never raises — violation handling must never fail silently just because
        the Kafka producer or DB pool is unavailable.
        """
        # 1. Kafka publish → platform.notifications topic
        producer = getattr(request.app.state, "kafka_producer", None)
        if producer is not None:
            try:
                notification = {
                    "notification_id": event["id"],
                    "bank_id": event["bank_id"],
                    "sb_bank_id": event["sb_bank_id"],
                    "channel": "whatsapp",
                    "template_id": (
                        "security.isolation_violation" if is_suspension
                        else "security.access_denied"
                    ),
                    "priority": "P0" if is_suspension else "P1",
                    "recipient_role": "bank_it_admin",
                    "context": {
                        "violation_type": event["violation_type"],
                        "user_id": event["user_id"],
                        "endpoint": event["endpoint"],
                        "incident_id": event["id"],
                        "suspended": is_suspension,
                    },
                    "schema_version": "1.0",
                }
                await producer.send_and_wait(
                    PLATFORM_NOTIFICATIONS,
                    value=json.dumps(notification).encode(),
                    key=event["id"].encode(),
                )
            except Exception as exc:
                log.warning("security.alert.kafka_failed", incident_id=event["id"], error=str(exc))

        # 2. YugabyteDB persist — platform.security_violations table
        pool = getattr(request.app.state, "db_pool_platform", None)
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO platform.security_violations (
                            violation_id, bank_id, sb_bank_id, user_id, role,
                            bank_type, violation_type, suspended, endpoint, method,
                            client_ip, detail, request_id, occurred_at
                        ) VALUES (
                            $1, $2, $3, $4, $5,
                            $6, $7, $8, $9, $10,
                            $11, $12, $13, NOW()
                        )
                        ON CONFLICT (violation_id) DO NOTHING
                        """,
                        event["id"],
                        event["bank_id"],
                        event["sb_bank_id"],
                        event["user_id"],
                        event["role"],
                        event["bank_type"],
                        event["violation_type"],
                        event["suspended"],
                        event["endpoint"],
                        event["method"],
                        event["client_ip"],
                        event["detail"][:512],
                        event["request_id"],
                    )
            except Exception as exc:
                log.warning("security.alert.db_failed", incident_id=event["id"], error=str(exc))


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_sb_bank_id(user_ctx) -> str:
    """
    Identifies which SB admin should receive this security alert.
    - If the violating user is SMB: their sponsor bank (SB) should be notified.
    - If the violating user is SB: the same bank's IT admin should be notified.
    - Unknown context: empty string.
    """
    if user_ctx is None:
        return ""
    try:
        from shared.auth.rbac import BankType
        if user_ctx.bank_type == BankType.SMB:
            # In production: look up sponsor_bank_id from YugabyteDB banks table.
            # For now, return a sentinel that the notification consumer resolves.
            return f"sponsor-of:{user_ctx.bank_id}"
        return user_ctx.bank_id
    except Exception:
        return ""
