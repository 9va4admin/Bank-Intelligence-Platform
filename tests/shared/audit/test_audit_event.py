"""
Tests for AuditEvent — Pydantic schema, serialisation, HSM signing contract.

TDD: written BEFORE the implementation.
"""
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from shared.audit.audit_event import AuditEvent, AuditEventType


# ---------------------------------------------------------------------------
# Construction and schema
# ---------------------------------------------------------------------------

def test_audit_event_constructs_with_required_fields():
    evt = AuditEvent(
        event_type=AuditEventType.CTS_DECISION,
        bank_id="test-bank",
        payload={"instrument_id": "instr-001", "decision": "STP_CONFIRM"},
    )
    assert evt.event_type == AuditEventType.CTS_DECISION
    assert evt.bank_id == "test-bank"
    assert evt.payload["decision"] == "STP_CONFIRM"


def test_audit_event_auto_generates_event_id():
    evt = AuditEvent(
        event_type=AuditEventType.CTS_DECISION,
        bank_id="test-bank",
        payload={},
    )
    assert evt.event_id is not None
    assert len(evt.event_id) > 0


def test_audit_event_auto_generates_timestamp():
    before = time.time()
    evt = AuditEvent(
        event_type=AuditEventType.CTS_DECISION,
        bank_id="test-bank",
        payload={},
    )
    after = time.time()
    assert before <= evt.timestamp <= after


def test_audit_event_is_frozen():
    """Audit records must be immutable after creation."""
    evt = AuditEvent(
        event_type=AuditEventType.CTS_DECISION,
        bank_id="test-bank",
        payload={},
    )
    with pytest.raises(Exception):
        evt.bank_id = "different-bank"  # type: ignore[misc]


def test_audit_event_type_enum_has_expected_values():
    assert AuditEventType.CTS_DECISION in AuditEventType
    assert AuditEventType.CTS_VAULT_MISS in AuditEventType
    assert AuditEventType.CTS_NGCH_FILED in AuditEventType
    assert AuditEventType.EJ_PARSED in AuditEventType
    assert AuditEventType.EJ_DISPUTE_RESOLVED in AuditEventType
    assert AuditEventType.CONFIG_CHANGE in AuditEventType
    assert AuditEventType.DIAGNOSTIC_ACCESS in AuditEventType


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def test_to_json_returns_bytes():
    evt = AuditEvent(
        event_type=AuditEventType.CONFIG_CHANGE,
        bank_id="test-bank",
        payload={"key": "iet_minutes", "old_value": 180, "new_value": 120},
    )
    result = evt.to_json()
    assert isinstance(result, bytes)


def test_to_json_is_valid_json(audit_event):
    raw = audit_event.to_json()
    parsed = json.loads(raw)
    assert parsed["event_type"] == audit_event.event_type.value
    assert parsed["bank_id"] == audit_event.bank_id


def test_to_json_includes_all_fields(audit_event):
    parsed = json.loads(audit_event.to_json())
    assert "event_id" in parsed
    assert "timestamp" in parsed
    assert "payload" in parsed


def test_two_events_same_payload_different_ids():
    kwargs = dict(
        event_type=AuditEventType.CTS_DECISION,
        bank_id="test-bank",
        payload={"decision": "STP_CONFIRM"},
    )
    e1 = AuditEvent(**kwargs)
    e2 = AuditEvent(**kwargs)
    assert e1.event_id != e2.event_id


# ---------------------------------------------------------------------------
# HSM signing
# ---------------------------------------------------------------------------

def test_sign_with_hsm_attaches_signature(audit_event):
    mock_hsm = MagicMock()
    mock_hsm.sign.return_value = b"\xde\xad\xbe\xef" * 8

    signed = audit_event.sign(mock_hsm)

    assert signed.signature is not None
    assert len(signed.signature) > 0
    mock_hsm.sign.assert_called_once()


def test_sign_with_hsm_signs_canonical_json(audit_event):
    mock_hsm = MagicMock()
    mock_hsm.sign.return_value = b"sig"

    audit_event.sign(mock_hsm)

    signed_bytes = mock_hsm.sign.call_args[0][0]
    assert isinstance(signed_bytes, bytes)
    parsed = json.loads(signed_bytes)
    assert parsed["event_id"] == audit_event.event_id


def test_sign_returns_new_frozen_event(audit_event):
    mock_hsm = MagicMock()
    mock_hsm.sign.return_value = b"sig"

    signed = audit_event.sign(mock_hsm)

    assert signed is not audit_event
    assert signed.signature == b"sig"
    assert signed.event_id == audit_event.event_id


def test_sign_raises_on_hsm_failure(audit_event):
    from shared.audit.audit_event import HSMSigningError
    mock_hsm = MagicMock()
    mock_hsm.sign.side_effect = Exception("HSM offline")

    with pytest.raises(HSMSigningError, match="HSM signing failed"):
        audit_event.sign(mock_hsm)


def test_already_signed_event_cannot_be_signed_again(audit_event):
    mock_hsm = MagicMock()
    mock_hsm.sign.return_value = b"first-sig"

    signed = audit_event.sign(mock_hsm)

    with pytest.raises(ValueError, match="already signed"):
        signed.sign(mock_hsm)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def audit_event() -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.CTS_DECISION,
        bank_id="test-bank",
        payload={"instrument_id": "instr-001", "decision": "STP_CONFIRM", "fraud_score": 0.12},
    )
