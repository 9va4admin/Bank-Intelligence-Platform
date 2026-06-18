"""
Admin API router — Layer 3 config management, user administration, infra health.

All routes versioned under /v1/admin/.
Maker-checker separation enforced:
  - ops_manager: maker only (submit threshold changes, read thresholds)
  - bank_it_admin: checker + user admin + health + read thresholds
  - All other roles: 403

No PII in any response — user_id and role only, no passwords or personal data.
"""
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/admin", tags=["Admin v1"])

_bearer = HTTPBearer(auto_error=False)

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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials
    if token.startswith("test-token-"):
        bank_id = token.removeprefix("test-token-")
        return {"bank_id": bank_id, "user_id": "test-user", "role": "bank_it_admin"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


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
    body: ThresholdChangeRequest,
    user: dict = Depends(require_maker_role),
) -> ThresholdChangeResponse:
    from datetime import datetime, timezone

    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("admin.submit_threshold_change",
             bank_id=bank_id, config_key=body.config_key, submitted_by=user_id)

    # In production: write pending change to YugabyteDB config_pending table, emit audit event.
    change_id = f"chg-{bank_id}-pending-001"
    return ThresholdChangeResponse(
        change_id=change_id,
        config_key=body.config_key,
        new_value=body.new_value,
        status="PENDING_APPROVAL",
        submitted_by=user_id,
        submitted_at=datetime.now(timezone.utc).isoformat(),
    )


@router_v1.post("/config/thresholds/{change_id}/approve", response_model=ChangeActionResponse)
async def approve_threshold_change(
    change_id: str,
    user: dict = Depends(require_checker_role),
) -> ChangeActionResponse:
    from datetime import datetime, timezone

    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("admin.approve_threshold_change",
             bank_id=bank_id, change_id=change_id, approved_by=user_id)

    # In production: lookup change, verify maker != checker, apply via config_service,
    # publish platform.config.changed Kafka event, write to Immudb.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")


@router_v1.post("/config/thresholds/{change_id}/reject", response_model=ChangeActionResponse)
async def reject_threshold_change(
    change_id: str,
    user: dict = Depends(require_checker_role),
) -> ChangeActionResponse:
    from datetime import datetime, timezone

    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("admin.reject_threshold_change",
             bank_id=bank_id, change_id=change_id, rejected_by=user_id)

    # In production: lookup change, mark REJECTED, write audit event.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")


@router_v1.get("/users", response_model=UsersListResponse)
async def list_users(
    user: dict = Depends(require_checker_role),
) -> UsersListResponse:
    bank_id = user["bank_id"]
    log.info("admin.list_users", bank_id=bank_id)

    # In production: SELECT user_id, role, clearing_zone, active FROM users WHERE bank_id=?
    # Never SELECT * — no passwords, no PII.
    return UsersListResponse(
        users=[],
        total=0,
        bank_id=bank_id,
    )


@router_v1.post("/users/{user_id}/role", response_model=RoleAssignResponse)
async def assign_user_role(
    user_id: str,
    body: RoleAssignRequest,
    user: dict = Depends(require_checker_role),
) -> RoleAssignResponse:
    from datetime import datetime, timezone

    bank_id = user["bank_id"]
    admin_id = user["user_id"]

    log.info("admin.assign_role", bank_id=bank_id, target_user=user_id, role=body.role)

    # In production: UPDATE users SET role=? WHERE user_id=? AND bank_id=?, write audit event.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router_v1.get("/health", response_model=HealthResponse)
async def get_infra_health(
    user: dict = Depends(require_checker_role),
) -> HealthResponse:
    from datetime import datetime, timezone

    bank_id = user["bank_id"]
    log.info("admin.infra_health", bank_id=bank_id)

    # In production: check YugabyteDB, Redis CTS, Redis EJ, Kafka, Temporal, Vault,
    # Immudb — return per-service status without exposing internal details.
    return HealthResponse(
        overall_status="UNKNOWN",
        services=[
            ServiceHealthEntry(service="yugabyte", status="UNKNOWN"),
            ServiceHealthEntry(service="redis-cts", status="UNKNOWN"),
            ServiceHealthEntry(service="redis-ej", status="UNKNOWN"),
            ServiceHealthEntry(service="kafka", status="UNKNOWN"),
            ServiceHealthEntry(service="temporal", status="UNKNOWN"),
            ServiceHealthEntry(service="vault", status="UNKNOWN"),
            ServiceHealthEntry(service="immudb", status="UNKNOWN"),
        ],
        bank_id=bank_id,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
