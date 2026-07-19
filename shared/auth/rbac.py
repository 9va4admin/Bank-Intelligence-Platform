"""
RBAC + ABAC — Role-Based Access Control with Attribute-Based extensions.

Two-axis model:
  Axis 1 — Tenant:          BankType (SB | SMB) + bank_id
  Axis 2 — Permission level: PermissionLevel (ADMIN | EDIT | READ_ONLY)
  Axis 3 — Functional role:  Role (ops_reviewer, fraud_analyst, ... smb_admin, smb_editor, smb_viewer)

Tenant isolation rules (non-negotiable):
  SB users  → can access own SB data + view any SMB data from SB context (no impersonation)
  SMB users → can ONLY access their own bank's data; blind wall to SB and other SMBs

PermissionLevel gates operations within the tenant:
  ADMIN      → full control including user management
  EDIT       → read + modify/action (superset of READ_ONLY)
  READ_ONLY  → view only, zero write operations

Functional Role gates which modules/data a user can see.
SMB roles (smb_admin/smb_editor/smb_viewer) map 1:1 to permission levels.

Every API route and PII decryption call must go through this module.
Never hard-code role checks in route handlers — always use has_permission()
or RBACPolicy.assert_* via FastAPI dependency injection.
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
    PermissionLevelError,
    TenantIsolationError,
)


class BankType(str, Enum):
    SB  = "SB"   # Sponsor Bank — runs ASTRA, is the NGCH direct member
    SMB = "SMB"  # Sub-Member Bank — routes through the SB


class PermissionLevel(str, Enum):
    ADMIN     = "ADMIN"      # Full control within own tenant
    EDIT      = "EDIT"       # Read + action/modify within own tenant
    READ_ONLY = "READ_ONLY"  # View only within own tenant

# Hierarchy: ADMIN > EDIT > READ_ONLY
_LEVEL_RANK: dict[PermissionLevel, int] = {
    PermissionLevel.READ_ONLY: 0,
    PermissionLevel.EDIT:      1,
    PermissionLevel.ADMIN:     2,
}


class Role(str, Enum):
    # SB functional roles (job-function specific)
    OPS_REVIEWER       = "ops_reviewer"
    FRAUD_ANALYST      = "fraud_analyst"
    OPS_MANAGER        = "ops_manager"
    BANK_IT_ADMIN      = "bank_it_admin"
    COMPLIANCE_OFFICER = "compliance_officer"
    RBI_EXAMINER       = "rbi_examiner"
    ML_ENGINEER        = "ml_engineer"
    SMB_IT_ADMIN       = "smb_it_admin"  # SB staff managing SMB registrations

    # SMB roles — map 1:1 to PermissionLevel within the SMB tenant
    SMB_ADMIN  = "smb_admin"   # Full control of own SMB
    SMB_EDITOR = "smb_editor"  # Action HR queue + modify within own SMB
    SMB_VIEWER = "smb_viewer"  # Read-only within own SMB


class Permission(str, Enum):
    # CTS operations
    CTS_VIEW_QUEUE      = "cts:view_queue"
    CTS_SUBMIT_DECISION = "cts:submit_decision"
    CTS_VIEW_ANALYTICS  = "cts:view_analytics"

    # EJ operations
    EJ_VIEW_DASHBOARD = "ej:view_dashboard"
    EJ_VIEW_DISPUTES  = "ej:view_disputes"

    # PII — gates column-level decryption
    VIEW_PII = "pii:view"

    # Config changes
    CONFIG_LAYER3_SUBMIT  = "config:layer3:submit"   # maker
    CONFIG_LAYER3_APPROVE = "config:layer3:approve"  # checker
    CONFIG_LAYER2_CHANGE  = "config:layer2:change"   # bank_it_admin via PR

    # Audit trail
    AUDIT_READ = "audit:read"

    # Login log — read only; DELETE intentionally omitted from all roles
    LOGIN_LOG_READ   = "login_log:read"
    LOGIN_LOG_DELETE = "login_log:delete"  # defined but granted to NO role — Immudb immutability

    # AI / MLflow
    AI_MODEL_METRICS = "ai:model_metrics"
    AI_MLFLOW_ACCESS = "ai:mlflow_access"

    # Admin console
    ADMIN_CONSOLE = "admin:console"

    # Sub-Member Bank management (SB-side permissions)
    SMB_REGISTER      = "smb:register"
    SMB_VIEW_LEDGER   = "smb:view_ledger"
    SMB_VAULT_SYNC    = "smb:vault_sync"
    SMB_CONFIG_CHANGE = "smb:config_change"

    # User management
    USER_MANAGE = "user:manage"  # create/edit/deactivate users within own tenant


# Permission matrix: role → granted permissions
# LOGIN_LOG_DELETE is deliberately absent from every role.
_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OPS_REVIEWER: frozenset({
        Permission.CTS_VIEW_QUEUE,
        Permission.CTS_SUBMIT_DECISION,
        Permission.LOGIN_LOG_READ,
    }),
    Role.FRAUD_ANALYST: frozenset({
        Permission.CTS_VIEW_ANALYTICS,
        Permission.EJ_VIEW_DASHBOARD,
        Permission.EJ_VIEW_DISPUTES,
        Permission.LOGIN_LOG_READ,
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
        Permission.SMB_VIEW_LEDGER,
        Permission.LOGIN_LOG_READ,
    }),
    Role.BANK_IT_ADMIN: frozenset({
        Permission.ADMIN_CONSOLE,
        Permission.CONFIG_LAYER3_APPROVE,
        Permission.CONFIG_LAYER2_CHANGE,
        Permission.AUDIT_READ,
        Permission.SMB_REGISTER,
        Permission.SMB_VIEW_LEDGER,
        Permission.SMB_VAULT_SYNC,
        Permission.SMB_CONFIG_CHANGE,
        Permission.USER_MANAGE,
        Permission.LOGIN_LOG_READ,
    }),
    Role.COMPLIANCE_OFFICER: frozenset({
        Permission.AUDIT_READ,
        Permission.VIEW_PII,
        Permission.CTS_VIEW_ANALYTICS,
        Permission.EJ_VIEW_DASHBOARD,
        Permission.SMB_VIEW_LEDGER,
        Permission.LOGIN_LOG_READ,
    }),
    Role.RBI_EXAMINER: frozenset({
        Permission.AUDIT_READ,
        Permission.LOGIN_LOG_READ,
    }),
    Role.ML_ENGINEER: frozenset({
        Permission.AI_MODEL_METRICS,
        Permission.AI_MLFLOW_ACCESS,
    }),
    Role.SMB_IT_ADMIN: frozenset({
        Permission.SMB_REGISTER,
        Permission.SMB_VIEW_LEDGER,
        Permission.SMB_VAULT_SYNC,
        Permission.SMB_CONFIG_CHANGE,
        Permission.AUDIT_READ,
        Permission.LOGIN_LOG_READ,
    }),
    # SMB roles — scoped to own SMB tenant by assert_tenant_access
    Role.SMB_ADMIN: frozenset({
        Permission.CTS_VIEW_QUEUE,
        Permission.CTS_SUBMIT_DECISION,
        Permission.SMB_VIEW_LEDGER,
        Permission.AUDIT_READ,
        Permission.USER_MANAGE,
        Permission.LOGIN_LOG_READ,
    }),
    Role.SMB_EDITOR: frozenset({
        Permission.CTS_VIEW_QUEUE,
        Permission.CTS_SUBMIT_DECISION,
        Permission.SMB_VIEW_LEDGER,
        Permission.LOGIN_LOG_READ,
    }),
    Role.SMB_VIEWER: frozenset({
        Permission.CTS_VIEW_QUEUE,
        Permission.SMB_VIEW_LEDGER,
        Permission.LOGIN_LOG_READ,
    }),
}


class UserContext(BaseModel):
    """Populated from the decoded JWT at each request boundary."""
    model_config = ConfigDict(frozen=True)

    user_id: str
    role: Role
    bank_id: str
    bank_type: BankType = BankType.SB           # default SB for backward compat
    permission_level: PermissionLevel = PermissionLevel.READ_ONLY  # least-privilege default
    clearing_zones: list[str] = Field(default_factory=list)
    engagement_expires_at: Optional[float] = None
    engagement_date_from: Optional[str] = None
    engagement_date_to: Optional[str] = None
    sponsor_bank_id: Optional[str] = None      # SMB users only: the SB they route through


def has_permission(user: UserContext, permission: Permission) -> bool:
    """Return True if the user's role grants the given permission."""
    return permission in _ROLE_PERMISSIONS.get(user.role, frozenset())


class RBACPolicy:
    """
    Stateless policy enforcer. All assert_* methods raise specific exceptions
    on violation — callers return 403. Call order in every route handler:
      1. assert_tenant_access   — am I even allowed to see this tenant's data?
      2. assert_permission_level — do I have the right level (ADMIN/EDIT/READ_ONLY)?
      3. assert_permission       — does my role grant this specific permission?
      4. assert_zone_access      — (ops_reviewer only) am I in the right zone?
      5. assert_engagement_active — (rbi_examiner only) is my engagement live?
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

    def assert_tenant_access(
        self,
        user: UserContext,
        target_bank_type: BankType,
        target_bank_id: str,
    ) -> None:
        """
        Enforce the hard SB↔SMB tenant wall.

        SB user:
          - Can access own SB data (bank_id must match)
          - Can VIEW any SMB data from SB context (no impersonation)
          - Cannot access a different SB

        SMB user:
          - Can ONLY access own bank's data (bank_type=SMB, bank_id must match)
          - Cannot access SB data — ever
          - Cannot access another SMB's data
        """
        if user.bank_type == BankType.SB:
            if target_bank_type == BankType.SB and user.bank_id != target_bank_id:
                raise BankIsolationError(
                    f"SB user '{user.user_id}' (bank={user.bank_id}) cannot access "
                    f"SB data for bank '{target_bank_id}'."
                )
            # SB → any SMB: allowed (view from SB context)
        else:
            # SMB user: zero tolerance for crossing tenant boundary
            if target_bank_type == BankType.SB:
                raise TenantIsolationError(
                    f"SMB user '{user.user_id}' (bank={user.bank_id}, type=SMB) "
                    f"attempted to access SB-level data — tenant boundary violation."
                )
            if user.bank_id != target_bank_id:
                raise TenantIsolationError(
                    f"SMB user '{user.user_id}' (bank={user.bank_id}) attempted to access "
                    f"SMB '{target_bank_id}' — cross-SMB access is forbidden."
                )

    def assert_permission_level(
        self,
        user: UserContext,
        required: PermissionLevel,
    ) -> None:
        """
        ADMIN satisfies ADMIN, EDIT, READ_ONLY requirements.
        EDIT  satisfies EDIT, READ_ONLY requirements.
        READ_ONLY satisfies only READ_ONLY requirements.
        """
        if _LEVEL_RANK[user.permission_level] < _LEVEL_RANK[required]:
            raise PermissionLevelError(
                f"User '{user.user_id}' has permission level '{user.permission_level.value}' "
                f"but operation requires '{required.value}'."
            )

    def assert_zone_access(self, user: UserContext, requested_zone: str) -> None:
        if user.role != Role.OPS_REVIEWER:
            return
        if requested_zone not in user.clearing_zones:
            raise InsufficientZoneScopeError(
                f"ops_reviewer '{user.user_id}' is scoped to zones {user.clearing_zones} "
                f"but requested zone '{requested_zone}'."
            )

    def assert_engagement_active(self, user: UserContext) -> None:
        if user.role != Role.RBI_EXAMINER:
            return
        if user.engagement_expires_at is None or time.time() > user.engagement_expires_at:
            raise EngagementExpiredError(
                f"RBI examiner '{user.user_id}' engagement has expired or was never provisioned. "
                f"A new time-limited engagement token is required."
            )

    def login_log_bank_scope(self, user: UserContext) -> Optional[str]:
        """
        Returns the bank_id filter to apply to login log queries.
        SB users see all logs  → returns None (no filter).
        SMB users see own only → returns their bank_id.
        """
        if user.bank_type == BankType.SB:
            return None
        return user.bank_id

    def smb_instrument_filter(self, user: UserContext) -> tuple[str, Optional[str]]:
        """
        Returns (effective_bank_id, smb_id_filter) for instrument queries.

        SB user:  effective_bank_id = user.bank_id, smb_id_filter = None (sees all SMBs)
        SMB user: effective_bank_id = sponsor_bank_id (or own bank_id if no sponsor),
                  smb_id_filter = user.bank_id (row-level isolation to this SMB only)

        Usage in SQL:
          WHERE bank_id = $1 [AND smb_id = $2]   -- $2 only when smb_id_filter is not None
        Usage in Temporal query:
          BankId = '{eff_bank}' [AND SmbId = '{smb_filter}']
        """
        if user.bank_type == BankType.SB:
            return (user.bank_id, None)
        # SMB: instruments are stored under the sponsor SB's bank_id namespace
        eff_bank = user.sponsor_bank_id if user.sponsor_bank_id else user.bank_id
        return (eff_bank, user.bank_id)
