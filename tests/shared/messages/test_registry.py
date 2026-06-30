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
    f.write_text(MESSAGES_YAML)
    return f


@pytest.fixture()
def registry(messages_file):
    return MessageRegistry(messages_file=messages_file)


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_get_returns_formatted_message(registry):
    result = registry.get("TEST_WORKFLOW_RECEIVED", instrument_id="CTS-001", bank="HDFC")
    assert result == "Cheque CTS-001 received from HDFC."


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
