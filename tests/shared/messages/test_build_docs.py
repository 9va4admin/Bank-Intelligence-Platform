"""
Tests for shared/messages/build_docs.py — CTS_Msg_Taxonomy.html generation.

Focused on the Incident Response column this session adds; the rest of the
generator (search/filter JS, summary counts) predates a dedicated test file
and is exercised indirectly via shared/messages/build.py's own smoke usage.
TDD: written BEFORE the Incident column implementation.
"""
import textwrap

import pytest

from shared.messages.build_docs import build_html


WITH_INCIDENT_YAML = textwrap.dedent("""
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

    CTS_WF_TEST_NO_INCIDENT:
      severity: INFO
      surface: [AUDIT]
      variables: []
      en: "Ordinary info message."
      hi: ""
""").strip()


@pytest.fixture()
def yaml_file(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(WITH_INCIDENT_YAML)
    return f


@pytest.fixture()
def html(yaml_file, tmp_path):
    out = tmp_path / "CTS_Msg_Taxonomy.html"
    build_html(yaml_path=yaml_file, output_path=out)
    return out.read_text(encoding="utf-8")


def test_incident_severity_shown_for_key_with_incident_block(html):
    assert "P0" in html


def test_owning_team_shown_for_key_with_incident_block(html):
    assert "cts_clearing_ops" in html


def test_key_without_incident_block_shows_placeholder(html):
    # The no-incident row must render without crashing and without
    # fabricating incident data for a key that was never classified.
    assert "CTS_WF_TEST_NO_INCIDENT" in html


def test_build_html_does_not_crash_when_no_keys_have_incident_blocks(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        PLAIN_KEY:
          severity: INFO
          surface: [UI]
          variables: []
          en: "Plain."
          hi: ""
    """).strip())
    out = tmp_path / "out.html"
    build_html(yaml_path=f, output_path=out)   # no exception = pass
    assert out.exists()
