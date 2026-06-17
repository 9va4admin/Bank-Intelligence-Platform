"""
RBAC + ABAC — Role-Based Access Control with Attribute-Based extensions.

Every API route and PII decryption call must go through this module.
Never hard-code role checks in route handlers — always use has_permission()
or RBACPolicy.assert_permission() via FastAPI dependency injection.

Role → Permission mapping implements the table from CLAUDE.md section 6.
ABAC rules:
  - ops_reviewer: further scoped to clearing_zone attribute
  - all roles: scoped to bank_id (BankIsolationError on cross-bank access)
  - rbi_examiner: time-limited per engagement (EngagementExpiredError on expiry)
"""
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.auth.exceptions import (
    AccessDeniedError,
    BankIsolationError,
    EngagementExpiredError,
    InsufficientZoneScopeError,
)


class Role(str, Enum):
    OPS_REVIEWER = "ops_reviewer"
    FRAUD_ANALYST = "fraud_analyst"
    OPS_MANAGER = "ops_manager"
    BANK_IT_ADMIN = "bank_it_admin"
    COMPLIANCE_OFFICER = "compliance_officer"
    RBI_EXAMINER = "rbi_examiner"
    ML_ENGINEER = "ml_engineer"


class Permission(str, Enum):
    # CTS operations
    CTS_VIEW_QUEUE = "cts:view_queue"
    CTS_SUBMIT_DECISION = "cts:submit_decision"
    CTS_VIEW_ANALYTICS = "cts:view_analytics"

    # EJ operations
    EJ_VIEW_DASHBOARD = "ej:view_dashboard"
    EJ_VIEW_DISPUTES = "ej:view_disputes"

    # PII — gates column-level decryption
    VIEW_PII = "pii:view"

    # Config changes
    CONFIG_LAYER3_SUBMIT = "config:layer3:submit"   # maker
    CONFIG_LAYER3_APPROVE = "config:layer3:approve"  # checker
    CONFIG_LAYER2_CHANGE = "config:layer2:change"    # bank_it_admin via PR

    # Audit trail
    AUDIT_READ = "audit:read"

    # AI / MLflow
    AI_MODEL_METRICS = "ai:model_metrics"
    AI_MLFLOW_ACCESS = "ai:mlflow_access"

    # Admin
    ADMIN_CONSOLE = "admin:console"


# Permission matrix: role → set of granted permissions
_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OPS_REVIEWER: frozenset({
        Permission.CTS_VIEW_QUEUE,
        Permission.CTS_SUBMIT_DECISION,
    }),
    Role.FRAUD_ANALYST: frozenset({
        Permission.CTS_VIEW_ANALYTICS,
        Permission.EJ_VIEW_DASHBOARD,
        Permission.EJ_VIEW_DISPUTES,
    }),
    Role.OPS_MANAGER: frozenset({
        Permission.CTS_VIEW_QUEUE,
        Permission.CTS_SUBMIT_DECISION,
        Permission.CTS_VIEW_ANALYTICS,
        Permission.EJ_VIEW_DASHBOARD,
        Permission.EJ_VIEW_DISPUTES,
        Permission.VIEW_PII,
        Permission.CONFIG_LAYER3_SUBMIT,
        Permission.AUDIT_READ,
    }),
    Role.BANK_IT_ADMIN: frozenset({
        Permission.ADMIN_CONSOLE,
        Permission.CONFIG_LAYER3_APPROVE,
        Permission.CONFIG_LAYER2_CHANGE,
        Permission.AUDIT_READ,
    }),
    Role.COMPLIANCE_OFFICER: frozenset({
        Permission.AUDIT_READ,
        Permission.VIEW_PII,
        Permission.CTS_VIEW_ANALYTICS,
        Permission.EJ_VIEW_DASHBOARD,
    }),
    Role.RBI_EXAMINER: frozenset({
        Permission.AUDIT_READ,
    }),
    Role.ML_ENGINEER: frozenset({
        Permission.AI_MODEL_METRICS,
        Permission.AI_MLFLOW_ACCESS,
    }),
}


class UserContext(BaseModel):
    """Populated from the decoded JWT at each request boundary."""
    model_config = ConfigDict(frozen=True)

    user_id: str
    role: Role
    bank_id: str
    clearing_zones: list[str] = Field(default_factory=list)
    engagement_expires_at: Optional[float] = None
    engagement_date_from: Optional[str] = None
    engagement_date_to: Optional[str] = None


def has_permission(user: UserContext, permission: Permission) -> bool:
    """Return True if the user's role grants the given permission."""
    return permission in _ROLE_PERMISSIONS.get(user.role, frozenset())


class RBACPolicy:
    """
    Stateless policy enforcer. Instantiate once per request or use as singleton.
    All assert_* methods raise specific exceptions on violation — callers return 403.
    """

    def assert_permission(self, user: UserContext, permission: Permission) -> None:
        if not has_permission(user, permission):
            raise AccessDeniedError(
                f"Role '{user.role.value}' does not have permission '{permission.value}' "
                f"(user_id={user.user_id}, bank_id={user.bank_id}). "
                f"Required: {permission.name} [{permission.value}]"
            )

    def assert_bank_access(self, user: UserContext, requested_bank_id: str) -> None:
        if user.bank_id != requested_bank_id:
            raise BankIsolationError(
                f"User '{user.user_id}' (bank={user.bank_id}) attempted to access "
                f"bank '{requested_bank_id}' — cross-bank access is forbidden."
            )

    def assert_zone_access(self, user: UserContext, requested_zone: str) -> None:
        # Roles other than ops_reviewer have no zone restriction
        if user.role != Role.OPS_REVIEWER:
            return
        if requested_zone not in user.clearing_zones:
            raise InsufficientZoneScopeError(
                f"ops_reviewer '{user.user_id}' is scoped to zones {user.clearing_zones} "
                f"but requested zone '{requested_zone}'."
            )

    def assert_engagement_active(self, user: UserContext) -> None:
        # Only applies to RBI examiners
        if user.role != Role.RBI_EXAMINER:
            return
        if user.engagement_expires_at is None or time.time() > user.engagement_expires_at:
            raise EngagementExpiredError(
                f"RBI examiner '{user.user_id}' engagement has expired or was never provisioned. "
                f"A new time-limited engagement token is required."
            )
