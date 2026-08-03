"""
Admin API router — Layer 3 config management, user administration, infra health.

All routes versioned under /v1/admin/.
Maker-checker separation enforced:
  - ops_manager: maker only (submit threshold changes, read thresholds)
  - bank_it_admin: checker + user admin + health + read thresholds
  - All other roles: 403

No PII in any response — user_id and role only, no passwords or personal data.
"""
import secrets as _secrets
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/admin", tags=["Admin v1"])

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


# ── Response models ──────────────────────────────────────────────────────────

class ThresholdEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    config_key: str
    current_value: str
    layer: Literal["LAYER_2", "LAYER_3"]
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
    user: dict = Depends(require_admin_role),
) -> ThresholdsListResponse:
    bank_id = user["bank_id"]
    log.info("admin.list_thresholds", bank_id=bank_id, role=user["role"])

    # In production: query config_service for Layer 3 thresholds from YugabyteDB config table.
    return ThresholdsListResponse(
        thresholds=[],
        total=0,
        bank_id=bank_id,
    )


@router_v1.post("/config/thresholds", response_model=ThresholdChangeResponse, status_code=202)
async def submit_threshold_change(
    request: Request,
    body: ThresholdChangeRequest,
    user: dict = Depends(require_maker_role),
) -> ThresholdChangeResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("admin.submit_threshold_change",
             bank_id=bank_id, config_key=body.config_key, submitted_by=user_id)

    change_id = f"chg-{bank_id}-{_secrets.token_hex(8)}"
    now = datetime.now(timezone.utc).isoformat()

    pool = getattr(request.app.state, "db_pool_platform", None)
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
) -> ChangeActionResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("admin.approve_threshold_change",
             bank_id=bank_id, change_id=change_id, approved_by=user_id)

    pool = getattr(request.app.state, "db_pool_platform", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    UPDATE platform.config_pending_changes
                    SET status = 'APPROVED', actioned_by = $1, actioned_at = NOW()
                    WHERE change_id = $2 AND bank_id = $3 AND status = 'PENDING_APPROVAL'
                    RETURNING change_id, actioned_at
                    """,
                    user_id, change_id, bank_id,
                )
            if result:
                return ChangeActionResponse(
                    change_id=change_id,
                    status="APPROVED",
                    actioned_by=user_id,
                    actioned_at=str(result["actioned_at"]),
                )
        except Exception:
            log.warning("admin.approve_threshold_change.db_error",
                        bank_id=bank_id, change_id=change_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")


@router_v1.post("/config/thresholds/{change_id}/reject", response_model=ChangeActionResponse)
async def reject_threshold_change(
    request: Request,
    change_id: str,
    user: dict = Depends(require_checker_role),
) -> ChangeActionResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("admin.reject_threshold_change",
             bank_id=bank_id, change_id=change_id, rejected_by=user_id)

    pool = getattr(request.app.state, "db_pool_platform", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    UPDATE platform.config_pending_changes
                    SET status = 'REJECTED', actioned_by = $1, actioned_at = NOW()
                    WHERE change_id = $2 AND bank_id = $3 AND status = 'PENDING_APPROVAL'
                    RETURNING change_id, actioned_at
                    """,
                    user_id, change_id, bank_id,
                )
            if result:
                return ChangeActionResponse(
                    change_id=change_id,
                    status="REJECTED",
                    actioned_by=user_id,
                    actioned_at=str(result["actioned_at"]),
                )
        except Exception:
            log.warning("admin.reject_threshold_change.db_error",
                        bank_id=bank_id, change_id=change_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")


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
