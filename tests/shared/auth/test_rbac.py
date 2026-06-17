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

ABAC rules:
  ops_reviewer further scoped to clearing_zone attribute
  All roles scoped to bank_id
  rbi_examiner access time-limited per engagement
"""
import time

import pytest

from shared.auth.rbac import (
    Permission,
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
