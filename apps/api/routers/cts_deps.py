"""
Shared FastAPI dependencies for all CTS router files.

Every cts_*.py router imports from here — never re-defines these.
Adding a new shared dep: add it here, import it in the relevant router(s).
"""
import hashlib
import re
from typing import Optional

import structlog
from fastapi import Depends, Header, HTTPException, Request, status

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext
from shared.event_bus.producer import EventProducer as KafkaEventProducer

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Temporal param safety
# ---------------------------------------------------------------------------

_TEMPORAL_PARAM_RE = re.compile(r'^[a-zA-Z0-9\-_]{1,64}$')


def _safe_temporal_param(value: str, field: str) -> str:
    """Reject bank_id / smb_id values that could inject into a Temporal visibility query."""
    if not _TEMPORAL_PARAM_RE.match(value):
        raise ValueError(
            f"Invalid {field} for Temporal query: "
            "must be alphanumeric + hyphens/underscores, max 64 chars"
        )
    return value


# ---------------------------------------------------------------------------
# SQL row caps — named constants so the intent is explicit and auditable
# ---------------------------------------------------------------------------

_VAULT_GAP_MAX_ROWS    = 2000   # post-hours vault-gap report; groups by account_last4
_SCAN_LOG_MAX_ROWS     = 500    # per-session outward scan event log
_ANALYTICS_TOP_N       = 10    # top-N IFSC analytics (intentional, not paginated)
_SMB_REPORTS_MAX_ROWS  = 500    # per-SMB daily aggregate report
_COMPLIANCE_MAX_ROWS   = 500    # outward CTS-2010 compliance checks per clearing day
_NGCH_ROUTING_MAX_ROWS = 500    # NGCH routing rules per bank
_MICR_PREFIX_MAX_ROWS  = 1000   # MICR prefix routing table


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------

async def get_current_user_context(
    request: Request,
    ctx: UserContext = Depends(require_user_context),
) -> UserContext:
    """
    The central auth chokepoint (apps.api.dependencies) plus the user's CURRENT access.

    The session carries the processing units and branches the user had at sign-in. An admin who narrows them, or disables the
    account, must take effect on the very next request, not when the session refreshes, so for locally managed accounts the
    scope and the active flag are read from the database here. Users who sign in through an identity provider have no local
    row and keep the scope their provider gave them. If the lookup itself fails the session's scope is used (a database
    blip must not lock every reviewer out) and a warning is logged. No token parsing here. ASTRA-01.
    """
    state = request.app.state
    pool = getattr(state, "db_pool_platform", None) or getattr(state, "db_pool_cts", None)
    if pool is None:
        return ctx
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT pu_ids, branch_ids, is_active FROM platform.local_auth_accounts WHERE user_id = $1 AND bank_id = $2",
                ctx.user_id, ctx.bank_id,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("cts.live_scope.lookup_failed", user_id=ctx.user_id, error=str(exc))
        return ctx
    if row is None:
        return ctx
    try:
        active, pu_ids, branch_ids = row["is_active"], list(row["pu_ids"] or []), list(row["branch_ids"] or [])
    except (KeyError, IndexError, TypeError):      # not an account row: treat as a failed lookup, never as a reason to fail the request
        log.warning("cts.live_scope.unexpected_row", user_id=ctx.user_id)
        return ctx
    if not active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been disabled")
    return ctx.model_copy(update={"pu_ids": pu_ids, "branch_ids": branch_ids})


async def get_current_bank_id(
    ctx: UserContext = Depends(get_current_user_context),
) -> str:
    return ctx.bank_id


async def get_bank_id_scanner_or_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> str:
    """Accept scanner machine bearer token OR user session cookie.

    The edge scanner agent (edge/cts-scanner-agent/) authenticates with a
    machine bearer token stored in token.dat — it has no user session. This
    dependency lets scanner-facing endpoints accept both auth methods.

    Priority: scanner machine token first → user session fallback.
    """
    if authorization and authorization.startswith("Bearer "):
        incoming_token = authorization[7:].strip()
        incoming_hash = hashlib.sha256(incoming_token.encode()).hexdigest()
        db_pool = getattr(request.app.state, "db_pool_cts", None)
        if db_pool is not None:
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT bank_id FROM cts.scanner_tokens "
                        "WHERE token_hash = $1 AND revoked = false",
                        incoming_hash,
                    )
                if row is not None:
                    log.info("cts.scanner_auth.ok", bank_id=row["bank_id"])
                    return row["bank_id"]
            except Exception as exc:
                log.warning("cts.scanner_auth.db_error", error=str(exc))
    # Fallback: require a valid browser session
    from apps.api.dependencies import require_user_context as _require_ctx
    ctx: UserContext = _require_ctx(request)
    return ctx.bank_id


async def get_current_user_id(
    ctx: UserContext = Depends(get_current_user_context),
) -> str:
    return ctx.user_id


# ---------------------------------------------------------------------------
# Infrastructure dependencies
# ---------------------------------------------------------------------------

def get_temporal_client(request: Request):
    """Retrieve the Temporal client stored on app state at startup."""
    client = getattr(request.app.state, "temporal_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow engine unavailable",
        )
    return client


def get_kafka_producer(request: Request) -> Optional[KafkaEventProducer]:
    """Return Kafka producer from app state, or None in test/dev mode."""
    return getattr(request.app.state, "kafka_producer", None)


def get_db_pool_cts(request: Request):
    """Return the CTS YugabyteDB connection pool from app state, or None in dev/test."""
    return getattr(request.app.state, "db_pool_cts", None)
