"""
Tests for shared/incidents/signal.py — emit_incident_signal().

TDD: written BEFORE the implementation.

The counter is always injected in these tests (see otel_setup tests for why:
OTel's global MeterProvider can only be configured once per process, so
inspecting real recorded data through the global provider is inherently
order-dependent across a shared test session). Production code never passes
counter explicitly — see test_lazy_real_counter_path_does_not_raise.
"""
from unittest.mock import MagicMock, patch

import pytest

from shared.incidents.signal import emit_incident_signal
from shared.messages.registry import IncidentMetadata, MessageEntry, UnknownMessageKey


def _entry(key: str, incident: IncidentMetadata | None) -> MessageEntry:
    return MessageEntry(
        key=key, text="Text.", severity="CRITICAL", surface=["UI", "AUDIT"],
        variables=[], locale="en", incident=incident,
    )


_IMMEDIATE = IncidentMetadata(
    incident_class="SAFETY_BOUNDARY", default_severity="P0", escalation_trigger="IMMEDIATE",
    owning_team="cts_clearing_ops", regulatory_reportable=True, auto_close_eligible=False,
    runbook_ref="runbooks/cts/x.md",
)


class TestNoOpPaths:
    def test_noop_when_key_has_no_incident_block(self):
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", return_value=_entry("INFO_KEY", None)):
            emit_incident_signal("INFO_KEY", bank_id="test-bank", counter=counter)
        counter.add.assert_not_called()

    def test_noop_and_does_not_raise_for_unknown_key(self):
        """Signal emission is a fire-and-forget observability side-effect —
        it must never be able to break the caller's real workflow, even if
        the message key was mistyped or the registry lookup fails."""
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", side_effect=UnknownMessageKey("NOPE")):
            emit_incident_signal("NOPE", bank_id="test-bank", counter=counter)
        counter.add.assert_not_called()


class TestSignalEmission:
    def test_increments_counter_when_incident_block_present(self):
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", return_value=_entry("CRIT_KEY", _IMMEDIATE)):
            emit_incident_signal("CRIT_KEY", bank_id="saraswat-coop", counter=counter)
        counter.add.assert_called_once()

    def test_labels_include_message_key(self):
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", return_value=_entry("CRIT_KEY", _IMMEDIATE)):
            emit_incident_signal("CRIT_KEY", bank_id="saraswat-coop", counter=counter)
        _, kwargs_attrs = counter.add.call_args[0]
        assert kwargs_attrs["message_key"] == "CRIT_KEY"

    def test_labels_include_bank_id(self):
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", return_value=_entry("CRIT_KEY", _IMMEDIATE)):
            emit_incident_signal("CRIT_KEY", bank_id="saraswat-coop", counter=counter)
        _, attrs = counter.add.call_args[0]
        assert attrs["bank_id"] == "saraswat-coop"

    def test_labels_include_incident_class_severity_and_owning_team(self):
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", return_value=_entry("CRIT_KEY", _IMMEDIATE)):
            emit_incident_signal("CRIT_KEY", bank_id="saraswat-coop", counter=counter)
        _, attrs = counter.add.call_args[0]
        assert attrs["incident_class"] == "SAFETY_BOUNDARY"
        assert attrs["severity"] == "P0"
        assert attrs["owning_team"] == "cts_clearing_ops"

    def test_increments_by_exactly_one(self):
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", return_value=_entry("CRIT_KEY", _IMMEDIATE)):
            emit_incident_signal("CRIT_KEY", bank_id="saraswat-coop", counter=counter)
        amount, _ = counter.add.call_args[0]
        assert amount == 1

    def test_threshold_class_key_labels_correctly(self):
        threshold_meta = IncidentMetadata(
            incident_class="EXPECTED_DEGRADATION", default_severity="P1",
            escalation_trigger="THRESHOLD", owning_team="cts_clearing_ops",
            regulatory_reportable=False, auto_close_eligible=False,
            runbook_ref="runbooks/cts/y.md", threshold={"count": 5, "window_seconds": 300},
        )
        counter = MagicMock()
        with patch("shared.incidents.signal.get_entry", return_value=_entry("ERR_KEY", threshold_meta)):
            emit_incident_signal("ERR_KEY", bank_id="saraswat-coop", counter=counter)
        _, attrs = counter.add.call_args[0]
        assert attrs["severity"] == "P1"
        assert attrs["incident_class"] == "EXPECTED_DEGRADATION"


class TestRealMeterPath:
    def test_lazy_real_counter_path_does_not_raise(self):
        """No counter injected — falls back to the real, lazily-created
        module-level OTel counter. Safe even with no configure_otel() call
        (the OTel API's default no-op provider handles that case)."""
        with patch("shared.incidents.signal.get_entry", return_value=_entry("CRIT_KEY", _IMMEDIATE)):
            emit_incident_signal("CRIT_KEY", bank_id="saraswat-coop")  # no exception = pass

    def test_lazy_counter_is_created_once_and_reused(self):
        import shared.incidents.signal as signal_module
        signal_module._counter = None  # reset module cache for a clean assertion

        with patch("shared.incidents.signal.get_entry", return_value=_entry("CRIT_KEY", _IMMEDIATE)):
            emit_incident_signal("CRIT_KEY", bank_id="b1")
            first = signal_module._counter
            emit_incident_signal("CRIT_KEY", bank_id="b2")
            second = signal_module._counter

        assert first is second
        assert first is not None
