"""
Tests for shared/messages/build_alerts.py — generates a PrometheusRule CRD
from every messages.yaml key that carries a complete incident: block.

TDD: written BEFORE the implementation.
"""
import textwrap

import pytest
import yaml

from shared.messages.build_alerts import build_alert_rules


IMMEDIATE_YAML = textwrap.dedent("""
    CTS_WF_TEST_CRITICAL:
      severity: CRITICAL
      surface: [UI, AUDIT, NOTIFICATION]
      variables: []
      en: "Something critical happened."
      hi: ""
      incident:
        incident_class: SAFETY_BOUNDARY
        default_severity: P0
        escalation_trigger: IMMEDIATE
        owning_team: cts_clearing_ops
        regulatory_reportable: true
        auto_close_eligible: false
        runbook_ref: "runbooks/cts/test-critical.md"

    PLATFORM_TEST_NO_INCIDENT:
      severity: INFO
      surface: [AUDIT]
      variables: []
      en: "Ordinary info message — no incident block."
      hi: ""

    CTS_WF_TEST_THRESHOLD:
      severity: ERROR
      surface: [UI, AUDIT, NOTIFICATION]
      variables: []
      en: "A dependency degraded."
      hi: ""
      incident:
        incident_class: EXPECTED_DEGRADATION
        default_severity: P2
        escalation_trigger: THRESHOLD
        threshold: { count: 5, window_seconds: 300 }
        owning_team: cts_ai_platform
        regulatory_reportable: false
        auto_close_eligible: true
        runbook_ref: "runbooks/cts/test-threshold.md"

    EJ_TEST_LOW_SEV:
      severity: WARN
      surface: [UI]
      variables: []
      en: "EJ minor issue."
      hi: ""
      incident:
        incident_class: STRUCTURAL
        default_severity: P4
        escalation_trigger: IMMEDIATE
        owning_team: ej_ops
        regulatory_reportable: false
        auto_close_eligible: true
        runbook_ref: "runbooks/ej/test-low.md"
""").strip()


@pytest.fixture()
def yaml_file(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(IMMEDIATE_YAML, encoding="utf-8")
    return f


@pytest.fixture()
def generated(yaml_file, tmp_path):
    out = tmp_path / "generated-incident-alerts.yaml"
    build_alert_rules(yaml_path=yaml_file, output_path=out)
    return yaml.safe_load(out.read_text())


def _all_rules(doc):
    rules = []
    for group in doc["spec"]["groups"]:
        rules.extend(group["rules"])
    return rules


def _rule_for(doc, alert_name):
    for rule in _all_rules(doc):
        if rule["alert"] == alert_name:
            return rule
    raise AssertionError(f"no rule named {alert_name}")


class TestStructure:
    def test_top_level_crd_shape(self, generated):
        assert generated["apiVersion"] == "monitoring.coreos.com/v1"
        assert generated["kind"] == "PrometheusRule"
        assert generated["metadata"]["name"] == "astra-incident-alerts"

    def test_keys_without_incident_block_are_skipped(self, generated):
        names = [r["alert"] for r in _all_rules(generated)]
        assert not any("NO_INCIDENT" in n for n in names)
        assert len(names) == 3   # the 3 keys that DO carry an incident: block

    def test_writes_output_file(self, tmp_path, yaml_file):
        out = tmp_path / "sub" / "generated-incident-alerts.yaml"
        build_alert_rules(yaml_path=yaml_file, output_path=out)
        assert out.exists()


class TestImmediateRule:
    def test_immediate_key_fires_with_zero_grace_period(self, generated):
        rule = _rule_for(generated, "CTSWFTESTCRITICAL")
        assert rule["for"] == "0s"

    def test_immediate_key_expr_uses_increase_over_5m(self, generated):
        rule = _rule_for(generated, "CTSWFTESTCRITICAL")
        assert 'message_key="CTS_WF_TEST_CRITICAL"' in rule["expr"]
        assert "[5m]" in rule["expr"]
        assert "> 0" in rule["expr"]


class TestThresholdRule:
    def test_threshold_key_expr_uses_configured_window_and_count(self, generated):
        rule = _rule_for(generated, "CTSWFTESTTHRESHOLD")
        assert 'message_key="CTS_WF_TEST_THRESHOLD"' in rule["expr"]
        assert "[300s]" in rule["expr"]
        assert "> 5" in rule["expr"]
        assert rule["for"] == "0s"


class TestLabelsAndAnnotations:
    def test_severity_p0_maps_to_critical(self, generated):
        rule = _rule_for(generated, "CTSWFTESTCRITICAL")
        assert rule["labels"]["severity"] == "critical"

    def test_severity_p2_maps_to_warning(self, generated):
        rule = _rule_for(generated, "CTSWFTESTTHRESHOLD")
        assert rule["labels"]["severity"] == "warning"

    def test_severity_p4_maps_to_info(self, generated):
        rule = _rule_for(generated, "EJTESTLOWSEV")
        assert rule["labels"]["severity"] == "info"

    def test_module_label_derived_from_key_prefix_cts(self, generated):
        rule = _rule_for(generated, "CTSWFTESTCRITICAL")
        assert rule["labels"]["module"] == "cts"

    def test_module_label_derived_from_key_prefix_ej(self, generated):
        rule = _rule_for(generated, "EJTESTLOWSEV")
        assert rule["labels"]["module"] == "ej"

    def test_owning_team_label_present(self, generated):
        rule = _rule_for(generated, "CTSWFTESTTHRESHOLD")
        assert rule["labels"]["owning_team"] == "cts_ai_platform"

    def test_incident_class_label_present(self, generated):
        rule = _rule_for(generated, "CTSWFTESTCRITICAL")
        assert rule["labels"]["incident_class"] == "SAFETY_BOUNDARY"

    def test_annotations_include_runbook_ref(self, generated):
        rule = _rule_for(generated, "CTSWFTESTCRITICAL")
        assert "runbooks/cts/test-critical.md" in rule["annotations"]["description"]

    def test_annotations_include_message_text(self, generated):
        rule = _rule_for(generated, "CTSWFTESTCRITICAL")
        assert "Something critical happened" in rule["annotations"]["description"]


class TestGrouping:
    def test_rules_grouped_by_owning_team(self, generated):
        group_names = [g["name"] for g in generated["spec"]["groups"]]
        assert "cts_clearing_ops" in group_names
        assert "cts_ai_platform" in group_names
        assert "ej_ops" in group_names
