"""
Tests for MessageRegistry — single-file YAML, Redis-backed, local cache.

Run: pytest tests/shared/messages/test_registry.py -v
"""
import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.messages.registry import (
    MessageRegistry,
    MessageEntry,
    IncidentMetadata,
    UnknownMessageKey,
    MissingVariable,
    REDIS_LOCALES_KEY,
    REDIS_MSG_PREFIX,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

MESSAGES_YAML = textwrap.dedent("""
    TEST_WORKFLOW_RECEIVED:
      severity: INFO
      surface: [UI, AUDIT]
      variables: [instrument_id, bank]
      en: "Cheque {instrument_id} received from {bank}."
      hi: ""

    TEST_WORKFLOW_CONFIRMED:
      severity: INFO
      surface: [UI, AUDIT, NOTIFICATION]
      variables: [instrument_id]
      en: "Cheque {instrument_id} confirmed and filed."
      hi: ""

    TEST_WORKFLOW_VAULT_MISS:
      severity: WARN
      surface: [UI, AUDIT]
      variables: [account_display]
      en: "Vault miss — {account_display} has no signature specimen."
      hi: ""

    TEST_AUTH_LOGIN_SUCCESS:
      severity: INFO
      surface: [AUDIT]
      variables: [display_name, role]
      en: "Login successful — {display_name} ({role})."
      hi: ""

    TEST_AUTH_ACCESS_DENIED:
      severity: ERROR
      surface: [UI, AUDIT]
      variables: [role, action]
      en: "Access denied — {role} cannot perform {action}."
      hi: ""
""").strip()


@pytest.fixture()
def messages_file(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(MESSAGES_YAML, encoding="utf-8")
    return f


@pytest.fixture()
def registry(messages_file):
    return MessageRegistry(messages_file=messages_file)


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_get_returns_formatted_message(registry):
    result = registry.get("TEST_WORKFLOW_RECEIVED", instrument_id="CTS-001", bank="HDFC")
    assert result == "Cheque CTS-001 received from HDFC."


def test_non_ascii_characters_load_correctly(tmp_path):
    """Regression: messages.yaml is full of em-dashes and ₹ throughout real
    entries. Reading the file without an explicit encoding silently mis-
    decodes them on this machine's default cp1252 locale (Windows) --
    every message containing one would render corrupted at runtime."""
    f = tmp_path / "messages.yaml"
    f.write_text(
        'UNICODE_KEY:\n'
        '  severity: INFO\n'
        '  surface: [UI]\n'
        '  variables: [amount]\n'
        '  en: "Account frozen — balance ₹5,000 held."\n'
        '  hi: ""\n',
        encoding="utf-8",
    )
    reg = MessageRegistry(messages_file=f)
    result = reg.get("UNICODE_KEY", amount="5000")
    assert "—" in result
    assert "₹" in result


def test_get_no_extra_variables(registry):
    result = registry.get("TEST_WORKFLOW_CONFIRMED", instrument_id="CTS-002")
    assert "CTS-002" in result and "filed" in result


def test_get_entry_returns_en_metadata(registry):
    entry = registry.get_entry("TEST_AUTH_ACCESS_DENIED")
    assert isinstance(entry, MessageEntry)
    assert entry.severity == "ERROR"
    assert "UI" in entry.surface
    assert "role" in entry.variables
    assert "action" in entry.variables


def test_keys_returns_all_en_keys(registry):
    keys = registry.keys()
    assert "TEST_WORKFLOW_RECEIVED" in keys
    assert "TEST_AUTH_LOGIN_SUCCESS" in keys
    assert len(keys) == 5


def test_locales_returns_all_loaded(registry):
    assert set(registry.locales()) == {"en", "hi"}


def test_get_hi_stub_returns_empty_string(registry):
    result = registry.get("TEST_WORKFLOW_RECEIVED", locale="hi", instrument_id="X", bank="Y")
    assert result == ""


# ── Fallback ──────────────────────────────────────────────────────────────────

def test_unknown_locale_falls_back_to_en(registry):
    result = registry.get("TEST_AUTH_LOGIN_SUCCESS", locale="ta", display_name="Priya", role="ops")
    assert "Priya" in result


# ── Error handling ─────────────────────────────────────────────────────────────

def test_unknown_key_raises(registry):
    with pytest.raises(UnknownMessageKey, match="DOES_NOT_EXIST"):
        registry.get("DOES_NOT_EXIST")


def test_missing_variable_raises(registry):
    with pytest.raises(MissingVariable, match="instrument_id"):
        registry.get("TEST_WORKFLOW_RECEIVED", bank="HDFC")


# ── Validation ─────────────────────────────────────────────────────────────────

def test_validate_passes_on_valid_file(registry):
    assert registry.validate() == []


def test_validate_detects_blank_en_text(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        BLANK_KEY:
          severity: INFO
          surface: [UI]
          variables: []
          en: ""
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("BLANK_KEY" in e for e in errors)


def test_validate_detects_undeclared_variable(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        BAD_KEY:
          severity: INFO
          surface: [UI]
          variables: [name]
          en: "Hello {name} and {undeclared}."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("undeclared" in e for e in errors)


def test_validate_detects_unused_declared_variable(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        UNUSED_VAR_KEY:
          severity: INFO
          surface: [UI]
          variables: [name, unused]
          en: "Hello {name}."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("unused" in e for e in errors)


def test_validate_detects_missing_locale_key(tmp_path):
    # In the single-file format, a missing locale is detected by explicitly
    # building the registry with a cache that has a key in en but not in hi.
    # We simulate this by calling validate() on a registry with a manually
    # constructed cache gap.
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        KEY_A:
          severity: INFO
          surface: [UI]
          variables: []
          en: "Message A."
          hi: ""
        KEY_B:
          severity: INFO
          surface: [UI]
          variables: []
          en: "Message B."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    # Manually remove KEY_B from the hi cache to simulate a missing stub
    del reg._cache["hi"]["KEY_B"]
    errors = reg.validate()
    assert any("KEY_B" in e and "hi" in e for e in errors)


def test_validate_invalid_severity(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        BAD_SEV:
          severity: VERBOSE
          surface: [UI]
          variables: []
          en: "Something."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("severity" in e and "VERBOSE" in e for e in errors)


def test_validate_invalid_surface(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        BAD_SURFACE:
          severity: INFO
          surface: [UI, WEBHOOK]
          variables: []
          en: "Something."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("WEBHOOK" in e for e in errors)


# ── JSON build output ──────────────────────────────────────────────────────────

def test_build_writes_json_files(registry, tmp_path):
    registry.build(output_dir=tmp_path)
    assert (tmp_path / "messages.en.json").exists()
    assert (tmp_path / "messages.hi.json").exists()


def test_build_en_json_has_correct_structure(registry, tmp_path):
    registry.build(output_dir=tmp_path)
    data = json.loads((tmp_path / "messages.en.json").read_text())
    entry = data["TEST_WORKFLOW_RECEIVED"]
    assert entry["text"] == "Cheque {instrument_id} received from {bank}."
    assert entry["severity"] == "INFO"
    assert "UI" in entry["surface"]
    assert "instrument_id" in entry["variables"]


def test_build_en_json_has_all_keys(registry, tmp_path):
    registry.build(output_dir=tmp_path)
    data = json.loads((tmp_path / "messages.en.json").read_text())
    assert set(data.keys()) == set(registry.keys())


def test_build_hi_json_merges_en_metadata(registry, tmp_path):
    registry.build(output_dir=tmp_path)
    data = json.loads((tmp_path / "messages.hi.json").read_text())
    entry = data["TEST_WORKFLOW_RECEIVED"]
    assert entry["text"] == ""
    assert entry["severity"] == "INFO"
    assert "instrument_id" in entry["variables"]


# ── Redis-backed loading ───────────────────────────────────────────────────────

def _make_redis_mock(cache: dict[str, dict[str, str]]):
    """
    Build a mock Redis client that serves HGETALL and SMEMBERS from `cache`.
    cache = { "astra:messages:en": {"KEY": '{"text":"...","severity":"INFO",...}'}, ... }
    """
    mock = MagicMock()

    locales_key_data = {
        b"en" if locale == "en" else locale.encode()
        for locale in ["en", "hi"]
    }

    def smembers(key):
        if key == REDIS_LOCALES_KEY:
            return locales_key_data
        return set()

    def hgetall(key):
        raw = cache.get(key, {})
        return {k.encode(): v.encode() for k, v in raw.items()}

    mock.smembers.side_effect = smembers
    mock.hgetall.side_effect = hgetall
    mock.ping.return_value = True
    return mock


def test_registry_loads_from_redis_when_available(messages_file):
    en_entry = json.dumps({
        "text": "Cheque {instrument_id} received from {bank}.",
        "severity": "INFO",
        "surface": ["UI", "AUDIT"],
        "variables": ["instrument_id", "bank"],
    })
    hi_entry = json.dumps({
        "text": "",
        "severity": "INFO",
        "surface": ["UI", "AUDIT"],
        "variables": ["instrument_id", "bank"],
    })
    redis_cache = {
        f"{REDIS_MSG_PREFIX}en": {"TEST_WORKFLOW_RECEIVED": en_entry},
        f"{REDIS_MSG_PREFIX}hi": {"TEST_WORKFLOW_RECEIVED": hi_entry},
    }
    redis_mock = _make_redis_mock(redis_cache)
    reg = MessageRegistry(messages_file=messages_file, redis_client=redis_mock)

    result = reg.get("TEST_WORKFLOW_RECEIVED", instrument_id="CTS-001", bank="HDFC")
    assert result == "Cheque CTS-001 received from HDFC."


def test_registry_falls_back_to_yaml_when_redis_empty(messages_file):
    redis_mock = MagicMock()
    redis_mock.smembers.return_value = set()
    redis_mock.ping.return_value = True

    reg = MessageRegistry(messages_file=messages_file, redis_client=redis_mock)
    result = reg.get("TEST_WORKFLOW_RECEIVED", instrument_id="X", bank="Y")
    assert result == "Cheque X received from Y."


def test_build_pushes_to_redis(registry, tmp_path):
    redis_mock = MagicMock()
    pipe_mock = MagicMock()
    redis_mock.pipeline.return_value = pipe_mock
    pipe_mock.__enter__ = MagicMock(return_value=pipe_mock)
    pipe_mock.__exit__ = MagicMock(return_value=False)

    registry.build(output_dir=tmp_path, redis_client=redis_mock)

    redis_mock.pipeline.assert_called_once()
    pipe_mock.execute.assert_called_once()
    # At minimum: delete + sadd + per-locale delete + hset calls
    assert pipe_mock.hset.call_count > 0


# ── Incident metadata (error → incident linkage) ────────────────────────────

_IMMEDIATE_INCIDENT_YAML = textwrap.dedent("""
    CRIT_SAFETY_KEY:
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
        runbook_ref: "runbooks/cts/crit-safety-key.md"
""").strip()

_THRESHOLD_INCIDENT_YAML = textwrap.dedent("""
    ERR_DEGRADED_KEY:
      severity: ERROR
      surface: [UI, AUDIT, NOTIFICATION]
      variables: []
      en: "A dependency degraded."
      hi: ""
      incident:
        incident_class: EXPECTED_DEGRADATION
        default_severity: P1
        escalation_trigger: THRESHOLD
        threshold: { count: 5, window_seconds: 300 }
        owning_team: cts_clearing_ops
        regulatory_reportable: false
        auto_close_eligible: false
        runbook_ref: "runbooks/cts/err-degraded-key.md"
""").strip()


def test_get_entry_returns_none_incident_when_absent(registry):
    entry = registry.get_entry("TEST_WORKFLOW_VAULT_MISS")
    assert entry.incident is None


def test_get_entry_parses_incident_block(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_IMMEDIATE_INCIDENT_YAML)
    reg = MessageRegistry(messages_file=f)

    entry = reg.get_entry("CRIT_SAFETY_KEY")

    assert isinstance(entry.incident, IncidentMetadata)
    assert entry.incident.incident_class == "SAFETY_BOUNDARY"
    assert entry.incident.default_severity == "P0"
    assert entry.incident.escalation_trigger == "IMMEDIATE"
    assert entry.incident.owning_team == "cts_clearing_ops"
    assert entry.incident.regulatory_reportable is True
    assert entry.incident.auto_close_eligible is False
    assert entry.incident.runbook_ref == "runbooks/cts/crit-safety-key.md"
    assert entry.incident.threshold is None


def test_get_entry_parses_threshold_block(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_THRESHOLD_INCIDENT_YAML)
    reg = MessageRegistry(messages_file=f)

    entry = reg.get_entry("ERR_DEGRADED_KEY")

    assert entry.incident.escalation_trigger == "THRESHOLD"
    assert entry.incident.threshold == {"count": 5, "window_seconds": 300}


def test_incident_metadata_survives_redis_round_trip(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_IMMEDIATE_INCIDENT_YAML)
    reg = MessageRegistry(messages_file=f)

    redis_mock = MagicMock()
    pipe_mock = MagicMock()
    redis_mock.pipeline.return_value = pipe_mock
    stored: dict[str, str] = {}

    def hset(key, field, value):
        stored[field] = value
    pipe_mock.hset.side_effect = hset

    reg.build(output_dir=tmp_path, redis_client=redis_mock)

    written = json.loads(stored["CRIT_SAFETY_KEY"])
    assert written["incident"]["incident_class"] == "SAFETY_BOUNDARY"
    assert written["incident"]["default_severity"] == "P0"

    # Now load a fresh registry purely from that Redis payload
    def smembers(key):
        return {b"en", b"hi"} if key == REDIS_LOCALES_KEY else set()

    def hgetall(key):
        if key.endswith(":en"):
            return {b"CRIT_SAFETY_KEY": stored["CRIT_SAFETY_KEY"].encode()}
        return {}

    reload_mock = MagicMock()
    reload_mock.smembers.side_effect = smembers
    reload_mock.hgetall.side_effect = hgetall

    reg2 = MessageRegistry(messages_file=f, redis_client=reload_mock)
    entry = reg2.get_entry("CRIT_SAFETY_KEY")
    assert entry.incident.incident_class == "SAFETY_BOUNDARY"
    assert entry.incident.escalation_trigger == "IMMEDIATE"


def test_incident_metadata_absent_from_browser_json_bundle(tmp_path):
    """The browser bundle is for UI text rendering only — internal ops
    routing (owning_team, runbook_ref) has no reason to ship to the frontend."""
    f = tmp_path / "messages.yaml"
    f.write_text(_IMMEDIATE_INCIDENT_YAML)
    reg = MessageRegistry(messages_file=f)
    reg.build(output_dir=tmp_path)

    data = json.loads((tmp_path / "messages.en.json").read_text())
    assert "incident" not in data["CRIT_SAFETY_KEY"]


# ── Incident validation ──────────────────────────────────────────────────────

def _base_incident_yaml(severity: str, **overrides) -> str:
    return _incident_yaml_for_key("SOME_KEY", severity, **overrides)


def test_validate_requires_incident_block_on_critical_keys(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        CRIT_NO_INCIDENT:
          severity: CRITICAL
          surface: [UI, AUDIT, NOTIFICATION]
          variables: []
          en: "Critical, but no incident block."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("CRIT_NO_INCIDENT" in e and "incident" in e for e in errors)


def test_validate_passes_when_critical_key_has_complete_incident_block(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_IMMEDIATE_INCIDENT_YAML)
    reg = MessageRegistry(messages_file=f)
    assert reg.validate() == []


def test_validate_incident_block_not_required_on_warn(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        WARN_NO_INCIDENT:
          severity: WARN
          surface: [UI]
          variables: []
          en: "Just a warning."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    assert reg.validate() == []


def test_validate_incident_block_not_required_on_error(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(textwrap.dedent("""
        ERROR_NO_INCIDENT:
          severity: ERROR
          surface: [UI]
          variables: []
          en: "Just an error."
          hi: ""
    """).strip())
    reg = MessageRegistry(messages_file=f)
    assert reg.validate() == []


def test_validate_incident_block_when_present_on_warn_must_be_well_formed(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml("WARN", incident_class="NOT_A_REAL_CLASS"))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("incident_class" in e and "NOT_A_REAL_CLASS" in e for e in errors)


def test_validate_detects_invalid_incident_class(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml("CRITICAL", incident_class="MADE_UP"))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("incident_class" in e and "MADE_UP" in e for e in errors)


def test_validate_detects_invalid_default_severity(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml("CRITICAL", default_severity="P9"))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("default_severity" in e and "P9" in e for e in errors)


def test_validate_detects_invalid_escalation_trigger(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml("CRITICAL", escalation_trigger="SOMETIMES"))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("escalation_trigger" in e and "SOMETIMES" in e for e in errors)


def test_validate_detects_invalid_owning_team(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml("CRITICAL", owning_team="nobody"))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("owning_team" in e and "nobody" in e for e in errors)


def test_validate_requires_threshold_when_escalation_trigger_is_threshold(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml("CRITICAL", escalation_trigger="THRESHOLD"))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("threshold" in e for e in errors)


def test_validate_accepts_threshold_when_escalation_trigger_is_threshold(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_THRESHOLD_INCIDENT_YAML)
    reg = MessageRegistry(messages_file=f)
    assert reg.validate() == []


def test_validate_detects_zero_threshold_count(tmp_path):
    f = tmp_path / "messages.yaml"
    text = _THRESHOLD_INCIDENT_YAML.replace("count: 5", "count: 0")
    f.write_text(text)
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("threshold" in e and "count" in e for e in errors)


def test_validate_detects_zero_threshold_window(tmp_path):
    f = tmp_path / "messages.yaml"
    text = _THRESHOLD_INCIDENT_YAML.replace("window_seconds: 300", "window_seconds: 0")
    f.write_text(text)
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("threshold" in e and "window_seconds" in e for e in errors)


def test_validate_never_condition_key_must_be_immediate(tmp_path):
    """Hard-coded safety-boundary allowlist: these keys can never be
    threshold-gated, regardless of what the YAML says."""
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml_for_key(
        "CTS_WF_IET_WATCHDOG_FIRED", "CRITICAL", escalation_trigger="THRESHOLD",
        threshold={"count": 5, "window_seconds": 300},
    ))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("CTS_WF_IET_WATCHDOG_FIRED" in e and "IMMEDIATE" in e for e in errors)


def test_validate_never_condition_key_must_be_regulatory_reportable(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml_for_key(
        "PLATFORM_AUDIT_WRITE_FAILED", "CRITICAL", regulatory_reportable=False,
    ))
    reg = MessageRegistry(messages_file=f)
    errors = reg.validate()
    assert any("PLATFORM_AUDIT_WRITE_FAILED" in e and "regulatory_reportable" in e for e in errors)


def test_validate_never_condition_key_passes_when_correctly_configured(tmp_path):
    f = tmp_path / "messages.yaml"
    f.write_text(_base_incident_yaml_for_key("PLATFORM_AUDIT_TAMPER_DETECTED", "CRITICAL"))
    reg = MessageRegistry(messages_file=f)
    assert reg.validate() == []


def _base_incident_yaml_for_key(key: str, severity: str, **overrides) -> str:
    return _incident_yaml_for_key(key, severity, **overrides)


def _incident_yaml_for_key(key: str, severity: str, **overrides) -> str:
    """Build a single-key messages.yaml fragment with an incident: block.

    Built as an explicit list of pre-indented lines rather than
    textwrap.dedent(f\"\"\"...{body}...\"\"\") — mixing a dedent'd template
    with an already-multi-line interpolated variable silently mis-indents
    every line of the variable after the first (dedent computes common
    indentation across the *whole* text, so a shallower embedded line drags
    every sibling line's indentation down with it), which produced YAML
    where the incident: sub-keys just fell out of the block entirely.
    """
    incident_fields = {
        "incident_class": "SAFETY_BOUNDARY",
        "default_severity": "P0",
        "escalation_trigger": "IMMEDIATE",
        "owning_team": "cts_clearing_ops",
        "regulatory_reportable": True,
        "auto_close_eligible": False,
        "runbook_ref": "runbooks/cts/x.md",
    }
    incident_fields.update(overrides)

    lines = [
        f"{key}:",
        f"  severity: {severity}",
        "  surface: [UI, AUDIT, NOTIFICATION]",
        "  variables: []",
        '  en: "Text."',
        '  hi: ""',
        "  incident:",
    ]
    for k, v in incident_fields.items():
        if isinstance(v, dict):
            lines.append(f"    {k}: {{ count: {v['count']}, window_seconds: {v['window_seconds']} }}")
        elif isinstance(v, str):
            lines.append(f"    {k}: {v!r}")
        else:
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def test_refresh_reloads_from_yaml(messages_file):
    reg = MessageRegistry(messages_file=messages_file)
    assert len(reg.keys()) == 5

    # Add a new key to the file
    extra = textwrap.dedent("""
        TEST_EXTRA_KEY:
          severity: INFO
          surface: [UI]
          variables: []
          en: "Extra message."
          hi: ""
    """)
    with messages_file.open("a") as f:
        f.write(extra)

    reg.refresh()
    assert len(reg.keys()) == 6
    assert reg.get("TEST_EXTRA_KEY") == "Extra message."
