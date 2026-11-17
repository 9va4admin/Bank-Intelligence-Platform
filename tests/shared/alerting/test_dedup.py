"""Which incident does an alert belong to, and does it open one or close one?"""
import pytest

from shared.alerting.incidents import dedup_key_for, is_resolution


@pytest.mark.parametrize("event_type", ["COMPONENT_DOWN", "COMPONENT_REMINDER", "COMPONENT_RECOVERED"])
def test_down_reminders_and_recovery_share_one_incident(event_type):
    assert dedup_key_for(event_type, "redis") == "component:redis:down"


@pytest.mark.parametrize("event_type", ["COMPONENT_SLOW", "COMPONENT_SLOW_CLEARED"])
def test_slow_and_its_clearing_share_one_incident_separate_from_down(event_type):
    assert dedup_key_for(event_type, "redis") == "component:redis:slow"


def test_other_checks_are_keyed_by_what_they_are_and_where():
    assert dedup_key_for("IET_BREACH_RISK", "") == "IET_BREACH_RISK:"
    assert dedup_key_for("SCANNER_BRANCH_OFFLINE", "fleet") == "SCANNER_BRANCH_OFFLINE:fleet"


def test_different_components_are_different_incidents():
    assert dedup_key_for("COMPONENT_DOWN", "redis") != dedup_key_for("COMPONENT_DOWN", "kafka")


def test_only_recoveries_close_an_incident():
    assert is_resolution("COMPONENT_RECOVERED") and is_resolution("COMPONENT_SLOW_CLEARED")
    assert not is_resolution("COMPONENT_DOWN") and not is_resolution("IET_BREACH_RISK")
