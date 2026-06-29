"""
Tests for MessageRegistry.

Run: pytest tests/shared/messages/test_registry.py -v
"""
import json
import textwrap
from pathlib import Path

import pytest

from shared.messages.registry import MessageRegistry, MessageEntry, UnknownMessageKey, MissingVariable


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def locales_dir(tmp_path):
    """Minimal locale fixture: two domains in en, partial hi stubs."""
    en = tmp_path / "en"
    hi = tmp_path / "hi"
    en.mkdir(); hi.mkdir()

    (en / "workflow.yaml").write_text(textwrap.dedent("""
        TEST_WORKFLOW_RECEIVED:
          text: "Cheque {instrument_id} received from {bank}."
          severity: INFO
          surface: [UI, AUDIT]
          variables: [instrument_id, bank]

        TEST_WORKFLOW_CONFIRMED:
          text: "Cheque {instrument_id} confirmed and filed."
          severity: INFO
          surface: [UI, AUDIT, NOTIFICATION]
          variables: [instrument_id]

        TEST_WORKFLOW_VAULT_MISS:
          text: "Vault miss — {account_display} has no signature specimen."
          severity: WARN
          surface: [UI, AUDIT]
          variables: [account_display]
    """).strip())

    (en / "auth.yaml").write_text(textwrap.dedent("""
        TEST_AUTH_LOGIN_SUCCESS:
          text: "Login successful — {display_name} ({role})."
          severity: INFO
          surface: [AUDIT]
          variables: [display_name, role]

        TEST_AUTH_ACCESS_DENIED:
          text: "Access denied — {role} cannot perform {action}."
          severity: ERROR
          surface: [UI, AUDIT]
          variables: [role, action]
    """).strip())

    # Hindi stubs — only cover workflow so far
    (hi / "workflow.yaml").write_text(textwrap.dedent("""
        TEST_WORKFLOW_RECEIVED:
          text: ""
        TEST_WORKFLOW_CONFIRMED:
          text: ""
        TEST_WORKFLOW_VAULT_MISS:
          text: ""
    """).strip())

    (hi / "auth.yaml").write_text(textwrap.dedent("""
        TEST_AUTH_LOGIN_SUCCESS:
          text: ""
        TEST_AUTH_ACCESS_DENIED:
          text: ""
    """).strip())

    return tmp_path


@pytest.fixture()
def registry(locales_dir):
    return MessageRegistry(locales_dir=locales_dir)


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_get_returns_formatted_message(registry):
    result = registry.get("TEST_WORKFLOW_RECEIVED", instrument_id="CTS-001", bank="HDFC")
    assert result == "Cheque CTS-001 received from HDFC."


def test_get_no_variables(registry):
    # Confirm doesn't need extra vars
    result = registry.get("TEST_WORKFLOW_CONFIRMED", instrument_id="CTS-002")
    assert "CTS-002" in result
    assert "filed" in result


def test_get_entry_returns_metadata(registry):
    entry = registry.get_entry("TEST_AUTH_ACCESS_DENIED")
    assert isinstance(entry, MessageEntry)
    assert entry.severity == "ERROR"
    assert "UI" in entry.surface
    assert "AUDIT" in entry.surface
    assert "role" in entry.variables
    assert "action" in entry.variables


def test_keys_returns_all_en_keys(registry):
    keys = registry.keys()
    assert "TEST_WORKFLOW_RECEIVED" in keys
    assert "TEST_AUTH_LOGIN_SUCCESS" in keys
    assert len(keys) == 5


def test_get_hi_stub_returns_empty_string(registry):
    result = registry.get("TEST_WORKFLOW_RECEIVED", locale="hi", instrument_id="X", bank="Y")
    assert result == ""


# ── Fallback behaviour ─────────────────────────────────────────────────────────

def test_get_unknown_locale_falls_back_to_en(registry):
    result = registry.get("TEST_AUTH_LOGIN_SUCCESS", locale="ta", display_name="Priya", role="ops_reviewer")
    assert "Priya" in result


# ── Error handling ─────────────────────────────────────────────────────────────

def test_get_unknown_key_raises(registry):
    with pytest.raises(UnknownMessageKey, match="DOES_NOT_EXIST"):
        registry.get("DOES_NOT_EXIST")


def test_get_missing_variable_raises(registry):
    with pytest.raises(MissingVariable, match="instrument_id"):
        registry.get("TEST_WORKFLOW_RECEIVED", bank="HDFC")  # instrument_id missing


# ── Validation ─────────────────────────────────────────────────────────────────

def test_validate_passes_on_valid_locales(registry):
    errors = registry.validate()
    assert errors == []


def test_validate_detects_undeclared_variable(tmp_path):
    en = tmp_path / "en"; en.mkdir()
    (en / "bad.yaml").write_text(textwrap.dedent("""
        BAD_KEY:
          text: "Hello {name} and {undeclared}."
          severity: INFO
          surface: [UI]
          variables: [name]
    """).strip())
    reg = MessageRegistry(locales_dir=tmp_path)
    errors = reg.validate()
    assert any("undeclared" in e for e in errors)


def test_validate_detects_blank_en_text(tmp_path):
    en = tmp_path / "en"; en.mkdir()
    (en / "bad.yaml").write_text(textwrap.dedent("""
        BLANK_KEY:
          text: ""
          severity: INFO
          surface: [UI]
          variables: []
    """).strip())
    reg = MessageRegistry(locales_dir=tmp_path)
    errors = reg.validate()
    assert any("BLANK_KEY" in e for e in errors)


def test_validate_detects_hi_key_missing_from_stub(tmp_path):
    en = tmp_path / "en"; en.mkdir()
    hi = tmp_path / "hi"; hi.mkdir()
    (en / "wf.yaml").write_text(textwrap.dedent("""
        KEY_A:
          text: "Message A."
          severity: INFO
          surface: [UI]
          variables: []
        KEY_B:
          text: "Message B."
          severity: INFO
          surface: [UI]
          variables: []
    """).strip())
    (hi / "wf.yaml").write_text(textwrap.dedent("""
        KEY_A:
          text: ""
    """).strip())
    reg = MessageRegistry(locales_dir=tmp_path)
    errors = reg.validate()
    assert any("KEY_B" in e and "hi" in e for e in errors)


# ── Build output ───────────────────────────────────────────────────────────────

def test_build_exports_valid_json(registry, tmp_path):
    registry.build(output_dir=tmp_path)
    en_file = tmp_path / "messages.en.json"
    hi_file = tmp_path / "messages.hi.json"
    assert en_file.exists()
    assert hi_file.exists()

    en_data = json.loads(en_file.read_text())
    assert "TEST_WORKFLOW_RECEIVED" in en_data
    assert en_data["TEST_WORKFLOW_RECEIVED"]["text"] == "Cheque {instrument_id} received from {bank}."
    assert en_data["TEST_WORKFLOW_RECEIVED"]["severity"] == "INFO"
    assert "UI" in en_data["TEST_WORKFLOW_RECEIVED"]["surface"]
    assert "instrument_id" in en_data["TEST_WORKFLOW_RECEIVED"]["variables"]


def test_build_en_json_has_all_keys(registry, tmp_path):
    registry.build(output_dir=tmp_path)
    data = json.loads((tmp_path / "messages.en.json").read_text())
    assert set(data.keys()) == set(registry.keys())
