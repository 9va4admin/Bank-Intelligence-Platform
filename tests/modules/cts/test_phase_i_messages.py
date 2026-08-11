"""
Phase I — Messages registry and AuditEventType coverage tests.

Validates that all new messages added for Phases D–F are correctly
registered in messages.yaml with proper severity, surface, and variable
declarations. Also verifies AuditEventType enum has all required entries.
"""
import pytest


# ─── Helper ───────────────────────────────────────────────────────────────────

def _entry(key, locale="en"):
    from shared.messages import get_entry
    return get_entry(key, locale=locale)


def _yaml_raw():
    """Load raw YAML once — for testing hi stub and variables fields."""
    import yaml
    from pathlib import Path
    path = Path(__file__).parents[3] / "shared" / "messages" / "locales" / "messages.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ─── 1. Hold messages ─────────────────────────────────────────────────────────

class TestHoldMessages:
    def test_hold_placed_message_exists(self):
        entry = _entry("CTS_WF_HOLD_PLACED")
        assert entry is not None

    def test_hold_placed_severity_warn(self):
        assert _entry("CTS_WF_HOLD_PLACED").severity == "WARN"

    def test_hold_placed_has_audit_surface(self):
        assert "AUDIT" in _entry("CTS_WF_HOLD_PLACED").surface

    def test_hold_placed_has_notification_surface(self):
        assert "NOTIFICATION" in _entry("CTS_WF_HOLD_PLACED").surface

    def test_hold_placed_variables_complete(self):
        vars_ = _entry("CTS_WF_HOLD_PLACED").variables
        for v in ["instrument_id", "held_by", "hold_reason", "iet_deadline"]:
            assert v in vars_, f"Missing variable '{v}' in CTS_WF_HOLD_PLACED"

    def test_hold_released_message_exists(self):
        assert _entry("CTS_WF_HOLD_RELEASED") is not None

    def test_hold_released_severity_info(self):
        assert _entry("CTS_WF_HOLD_RELEASED").severity == "INFO"

    def test_hold_released_has_audit_surface(self):
        assert "AUDIT" in _entry("CTS_WF_HOLD_RELEASED").surface

    def test_hold_released_variables_complete(self):
        vars_ = _entry("CTS_WF_HOLD_RELEASED").variables
        for v in ["instrument_id", "released_by", "branch_recommendation"]:
            assert v in vars_

    def test_hold_expired_message_exists(self):
        assert _entry("CTS_WF_HOLD_EXPIRED") is not None

    def test_hold_expired_severity_critical(self):
        assert _entry("CTS_WF_HOLD_EXPIRED").severity == "CRITICAL"

    def test_hold_expired_has_all_surfaces(self):
        surfaces = _entry("CTS_WF_HOLD_EXPIRED").surface
        for s in ["UI", "AUDIT", "NOTIFICATION"]:
            assert s in surfaces


# ─── 2. Hold escalation messages ─────────────────────────────────────────────

class TestHoldEscalationMessages:
    def test_hold_escalation_30min_exists(self):
        assert _entry("CTS_HOLD_ESCALATION_30MIN") is not None

    def test_hold_escalation_30min_severity_warn(self):
        assert _entry("CTS_HOLD_ESCALATION_30MIN").severity == "WARN"

    def test_hold_escalation_30min_has_notification(self):
        assert "NOTIFICATION" in _entry("CTS_HOLD_ESCALATION_30MIN").surface

    def test_hold_escalation_critical_exists(self):
        assert _entry("CTS_HOLD_ESCALATION_CRITICAL") is not None

    def test_hold_escalation_critical_severity_critical(self):
        assert _entry("CTS_HOLD_ESCALATION_CRITICAL").severity == "CRITICAL"

    def test_hold_escalation_p0_exists(self):
        assert _entry("CTS_HOLD_ESCALATION_P0") is not None

    def test_hold_escalation_p0_severity_critical(self):
        assert _entry("CTS_HOLD_ESCALATION_P0").severity == "CRITICAL"

    def test_hold_escalation_p0_has_notification(self):
        assert "NOTIFICATION" in _entry("CTS_HOLD_ESCALATION_P0").surface

    def test_critical_messages_have_incident_block(self):
        for key in ["CTS_WF_HOLD_EXPIRED", "CTS_HOLD_ESCALATION_CRITICAL", "CTS_HOLD_ESCALATION_P0"]:
            entry = _entry(key)
            assert entry.incident is not None, f"Missing incident block on {key}"

    def test_hold_expired_incident_is_p0(self):
        assert _entry("CTS_WF_HOLD_EXPIRED").incident.default_severity == "P0"

    def test_hold_escalation_p0_incident_is_p0(self):
        assert _entry("CTS_HOLD_ESCALATION_P0").incident.default_severity == "P0"

    def test_hold_escalation_critical_incident_is_p1(self):
        assert _entry("CTS_HOLD_ESCALATION_CRITICAL").incident.default_severity == "P1"


# ─── 3. Allocation messages ───────────────────────────────────────────────────

class TestAllocationMessages:
    def test_alloc_claimed_exists(self):
        assert _entry("CTS_ALLOC_CLAIMED") is not None

    def test_alloc_claimed_severity_info(self):
        assert _entry("CTS_ALLOC_CLAIMED").severity == "INFO"

    def test_alloc_unclaimed_exists(self):
        assert _entry("CTS_ALLOC_UNCLAIMED") is not None

    def test_alloc_auto_assigned_exists(self):
        assert _entry("CTS_ALLOC_AUTO_ASSIGNED") is not None

    def test_alloc_auto_assigned_has_allocation_mode_variable(self):
        assert "allocation_mode" in _entry("CTS_ALLOC_AUTO_ASSIGNED").variables

    def test_lock_acquired_exists(self):
        assert _entry("CTS_LOCK_ACQUIRED") is not None

    def test_lock_expired_severity_warn(self):
        assert _entry("CTS_LOCK_EXPIRED").severity == "WARN"


# ─── 4. Config change messages ────────────────────────────────────────────────

class TestConfigChangeMessages:
    def test_l3_submitted_exists(self):
        assert _entry("CTS_CONFIG_L3_SUBMITTED") is not None

    def test_l3_submitted_has_audit_and_notification(self):
        surfaces = _entry("CTS_CONFIG_L3_SUBMITTED").surface
        assert "AUDIT" in surfaces
        assert "NOTIFICATION" in surfaces

    def test_l3_approved_exists(self):
        assert _entry("CTS_CONFIG_L3_APPROVED") is not None

    def test_l3_rejected_exists(self):
        assert _entry("CTS_CONFIG_L3_REJECTED") is not None

    def test_l3_rejected_variables_include_reason(self):
        assert "reason" in _entry("CTS_CONFIG_L3_REJECTED").variables

    def test_l2_requested_exists(self):
        assert _entry("PLATFORM_CONFIG_L2_REQUESTED") is not None

    def test_l2_deployed_exists(self):
        assert _entry("PLATFORM_CONFIG_L2_DEPLOYED") is not None


# ─── 5. Queue tier routing message ───────────────────────────────────────────

class TestQueueTierMessages:
    def test_queue_tier_routed_exists(self):
        assert _entry("CTS_QUEUE_TIER_ROUTED") is not None

    def test_queue_tier_routed_severity_info(self):
        assert _entry("CTS_QUEUE_TIER_ROUTED").severity == "INFO"

    def test_queue_tier_routed_variables(self):
        vars_ = _entry("CTS_QUEUE_TIER_ROUTED").variables
        for v in ["instrument_id", "queue_tier", "kafka_topic"]:
            assert v in vars_


# ─── 6. AuditEventType enum ──────────────────────────────────────────────────

class TestAuditEventTypes:
    def test_cts_hold_placed_exists(self):
        from shared.audit.audit_event import AuditEventType
        assert hasattr(AuditEventType, "CTS_HOLD_PLACED")

    def test_cts_hold_released_exists(self):
        from shared.audit.audit_event import AuditEventType
        assert hasattr(AuditEventType, "CTS_HOLD_RELEASED")

    def test_cts_alloc_claimed_exists(self):
        from shared.audit.audit_event import AuditEventType
        assert hasattr(AuditEventType, "CTS_ALLOC_CLAIMED")

    def test_cts_alloc_unclaimed_exists(self):
        from shared.audit.audit_event import AuditEventType
        assert hasattr(AuditEventType, "CTS_ALLOC_UNCLAIMED")

    def test_cts_alloc_auto_assigned_exists(self):
        from shared.audit.audit_event import AuditEventType
        assert hasattr(AuditEventType, "CTS_ALLOC_AUTO_ASSIGNED")

    def test_all_required_event_types_are_enum_members(self):
        from shared.audit.audit_event import AuditEventType
        required = [
            "CTS_HOLD_PLACED",
            "CTS_HOLD_RELEASED",
            "CTS_ALLOC_CLAIMED",
            "CTS_ALLOC_UNCLAIMED",
            "CTS_ALLOC_AUTO_ASSIGNED",
        ]
        members = [m.name for m in AuditEventType]
        for name in required:
            assert name in members, f"AuditEventType.{name} missing"


# ─── 7. Hi stubs present on new messages ─────────────────────────────────────

class TestHiStubs:
    def test_new_messages_have_hi_stub(self):
        raw = _yaml_raw()
        new_keys = [
            "CTS_WF_HOLD_EXPIRED",
            "CTS_HOLD_ESCALATION_30MIN",
            "CTS_HOLD_ESCALATION_CRITICAL",
            "CTS_HOLD_ESCALATION_P0",
            "CTS_CONFIG_L3_SUBMITTED",
            "CTS_CONFIG_L3_APPROVED",
            "CTS_CONFIG_L3_REJECTED",
            "CTS_QUEUE_TIER_ROUTED",
        ]
        for key in new_keys:
            assert key in raw, f"{key} not in YAML"
            assert "hi" in raw[key], f"Missing 'hi' stub on {key}"

    def test_hi_stubs_are_empty_strings(self):
        raw = _yaml_raw()
        new_keys = [
            "CTS_WF_HOLD_EXPIRED",
            "CTS_HOLD_ESCALATION_30MIN",
        ]
        for key in new_keys:
            assert raw[key]["hi"] == "", f"{key} hi stub should be empty string"


# ─── 8. Message text formatting (spot-check) ─────────────────────────────────

class TestMessageText:
    def test_hold_placed_text_contains_placeholders(self):
        entry = _entry("CTS_WF_HOLD_PLACED")
        assert "{instrument_id}" in entry.text
        assert "{held_by}" in entry.text
        assert "{iet_deadline}" in entry.text

    def test_hold_escalation_p0_text_mentions_5_minutes(self):
        entry = _entry("CTS_HOLD_ESCALATION_P0")
        assert "5 minutes" in entry.text.lower() or "5-minute" in entry.text.lower()

    def test_hold_escalation_critical_text_mentions_60_minutes(self):
        entry = _entry("CTS_HOLD_ESCALATION_CRITICAL")
        assert "60 minutes" in entry.text

    def test_l3_submitted_text_mentions_pending(self):
        entry = _entry("CTS_CONFIG_L3_SUBMITTED")
        assert "pending" in entry.text.lower()
