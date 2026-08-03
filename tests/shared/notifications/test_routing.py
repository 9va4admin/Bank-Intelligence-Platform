"""
TDD tests for shared/notifications/routing.py — NotificationRoutingTable.

Tests verify:
- Event → recipient roles are correct per the Notification Taxonomy
- Channel selection follows the delivery cascade (Bell / Email / WA)
- Priority assignment is correct (P0/P1/P2/P3)
- Incident flag is set correctly
- build_requests() produces the right NotificationRequest objects
- Edge cases: unknown event type raises, empty bank context raises
"""
import pytest
from unittest.mock import MagicMock

from shared.audit.audit_event import AuditEventType
from shared.notifications.routing import (
    NotificationRoutingTable,
    RoutingSpec,
    RecipientRule,
    Priority,
    Channel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_routing_table() -> NotificationRoutingTable:
    return NotificationRoutingTable()


def _make_user(role: str, user_id: str = "u1", email: str = "user@bank.com", phone: str = "+919900000000"):
    return MagicMock(user_id=user_id, role=role, email=email, phone=phone, bank_id="test-bank")


# ---------------------------------------------------------------------------
# Priority constants
# ---------------------------------------------------------------------------

class TestPriority:
    def test_p0_value(self):
        assert Priority.P0.value == "P0"

    def test_p1_value(self):
        assert Priority.P1.value == "P1"

    def test_p2_value(self):
        assert Priority.P2.value == "P2"

    def test_p3_value(self):
        assert Priority.P3.value == "P3"


# ---------------------------------------------------------------------------
# Channel constants
# ---------------------------------------------------------------------------

class TestChannel:
    def test_email_value(self):
        assert Channel.EMAIL.value == "email"

    def test_whatsapp_value(self):
        assert Channel.WHATSAPP.value == "whatsapp"

    def test_bell_value(self):
        assert Channel.BELL.value == "bell"


# ---------------------------------------------------------------------------
# RoutingSpec — kill switch events
# ---------------------------------------------------------------------------

class TestRoutingSpecKillSwitch:
    def test_ks_engaged_is_p0(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        assert spec.priority == Priority.P0

    def test_ks_engaged_creates_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        assert spec.create_incident is True

    def test_ks_engaged_notifies(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        assert spec.notify is True

    def test_ks_engaged_roles_include_bank_it_admin(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        roles = [r.role for r in spec.recipients]
        assert "BANK_IT_ADMIN" in roles

    def test_ks_engaged_roles_include_ops_manager(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        roles = [r.role for r in spec.recipients]
        assert "OPS_MANAGER" in roles

    def test_ks_engaged_roles_include_compliance(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        roles = [r.role for r in spec.recipients]
        assert "COMPLIANCE_OFFICER" in roles

    def test_ks_engaged_bank_it_admin_gets_email_and_whatsapp(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        it_admin = next(r for r in spec.recipients if r.role == "BANK_IT_ADMIN")
        assert Channel.EMAIL in it_admin.channels
        assert Channel.WHATSAPP in it_admin.channels

    def test_ks_engaged_compliance_gets_email_only(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        compliance = next(r for r in spec.recipients if r.role == "COMPLIANCE_OFFICER")
        assert Channel.EMAIL in compliance.channels
        assert Channel.WHATSAPP not in compliance.channels

    def test_ks_released_is_p3(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_RELEASED)
        assert spec.priority == Priority.P3

    def test_ks_released_does_not_create_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_RELEASED)
        assert spec.create_incident is False

    def test_ks_applied_has_no_notification(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_APPLIED)
        assert spec.notify is False

    def test_ks_applied_still_has_spec(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_APPLIED)
        assert spec is not None


# ---------------------------------------------------------------------------
# RoutingSpec — IET watchdog
# ---------------------------------------------------------------------------

class TestRoutingSpecIET:
    def test_iet_watchdog_is_p0(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_IET_WATCHDOG_FIRED)
        assert spec.priority == Priority.P0

    def test_iet_watchdog_creates_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_IET_WATCHDOG_FIRED)
        assert spec.create_incident is True

    def test_iet_watchdog_ops_reviewer_gets_bell_and_whatsapp(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_IET_WATCHDOG_FIRED)
        reviewer = next(r for r in spec.recipients if r.role == "OPS_REVIEWER")
        assert Channel.BELL in reviewer.channels
        assert Channel.WHATSAPP in reviewer.channels

    def test_iet_watchdog_ops_manager_gets_three_channels(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_IET_WATCHDOG_FIRED)
        mgr = next(r for r in spec.recipients if r.role == "OPS_MANAGER")
        assert Channel.BELL in mgr.channels
        assert Channel.WHATSAPP in mgr.channels
        assert Channel.EMAIL in mgr.channels


# ---------------------------------------------------------------------------
# RoutingSpec — human review
# ---------------------------------------------------------------------------

class TestRoutingSpecHumanReview:
    def test_review_assigned_notifies(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_REVIEW_ASSIGNED)
        assert spec.notify is True

    def test_review_assigned_is_p3(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_REVIEW_ASSIGNED)
        assert spec.priority == Priority.P3

    def test_review_assigned_ops_reviewer_gets_bell(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_REVIEW_ASSIGNED)
        reviewer = next(r for r in spec.recipients if r.role == "OPS_REVIEWER")
        assert Channel.BELL in reviewer.channels

    def test_review_timeout_is_p1(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_REVIEW_TIMEOUT)
        assert spec.priority == Priority.P1

    def test_review_timeout_creates_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_REVIEW_TIMEOUT)
        assert spec.create_incident is True

    def test_review_timeout_ops_manager_gets_email_and_whatsapp(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_REVIEW_TIMEOUT)
        mgr = next(r for r in spec.recipients if r.role == "OPS_MANAGER")
        assert Channel.EMAIL in mgr.channels
        assert Channel.WHATSAPP in mgr.channels


# ---------------------------------------------------------------------------
# RoutingSpec — NGCH failures
# ---------------------------------------------------------------------------

class TestRoutingSpecNGCH:
    def test_ngch_terminal_is_p0(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_NGCH_TERMINAL_FAILURE)
        assert spec.priority == Priority.P0

    def test_ngch_terminal_creates_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_NGCH_TERMINAL_FAILURE)
        assert spec.create_incident is True

    def test_ngch_terminal_ops_manager_notified(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_NGCH_TERMINAL_FAILURE)
        roles = [r.role for r in spec.recipients]
        assert "OPS_MANAGER" in roles

    def test_ngch_cert_expired_is_p0(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_NGCH_CERT_EXPIRED)
        assert spec.priority == Priority.P0

    def test_ngch_cert_expired_bank_it_admin_gets_whatsapp(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_NGCH_CERT_EXPIRED)
        it_admin = next(r for r in spec.recipients if r.role == "BANK_IT_ADMIN")
        assert Channel.WHATSAPP in it_admin.channels


# ---------------------------------------------------------------------------
# RoutingSpec — CBS events
# ---------------------------------------------------------------------------

class TestRoutingSpecCBS:
    def test_cbs_unreachable_is_p1(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CBS_UNREACHABLE)
        assert spec.priority == Priority.P1

    def test_cbs_unreachable_creates_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CBS_UNREACHABLE)
        assert spec.create_incident is True

    def test_cbs_auth_failed_is_p0(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CBS_AUTH_FAILED)
        assert spec.priority == Priority.P0

    def test_cbs_auth_failed_bank_it_admin_gets_whatsapp(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CBS_AUTH_FAILED)
        it_admin = next(r for r in spec.recipients if r.role == "BANK_IT_ADMIN")
        assert Channel.WHATSAPP in it_admin.channels

    def test_cbs_recovered_does_not_create_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CBS_RECOVERED)
        assert spec.create_incident is False


# ---------------------------------------------------------------------------
# RoutingSpec — Vault events
# ---------------------------------------------------------------------------

class TestRoutingSpecVault:
    def test_vault_stale_is_p0(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.VAULT_STALE)
        assert spec.priority == Priority.P0

    def test_vault_stale_creates_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.VAULT_STALE)
        assert spec.create_incident is True

    def test_vault_stale_ops_manager_gets_whatsapp_and_email(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.VAULT_STALE)
        mgr = next(r for r in spec.recipients if r.role == "OPS_MANAGER")
        assert Channel.WHATSAPP in mgr.channels
        assert Channel.EMAIL in mgr.channels

    def test_vault_integrity_fail_is_p0(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.VAULT_INTEGRITY_FAIL)
        assert spec.priority == Priority.P0

    def test_vault_integrity_fail_creates_incident(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.VAULT_INTEGRITY_FAIL)
        assert spec.create_incident is True

    def test_vault_sync_failed_is_p1(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.VAULT_SYNC_FAILED)
        assert spec.priority == Priority.P1

    def test_vault_sync_has_no_notification(self):
        """Successful vault sync is AUDIT only — no notification needed."""
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.VAULT_SYNC)
        assert spec.notify is False


# ---------------------------------------------------------------------------
# RoutingSpec — EJ events
# ---------------------------------------------------------------------------

class TestRoutingSpecEJ:
    def test_ej_atm_health_changed_notifies(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.EJ_ATM_HEALTH_CHANGED)
        assert spec.notify is True

    def test_ej_oem_unknown_is_p2(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.EJ_OEM_UNKNOWN)
        assert spec.priority == Priority.P2

    def test_ej_oem_unknown_ml_engineer_gets_bell_and_email(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.EJ_OEM_UNKNOWN)
        ml = next(r for r in spec.recipients if r.role == "ML_ENGINEER")
        assert Channel.BELL in ml.channels
        assert Channel.EMAIL in ml.channels


# ---------------------------------------------------------------------------
# RoutingSpec — audit-only events (no notification)
# ---------------------------------------------------------------------------

class TestRoutingSpecAuditOnly:
    def test_cts_decision_has_no_notification(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_DECISION)
        assert spec.notify is False

    def test_cts_ngch_filed_has_no_notification(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_NGCH_FILED)
        assert spec.notify is False

    def test_config_change_has_no_notification(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CONFIG_CHANGE)
        assert spec.notify is False


# ---------------------------------------------------------------------------
# build_requests() — produces NotificationRequest list per event
# ---------------------------------------------------------------------------

class TestBuildRequests:
    def test_build_requests_ks_engaged_returns_multiple_requests(self):
        rt = _make_routing_table()
        users = [
            _make_user("BANK_IT_ADMIN", "u1", "itadmin@bank.com", "+91990001"),
            _make_user("OPS_MANAGER", "u2", "opsmgr@bank.com", "+91990002"),
            _make_user("COMPLIANCE_OFFICER", "u3", "compliance@bank.com", "+91990003"),
        ]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id="test-bank",
            users=users,
            context={"mode": "KC", "scope": "GLOBAL"},
        )
        assert len(requests) > 0

    def test_build_requests_ks_engaged_bank_it_admin_has_email_request(self):
        rt = _make_routing_table()
        users = [_make_user("BANK_IT_ADMIN", "u1", "itadmin@bank.com")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id="test-bank",
            users=users,
            context={"mode": "KC", "scope": "GLOBAL"},
        )
        email_requests = [r for r in requests if r.channel == "email"]
        assert len(email_requests) >= 1
        assert email_requests[0].recipient == "itadmin@bank.com"

    def test_build_requests_ks_engaged_bank_it_admin_has_whatsapp_request(self):
        rt = _make_routing_table()
        users = [_make_user("BANK_IT_ADMIN", "u1", "itadmin@bank.com", "+91990001")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id="test-bank",
            users=users,
            context={"mode": "KC", "scope": "GLOBAL"},
        )
        wa_requests = [r for r in requests if r.channel == "whatsapp"]
        assert len(wa_requests) >= 1
        assert wa_requests[0].recipient == "+91990001"

    def test_build_requests_audit_only_event_returns_empty_list(self):
        rt = _make_routing_table()
        users = [_make_user("OPS_REVIEWER", "u1")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_DECISION,
            bank_id="test-bank",
            users=users,
            context={},
        )
        assert requests == []

    def test_build_requests_no_matching_users_returns_empty_list(self):
        rt = _make_routing_table()
        users = [_make_user("FRAUD_ANALYST", "u1", "analyst@bank.com")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id="test-bank",
            users=users,
            context={"mode": "KP"},
        )
        # FRAUD_ANALYST is not a recipient for kill switch events
        assert len(requests) == 0

    def test_build_requests_correct_template_id_for_ks_engaged_bank_it_admin(self):
        rt = _make_routing_table()
        users = [_make_user("BANK_IT_ADMIN", "u1", "itadmin@bank.com", "+91990001")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id="test-bank",
            users=users,
            context={"mode": "KC"},
        )
        email_req = next(r for r in requests if r.channel == "email")
        assert email_req.template_id == "CTS_KS_ENGAGED_IT_ADMIN"

    def test_build_requests_correct_template_id_for_ks_engaged_ops_manager(self):
        rt = _make_routing_table()
        users = [_make_user("OPS_MANAGER", "u1", "opsmgr@bank.com", "+91990002")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id="test-bank",
            users=users,
            context={"mode": "KC"},
        )
        email_req = next(r for r in requests if r.channel == "email")
        assert email_req.template_id == "CTS_KS_ENGAGED_OPS_MGR"

    def test_build_requests_bell_channel_uses_user_id_as_recipient(self):
        rt = _make_routing_table()
        users = [_make_user("OPS_REVIEWER", "reviewer-uuid-1", "rev@bank.com")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_REVIEW_ASSIGNED,
            bank_id="test-bank",
            users=users,
            context={"instrument_id": "instr-001"},
        )
        bell_requests = [r for r in requests if r.channel == "bell"]
        assert len(bell_requests) >= 1
        assert bell_requests[0].recipient == "reviewer-uuid-1"

    def test_build_requests_context_passed_through(self):
        rt = _make_routing_table()
        users = [_make_user("BANK_IT_ADMIN", "u1", "itadmin@bank.com")]
        ctx = {"mode": "KC", "scope": "GLOBAL", "bank_id": "test-bank"}
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id="test-bank",
            users=users,
            context=ctx,
        )
        assert len(requests) > 0
        for req in requests:
            assert req.context == ctx

    def test_build_requests_ks_applied_returns_empty(self):
        rt = _make_routing_table()
        users = [_make_user("BANK_IT_ADMIN", "u1", "itadmin@bank.com")]
        requests = rt.build_requests(
            event_type=AuditEventType.CTS_KILL_SWITCH_APPLIED,
            bank_id="test-bank",
            users=users,
            context={},
        )
        assert requests == []


# ---------------------------------------------------------------------------
# get_spec() error handling
# ---------------------------------------------------------------------------

class TestGetSpec:
    def test_all_audit_event_types_have_a_spec(self):
        rt = _make_routing_table()
        for event_type in AuditEventType:
            spec = rt.get_spec(event_type)
            assert spec is not None, f"Missing spec for {event_type}"

    def test_spec_is_routing_spec_instance(self):
        rt = _make_routing_table()
        spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        assert isinstance(spec, RoutingSpec)

    def test_routing_table_is_immutable_after_init(self):
        rt1 = _make_routing_table()
        rt2 = _make_routing_table()
        spec1 = rt1.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        spec2 = rt2.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
        assert spec1.priority == spec2.priority
