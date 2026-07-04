"""
Tests for RBAC — role definitions, ABAC rules, permission checks.

TDD: written BEFORE the implementation.

Roles from CLAUDE.md:
  ops_reviewer      — CTS human queue, own zone only, no config
  fraud_analyst     — CTS+EJ analytics, scores+SHAP, no PII, no config
  ops_manager       — CTS+EJ full, cross-zone reports, Layer 3 config
  bank_it_admin     — Admin console, infra only, Layer 2 config (maker-checker)
  compliance_officer— Audit+reports, read-only audit trail, no config
  rbi_examiner      — Audit only (time-scoped), read-only date-scoped, no config
  ml_engineer       — AI server+MLflow, inference logs, no customer data, no config
  smb_admin         — Full control within own SMB tenant
  smb_editor        — Action HR queue + view within own SMB tenant
  smb_viewer        — Read-only within own SMB tenant

Tenant isolation rules:
  SB users can see SB data + all SMB data (from SB context — no impersonation)
  SMB users can ONLY see their own bank's data — complete blind wall to SB
  SMB A cannot see SMB B
  Nobody can edit or delete login logs — Immudb enforces immutability

ABAC rules:
  ops_reviewer further scoped to clearing_zone attribute
  All roles scoped to bank_id
  rbi_examiner access time-limited per engagement
  permission_level (ADMIN/EDIT/READ_ONLY) gates write operations within tenant
"""
import time

import pytest

from shared.auth.rbac import (
    BankType,
    Permission,
    PermissionLevel,
    RBACPolicy,
    Role,
    UserContext,
    has_permission,
)
from shared.auth.exceptions import (
    AccessDeniedError,
    InsufficientZoneScopeError,
    BankIsolationError,
    EngagementExpiredError,
    TenantIsolationError,
    PermissionLevelError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ops_reviewer() -> UserContext:
    return UserContext(
        user_id="rev-001",
        role=Role.OPS_REVIEWER,
        bank_id="test-bank",
        clearing_zones=["MUMBAI"],
    )


@pytest.fixture
def fraud_analyst() -> UserContext:
    return UserContext(
        user_id="fa-001",
        role=Role.FRAUD_ANALYST,
        bank_id="test-bank",
    )


@pytest.fixture
def ops_manager() -> UserContext:
    return UserContext(
        user_id="mgr-001",
        role=Role.OPS_MANAGER,
        bank_id="test-bank",
    )


@pytest.fixture
def bank_it_admin() -> UserContext:
    return UserContext(
        user_id="admin-001",
        role=Role.BANK_IT_ADMIN,
        bank_id="test-bank",
    )


@pytest.fixture
def compliance_officer() -> UserContext:
    return UserContext(
        user_id="co-001",
        role=Role.COMPLIANCE_OFFICER,
        bank_id="test-bank",
    )


@pytest.fixture
def rbi_examiner() -> UserContext:
    return UserContext(
        user_id="rbi-001",
        role=Role.RBI_EXAMINER,
        bank_id="test-bank",
        engagement_expires_at=time.time() + 3600,  # 1 hour from now
        engagement_date_from="2026-01-01",
        engagement_date_to="2026-06-17",
    )


@pytest.fixture
def ml_engineer() -> UserContext:
    return UserContext(
        user_id="ml-001",
        role=Role.ML_ENGINEER,
        bank_id="test-bank",
    )


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

def test_role_enum_contains_all_seven_roles():
    assert Role.OPS_REVIEWER in Role
    assert Role.FRAUD_ANALYST in Role
    assert Role.OPS_MANAGER in Role
    assert Role.BANK_IT_ADMIN in Role
    assert Role.COMPLIANCE_OFFICER in Role
    assert Role.RBI_EXAMINER in Role
    assert Role.ML_ENGINEER in Role


# ---------------------------------------------------------------------------
# CTS human review queue access
# ---------------------------------------------------------------------------

def test_ops_reviewer_can_view_cts_queue(ops_reviewer):
    assert has_permission(ops_reviewer, Permission.CTS_VIEW_QUEUE) is True


def test_fraud_analyst_cannot_view_cts_queue(fraud_analyst):
    assert has_permission(fraud_analyst, Permission.CTS_VIEW_QUEUE) is False


def test_ops_manager_can_view_cts_queue(ops_manager):
    assert has_permission(ops_manager, Permission.CTS_VIEW_QUEUE) is True


def test_bank_it_admin_cannot_view_cts_queue(bank_it_admin):
    assert has_permission(bank_it_admin, Permission.CTS_VIEW_QUEUE) is False


# ---------------------------------------------------------------------------
# Zone scoping — ops_reviewer restricted to own zone
# ---------------------------------------------------------------------------

def test_ops_reviewer_access_own_zone_passes(ops_reviewer):
    policy = RBACPolicy()
    policy.assert_zone_access(ops_reviewer, requested_zone="MUMBAI")  # no exception


def test_ops_reviewer_access_other_zone_raises(ops_reviewer):
    policy = RBACPolicy()
    with pytest.raises(InsufficientZoneScopeError):
        policy.assert_zone_access(ops_reviewer, requested_zone="DELHI")


def test_ops_manager_access_any_zone_passes(ops_manager):
    policy = RBACPolicy()
    policy.assert_zone_access(ops_manager, requested_zone="DELHI")   # no exception
    policy.assert_zone_access(ops_manager, requested_zone="MUMBAI")  # no exception


def test_compliance_officer_access_any_zone_passes(compliance_officer):
    policy = RBACPolicy()
    policy.assert_zone_access(compliance_officer, requested_zone="CHENNAI")


# ---------------------------------------------------------------------------
# Bank isolation — cross-bank access forbidden
# ---------------------------------------------------------------------------

def test_bank_isolation_same_bank_passes(ops_reviewer):
    policy = RBACPolicy()
    policy.assert_bank_access(ops_reviewer, requested_bank_id="test-bank")  # no exception


def test_bank_isolation_different_bank_raises(ops_reviewer):
    policy = RBACPolicy()
    with pytest.raises(BankIsolationError):
        policy.assert_bank_access(ops_reviewer, requested_bank_id="other-bank")


def test_bank_isolation_applies_to_all_roles(ops_manager, fraud_analyst, compliance_officer):
    policy = RBACPolicy()
    for user in [ops_manager, fraud_analyst, compliance_officer]:
        with pytest.raises(BankIsolationError):
            policy.assert_bank_access(user, requested_bank_id="rival-bank")


# ---------------------------------------------------------------------------
# PII access — can_view_pii()
# ---------------------------------------------------------------------------

def test_ops_reviewer_cannot_view_pii(ops_reviewer):
    assert has_permission(ops_reviewer, Permission.VIEW_PII) is False


def test_fraud_analyst_cannot_view_pii(fraud_analyst):
    assert has_permission(fraud_analyst, Permission.VIEW_PII) is False


def test_ops_manager_can_view_pii(ops_manager):
    assert has_permission(ops_manager, Permission.VIEW_PII) is True


def test_bank_it_admin_cannot_view_pii(bank_it_admin):
    # IT admin has infra access, not transaction data
    assert has_permission(bank_it_admin, Permission.VIEW_PII) is False


def test_compliance_officer_can_view_pii(compliance_officer):
    assert has_permission(compliance_officer, Permission.VIEW_PII) is True


def test_ml_engineer_cannot_view_pii(ml_engineer):
    assert has_permission(ml_engineer, Permission.VIEW_PII) is False


# ---------------------------------------------------------------------------
# Config change access — Layer 3
# ---------------------------------------------------------------------------

def test_ops_manager_can_submit_config_change(ops_manager):
    assert has_permission(ops_manager, Permission.CONFIG_LAYER3_SUBMIT) is True


def test_bank_it_admin_can_approve_config_change(bank_it_admin):
    assert has_permission(bank_it_admin, Permission.CONFIG_LAYER3_APPROVE) is True


def test_ops_reviewer_cannot_change_config(ops_reviewer):
    assert has_permission(ops_reviewer, Permission.CONFIG_LAYER3_SUBMIT) is False
    assert has_permission(ops_reviewer, Permission.CONFIG_LAYER3_APPROVE) is False


def test_fraud_analyst_cannot_change_config(fraud_analyst):
    assert has_permission(fraud_analyst, Permission.CONFIG_LAYER3_SUBMIT) is False


def test_compliance_officer_cannot_change_config(compliance_officer):
    assert has_permission(compliance_officer, Permission.CONFIG_LAYER3_SUBMIT) is False


# ---------------------------------------------------------------------------
# Audit trail access
# ---------------------------------------------------------------------------

def test_compliance_officer_can_read_audit(compliance_officer):
    assert has_permission(compliance_officer, Permission.AUDIT_READ) is True


def test_rbi_examiner_can_read_audit(rbi_examiner):
    assert has_permission(rbi_examiner, Permission.AUDIT_READ) is True


def test_ops_reviewer_cannot_read_audit(ops_reviewer):
    assert has_permission(ops_reviewer, Permission.AUDIT_READ) is False


def test_fraud_analyst_cannot_read_audit(fraud_analyst):
    assert has_permission(fraud_analyst, Permission.AUDIT_READ) is False


# ---------------------------------------------------------------------------
# RBI examiner — time-limited engagement
# ---------------------------------------------------------------------------

def test_rbi_examiner_active_engagement_passes(rbi_examiner):
    policy = RBACPolicy()
    policy.assert_engagement_active(rbi_examiner)  # no exception — expires in 1 hour


def test_rbi_examiner_expired_engagement_raises():
    expired = UserContext(
        user_id="rbi-expired",
        role=Role.RBI_EXAMINER,
        bank_id="test-bank",
        engagement_expires_at=time.time() - 1,  # 1 second ago
        engagement_date_from="2026-01-01",
        engagement_date_to="2026-06-17",
    )
    policy = RBACPolicy()
    with pytest.raises(EngagementExpiredError):
        policy.assert_engagement_active(expired)


def test_rbi_examiner_no_engagement_raises():
    no_engagement = UserContext(
        user_id="rbi-no-eng",
        role=Role.RBI_EXAMINER,
        bank_id="test-bank",
        # No engagement_expires_at set
    )
    policy = RBACPolicy()
    with pytest.raises(EngagementExpiredError):
        policy.assert_engagement_active(no_engagement)


def test_non_rbi_user_assert_engagement_is_noop(ops_manager):
    policy = RBACPolicy()
    policy.assert_engagement_active(ops_manager)  # no exception — not rbi_examiner


# ---------------------------------------------------------------------------
# ML engineer — AI access, no customer data
# ---------------------------------------------------------------------------

def test_ml_engineer_can_view_model_metrics(ml_engineer):
    assert has_permission(ml_engineer, Permission.AI_MODEL_METRICS) is True


def test_ml_engineer_cannot_view_cts_queue(ml_engineer):
    assert has_permission(ml_engineer, Permission.CTS_VIEW_QUEUE) is False


def test_ml_engineer_cannot_view_pii(ml_engineer):
    assert has_permission(ml_engineer, Permission.VIEW_PII) is False


# ---------------------------------------------------------------------------
# assert_permission helper
# ---------------------------------------------------------------------------

def test_assert_permission_raises_on_denied(fraud_analyst):
    policy = RBACPolicy()
    with pytest.raises(AccessDeniedError):
        policy.assert_permission(fraud_analyst, Permission.CTS_VIEW_QUEUE)


def test_assert_permission_passes_on_allowed(ops_reviewer):
    policy = RBACPolicy()
    policy.assert_permission(ops_reviewer, Permission.CTS_VIEW_QUEUE)  # no exception


def test_assert_permission_error_includes_role_and_permission(fraud_analyst):
    policy = RBACPolicy()
    with pytest.raises(AccessDeniedError) as exc_info:
        policy.assert_permission(fraud_analyst, Permission.CTS_VIEW_QUEUE)
    msg = str(exc_info.value)
    assert "fraud_analyst" in msg.lower() or "FRAUD_ANALYST" in msg
    assert "CTS_VIEW_QUEUE" in msg


# ===========================================================================
# CYCLE 1: BankType + PermissionLevel enums
# ===========================================================================

class TestBankTypeEnum:
    def test_sb_value(self):
        assert BankType.SB == "SB"

    def test_smb_value(self):
        assert BankType.SMB == "SMB"

    def test_only_two_values(self):
        assert set(BankType) == {BankType.SB, BankType.SMB}


class TestPermissionLevelEnum:
    def test_admin_value(self):
        assert PermissionLevel.ADMIN == "ADMIN"

    def test_edit_value(self):
        assert PermissionLevel.EDIT == "EDIT"

    def test_read_only_value(self):
        assert PermissionLevel.READ_ONLY == "READ_ONLY"

    def test_only_three_values(self):
        assert set(PermissionLevel) == {
            PermissionLevel.ADMIN,
            PermissionLevel.EDIT,
            PermissionLevel.READ_ONLY,
        }


# ===========================================================================
# CYCLE 2: UserContext carries bank_type and permission_level
# ===========================================================================

class TestUserContextBankTypeAndPermissionLevel:
    def test_sb_user_has_bank_type(self):
        user = UserContext(
            user_id="u-sb-1",
            role=Role.OPS_MANAGER,
            bank_id="hdfc-bank",
            bank_type=BankType.SB,
            permission_level=PermissionLevel.EDIT,
        )
        assert user.bank_type == BankType.SB
        assert user.permission_level == PermissionLevel.EDIT

    def test_smb_user_has_bank_type(self):
        user = UserContext(
            user_id="u-smb-1",
            role=Role.SMB_EDITOR,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.EDIT,
        )
        assert user.bank_type == BankType.SMB

    def test_default_bank_type_is_sb_for_backward_compat(self):
        # Existing UserContext without bank_type must not break — defaults to SB
        user = UserContext(
            user_id="u-old",
            role=Role.OPS_REVIEWER,
            bank_id="test-bank",
        )
        assert user.bank_type == BankType.SB

    def test_default_permission_level_is_edit_for_backward_compat(self):
        user = UserContext(
            user_id="u-old",
            role=Role.OPS_REVIEWER,
            bank_id="test-bank",
        )
        assert user.permission_level == PermissionLevel.EDIT


# ===========================================================================
# CYCLE 3: SMB roles in Role enum
# ===========================================================================

class TestSMBRoles:
    def test_smb_admin_role_exists(self):
        assert Role.SMB_ADMIN == "smb_admin"

    def test_smb_editor_role_exists(self):
        assert Role.SMB_EDITOR == "smb_editor"

    def test_smb_viewer_role_exists(self):
        assert Role.SMB_VIEWER == "smb_viewer"

    def test_smb_admin_can_view_hr_queue(self):
        user = UserContext(
            user_id="smb-adm-1",
            role=Role.SMB_ADMIN,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.ADMIN,
        )
        assert has_permission(user, Permission.CTS_VIEW_QUEUE) is True

    def test_smb_admin_can_submit_decision(self):
        user = UserContext(
            user_id="smb-adm-1",
            role=Role.SMB_ADMIN,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.ADMIN,
        )
        assert has_permission(user, Permission.CTS_SUBMIT_DECISION) is True

    def test_smb_editor_can_view_queue_and_submit_decision(self):
        user = UserContext(
            user_id="smb-ed-1",
            role=Role.SMB_EDITOR,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.EDIT,
        )
        assert has_permission(user, Permission.CTS_VIEW_QUEUE) is True
        assert has_permission(user, Permission.CTS_SUBMIT_DECISION) is True

    def test_smb_viewer_can_view_queue_but_not_submit(self):
        user = UserContext(
            user_id="smb-vw-1",
            role=Role.SMB_VIEWER,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.READ_ONLY,
        )
        assert has_permission(user, Permission.CTS_VIEW_QUEUE) is True
        assert has_permission(user, Permission.CTS_SUBMIT_DECISION) is False

    def test_smb_admin_can_read_login_log(self):
        user = UserContext(
            user_id="smb-adm-1",
            role=Role.SMB_ADMIN,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.ADMIN,
        )
        assert has_permission(user, Permission.LOGIN_LOG_READ) is True

    def test_smb_viewer_can_read_login_log(self):
        user = UserContext(
            user_id="smb-vw-1",
            role=Role.SMB_VIEWER,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.READ_ONLY,
        )
        assert has_permission(user, Permission.LOGIN_LOG_READ) is True

    def test_nobody_has_login_log_delete_permission(self):
        # LOGIN_LOG_DELETE must not exist in any role's permission set
        for role in Role:
            user = UserContext(
                user_id="u-test",
                role=role,
                bank_id="test-bank",
                bank_type=BankType.SB if role not in (Role.SMB_ADMIN, Role.SMB_EDITOR, Role.SMB_VIEWER) else BankType.SMB,
                permission_level=PermissionLevel.ADMIN,
            )
            assert has_permission(user, Permission.LOGIN_LOG_DELETE) is False

    def test_smb_admin_cannot_access_sb_config(self):
        user = UserContext(
            user_id="smb-adm-1",
            role=Role.SMB_ADMIN,
            bank_id="saraswat-ucb",
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.ADMIN,
        )
        assert has_permission(user, Permission.CONFIG_LAYER3_SUBMIT) is False
        assert has_permission(user, Permission.CONFIG_LAYER3_APPROVE) is False
        assert has_permission(user, Permission.ADMIN_CONSOLE) is False


# ===========================================================================
# CYCLE 4: TenantIsolationError + assert_tenant_access
# ===========================================================================

@pytest.fixture
def sb_admin():
    return UserContext(
        user_id="sb-adm-1",
        role=Role.BANK_IT_ADMIN,
        bank_id="hdfc-bank",
        bank_type=BankType.SB,
        permission_level=PermissionLevel.ADMIN,
    )

@pytest.fixture
def sb_editor():
    return UserContext(
        user_id="sb-ed-1",
        role=Role.OPS_MANAGER,
        bank_id="hdfc-bank",
        bank_type=BankType.SB,
        permission_level=PermissionLevel.EDIT,
    )

@pytest.fixture
def smb_admin_user():
    return UserContext(
        user_id="smb-adm-1",
        role=Role.SMB_ADMIN,
        bank_id="saraswat-ucb",
        bank_type=BankType.SMB,
        permission_level=PermissionLevel.ADMIN,
    )

@pytest.fixture
def smb_viewer_user():
    return UserContext(
        user_id="smb-vw-1",
        role=Role.SMB_VIEWER,
        bank_id="saraswat-ucb",
        bank_type=BankType.SMB,
        permission_level=PermissionLevel.READ_ONLY,
    )


class TestTenantIsolation:
    """SB sees all. SMB sees only own. No cross-tenant. No impersonation."""

    def test_sb_user_can_access_own_sb_data(self, sb_admin):
        policy = RBACPolicy()
        # No exception
        policy.assert_tenant_access(sb_admin, target_bank_type=BankType.SB, target_bank_id="hdfc-bank")

    def test_sb_user_can_view_smb_data_from_sb_context(self, sb_admin):
        policy = RBACPolicy()
        # SB can see any SMB's data — no exception
        policy.assert_tenant_access(sb_admin, target_bank_type=BankType.SMB, target_bank_id="saraswat-ucb")

    def test_sb_user_cannot_access_different_sb(self, sb_admin):
        policy = RBACPolicy()
        with pytest.raises(BankIsolationError):
            policy.assert_tenant_access(sb_admin, target_bank_type=BankType.SB, target_bank_id="icici-bank")

    def test_smb_user_can_access_own_smb_data(self, smb_admin_user):
        policy = RBACPolicy()
        # No exception
        policy.assert_tenant_access(smb_admin_user, target_bank_type=BankType.SMB, target_bank_id="saraswat-ucb")

    def test_smb_user_cannot_access_sb_data(self, smb_admin_user):
        policy = RBACPolicy()
        with pytest.raises(TenantIsolationError):
            policy.assert_tenant_access(smb_admin_user, target_bank_type=BankType.SB, target_bank_id="hdfc-bank")

    def test_smb_user_cannot_access_different_smb(self, smb_admin_user):
        policy = RBACPolicy()
        with pytest.raises(TenantIsolationError):
            policy.assert_tenant_access(smb_admin_user, target_bank_type=BankType.SMB, target_bank_id="cosmos-ucb")

    def test_smb_viewer_cannot_access_sb_data(self, smb_viewer_user):
        policy = RBACPolicy()
        with pytest.raises(TenantIsolationError):
            policy.assert_tenant_access(smb_viewer_user, target_bank_type=BankType.SB, target_bank_id="hdfc-bank")

    def test_tenant_isolation_error_message_is_informative(self, smb_admin_user):
        policy = RBACPolicy()
        with pytest.raises(TenantIsolationError) as exc_info:
            policy.assert_tenant_access(smb_admin_user, target_bank_type=BankType.SB, target_bank_id="hdfc-bank")
        msg = str(exc_info.value)
        assert "saraswat-ucb" in msg
        assert "SMB" in msg


# ===========================================================================
# CYCLE 5: PermissionLevel enforcement
# ===========================================================================

class TestPermissionLevelEnforcement:

    def test_admin_can_perform_admin_action(self, sb_admin):
        policy = RBACPolicy()
        # No exception
        policy.assert_permission_level(sb_admin, required=PermissionLevel.ADMIN)

    def test_edit_user_cannot_perform_admin_action(self, sb_editor):
        policy = RBACPolicy()
        with pytest.raises(PermissionLevelError):
            policy.assert_permission_level(sb_editor, required=PermissionLevel.ADMIN)

    def test_edit_user_can_perform_edit_action(self, sb_editor):
        policy = RBACPolicy()
        # No exception
        policy.assert_permission_level(sb_editor, required=PermissionLevel.EDIT)

    def test_read_only_user_cannot_perform_edit_action(self):
        ro_user = UserContext(
            user_id="ro-1",
            role=Role.OPS_REVIEWER,
            bank_id="hdfc-bank",
            bank_type=BankType.SB,
            permission_level=PermissionLevel.READ_ONLY,
        )
        policy = RBACPolicy()
        with pytest.raises(PermissionLevelError):
            policy.assert_permission_level(ro_user, required=PermissionLevel.EDIT)

    def test_read_only_user_can_perform_read_action(self):
        ro_user = UserContext(
            user_id="ro-1",
            role=Role.OPS_REVIEWER,
            bank_id="hdfc-bank",
            bank_type=BankType.SB,
            permission_level=PermissionLevel.READ_ONLY,
        )
        policy = RBACPolicy()
        # No exception — READ_ONLY satisfies READ_ONLY requirement
        policy.assert_permission_level(ro_user, required=PermissionLevel.READ_ONLY)

    def test_admin_satisfies_edit_requirement(self, sb_admin):
        policy = RBACPolicy()
        # ADMIN is a superset of EDIT
        policy.assert_permission_level(sb_admin, required=PermissionLevel.EDIT)

    def test_admin_satisfies_read_only_requirement(self, sb_admin):
        policy = RBACPolicy()
        policy.assert_permission_level(sb_admin, required=PermissionLevel.READ_ONLY)

    def test_permission_level_error_message_is_informative(self, sb_editor):
        policy = RBACPolicy()
        with pytest.raises(PermissionLevelError) as exc_info:
            policy.assert_permission_level(sb_editor, required=PermissionLevel.ADMIN)
        msg = str(exc_info.value)
        assert "EDIT" in msg
        assert "ADMIN" in msg


# ===========================================================================
# CYCLE 6: Login Log — SB sees all, SMB sees own, nobody can delete
# ===========================================================================

class TestLoginLogAccess:

    def test_sb_admin_has_login_log_read(self, sb_admin):
        assert has_permission(sb_admin, Permission.LOGIN_LOG_READ) is True

    def test_sb_editor_has_login_log_read(self, sb_editor):
        assert has_permission(sb_editor, Permission.LOGIN_LOG_READ) is True

    def test_sb_read_only_user_has_login_log_read(self):
        ro = UserContext(
            user_id="ro-1", role=Role.COMPLIANCE_OFFICER,
            bank_id="hdfc-bank", bank_type=BankType.SB,
            permission_level=PermissionLevel.READ_ONLY,
        )
        assert has_permission(ro, Permission.LOGIN_LOG_READ) is True

    def test_smb_admin_has_login_log_read(self, smb_admin_user):
        assert has_permission(smb_admin_user, Permission.LOGIN_LOG_READ) is True

    def test_login_log_read_scope_sb_sees_all(self, sb_admin):
        # SB user's login log query must not be restricted to a single bank_id.
        # We verify this via the policy helper — returns None meaning "no restriction"
        policy = RBACPolicy()
        scope = policy.login_log_bank_scope(sb_admin)
        assert scope is None  # None = no bank_id filter — sees all

    def test_login_log_read_scope_smb_sees_own(self, smb_admin_user):
        policy = RBACPolicy()
        scope = policy.login_log_bank_scope(smb_admin_user)
        assert scope == "saraswat-ucb"  # must filter to own bank only

    def test_login_log_delete_does_not_exist_on_any_role(self):
        # LOGIN_LOG_DELETE must not be in _ROLE_PERMISSIONS for any role
        for role in Role:
            user = UserContext(
                user_id="u-test", role=role, bank_id="test-bank",
                bank_type=BankType.SB if role not in (Role.SMB_ADMIN, Role.SMB_EDITOR, Role.SMB_VIEWER) else BankType.SMB,
                permission_level=PermissionLevel.ADMIN,
            )
            assert has_permission(user, Permission.LOGIN_LOG_DELETE) is False


class TestSMBInstrumentFilter:
    """Phase 5 — Row-level isolation: smb_instrument_filter() for safe query scoping."""

    def _sb_user(self):
        return UserContext(
            user_id="sb-ops-1", role=Role.OPS_MANAGER,
            bank_id="saraswat-coop", bank_type=BankType.SB,
            permission_level=PermissionLevel.EDIT,
        )

    def _smb_user(self, smb_id="cosmos-coop", sponsor="saraswat-coop"):
        return UserContext(
            user_id="smb-edit-1", role=Role.SMB_EDITOR,
            bank_id=smb_id, bank_type=BankType.SMB,
            permission_level=PermissionLevel.EDIT,
            sponsor_bank_id=sponsor,
        )

    def test_sb_filter_returns_own_bank_id_no_smb_restriction(self):
        """SB user: effective_bank_id = own bank, smb_id_filter = None (sees all SMBs)."""
        policy = RBACPolicy()
        eff_bank, smb_filter = policy.smb_instrument_filter(self._sb_user())
        assert eff_bank == "saraswat-coop"
        assert smb_filter is None

    def test_smb_filter_returns_sponsor_bank_and_own_smb_id(self):
        """SMB user: effective_bank_id = sponsor bank, smb_id_filter = own bank_id."""
        policy = RBACPolicy()
        eff_bank, smb_filter = policy.smb_instrument_filter(self._smb_user())
        assert eff_bank == "saraswat-coop"    # query SB's data store
        assert smb_filter == "cosmos-coop"    # filtered to this SMB only

    def test_smb_filter_without_sponsor_falls_back_to_own_bank(self):
        """SMB user with no sponsor_bank_id: effective_bank_id falls back to own bank_id."""
        smb_no_sponsor = UserContext(
            user_id="smb-ns-1", role=Role.SMB_VIEWER,
            bank_id="no-sponsor-ucb", bank_type=BankType.SMB,
            permission_level=PermissionLevel.READ_ONLY,
            # sponsor_bank_id not set
        )
        policy = RBACPolicy()
        eff_bank, smb_filter = policy.smb_instrument_filter(smb_no_sponsor)
        assert eff_bank == "no-sponsor-ucb"
        assert smb_filter == "no-sponsor-ucb"

    def test_sponsor_bank_id_field_defaults_to_none(self):
        """UserContext backward compat: sponsor_bank_id is optional, defaults None."""
        user = UserContext(
            user_id="u", role=Role.OPS_MANAGER,
            bank_id="b", bank_type=BankType.SB,
            permission_level=PermissionLevel.EDIT,
        )
        assert user.sponsor_bank_id is None

    def test_smb_user_can_set_sponsor_bank_id(self):
        """SMB UserContext accepts sponsor_bank_id from JWT."""
        user = self._smb_user(smb_id="cosmos-coop", sponsor="saraswat-coop")
        assert user.sponsor_bank_id == "saraswat-coop"
        assert user.bank_id == "cosmos-coop"
        assert user.bank_type == BankType.SMB
