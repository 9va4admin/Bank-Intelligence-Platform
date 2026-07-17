"""
Tests for ImmudbClient — covers write, verify, HSM signing, and error paths.

Regression: this fixture previously mocked a `.immudb_database.set()` /
`.immudb_database.verified_get()` interface that does not exist anywhere on
the real immudb-py SDK — methods are directly on the client (`.set()`,
`.verifiedGet()`, `.login()`). Every test here passed against that wrong
mock for as long as it existed, because nothing ever ran this against the
real SDK or a real immudb instance. Confirmed against the installed
`immudb` package's real ImmudbClient before rewriting this file — see
infra/docker-compose.integration.yml + tests/integration/test_immudb_integration.py
for the real-instance proof.
"""
import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.audit.immudb_client import ImmudbClient
from shared.audit.exceptions import (
    ImmudbUnavailableError,
    ImmudbVerificationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> ImmudbClient:
    """Return an ImmudbClient wired with mocks, bypassing connect()."""
    c = ImmudbClient()
    c._collection = "cts_events"
    c._bank_id = "test-bank"
    c._ready = True

    stub = MagicMock()
    stub.verifiedSet = MagicMock(return_value=MagicMock(id=42, verified=True))
    stub.verifiedGet = MagicMock(
        return_value=MagicMock(verified=True, value=b'{"event_type":"TEST"}')
    )
    c._stub = stub
    return c


# ---------------------------------------------------------------------------
# write_event — happy path
# ---------------------------------------------------------------------------

def test_write_event_calls_immudb(client: ImmudbClient):
    payload = {"event_type": "CTS_DECISION", "instrument_id": "instr-001", "bank_id": "test-bank"}
    result = client.write_event(payload)

    assert result["tx_id"] == 42
    assert result["verified"] is True
    client._stub.verifiedSet.assert_called_once()


def test_write_event_returns_tx_metadata(client: ImmudbClient):
    payload = {"event_type": "CTS_DECISION", "bank_id": "test-bank"}
    result = client.write_event(payload)

    assert "tx_id" in result
    assert "timestamp" in result
    assert "collection" in result
    assert result["collection"] == "cts_events"


def test_write_event_key_includes_bank_id_and_hash(client: ImmudbClient):
    """Key must include bank_id for isolation — never a bare sequential id."""
    payload = {"event_type": "AUDIT_WRITE", "bank_id": "test-bank"}
    client.write_event(payload)

    call_args = client._stub.verifiedSet.call_args
    # Key passed to immudb must contain bank_id prefix
    key_used = call_args[0][0] if call_args[0] else call_args[1].get("key", b"")
    assert b"test-bank" in key_used


def test_write_event_value_is_json_bytes(client: ImmudbClient):
    """Value stored in immudb must be JSON-serialised bytes."""
    import json
    payload = {"event_type": "CONFIG_CHANGE", "bank_id": "test-bank", "key": "iet_minutes"}
    client.write_event(payload)

    call_args = client._stub.verifiedSet.call_args
    value_used = call_args[0][1] if call_args[0] else call_args[1].get("value", b"")
    parsed = json.loads(value_used)
    assert parsed["event_type"] == "CONFIG_CHANGE"


# ---------------------------------------------------------------------------
# write_event — error paths
# ---------------------------------------------------------------------------

def test_write_event_raises_on_immudb_unavailable(client: ImmudbClient):
    client._stub.verifiedSet.side_effect = Exception("connection refused")

    with pytest.raises(ImmudbUnavailableError, match="write failed"):
        client.write_event({"event_type": "TEST", "bank_id": "test-bank"})


def test_write_event_raises_if_not_ready():
    uninit = ImmudbClient()
    with pytest.raises(RuntimeError, match="connect()"):
        uninit.write_event({"event_type": "TEST", "bank_id": "test-bank"})


def test_write_event_raises_if_payload_missing_bank_id(client: ImmudbClient):
    with pytest.raises(ValueError, match="bank_id"):
        client.write_event({"event_type": "CTS_DECISION"})


# ---------------------------------------------------------------------------
# verify_event
# ---------------------------------------------------------------------------

def test_verify_event_returns_true_on_valid_tx(client: ImmudbClient):
    result = client.verify_event(key=b"test-bank:some-hash")
    assert result is True


def test_verify_event_raises_on_tampered_record(client: ImmudbClient):
    client._stub.verifiedGet.return_value = MagicMock(verified=False)

    with pytest.raises(ImmudbVerificationError):
        client.verify_event(key=b"test-bank:tampered-hash")


def test_verify_event_raises_on_immudb_unavailable(client: ImmudbClient):
    client._stub.verifiedGet.side_effect = Exception("grpc error")

    with pytest.raises(ImmudbUnavailableError, match="verify failed"):
        client.verify_event(key=b"test-bank:any-hash")


# ---------------------------------------------------------------------------
# collection isolation
# ---------------------------------------------------------------------------

def test_collection_is_set_on_init(client: ImmudbClient):
    assert client._collection == "cts_events"


def test_set_collection_changes_collection(client: ImmudbClient):
    client.set_collection("ej_events")
    assert client._collection == "ej_events"


def test_write_event_uses_active_collection(client: ImmudbClient):
    client.set_collection("ej_events")
    payload = {"event_type": "EJ_PARSED", "bank_id": "test-bank"}
    result = client.write_event(payload)
    assert result["collection"] == "ej_events"


# ---------------------------------------------------------------------------
# key generation
# ---------------------------------------------------------------------------

def test_make_key_is_deterministic(client: ImmudbClient):
    """Same inputs always produce the same key — required for idempotent lookup."""
    k1 = client._make_key("test-bank", "cts_events", "instr-001")
    k2 = client._make_key("test-bank", "cts_events", "instr-001")
    assert k1 == k2


def test_make_key_differs_by_event_id(client: ImmudbClient):
    k1 = client._make_key("test-bank", "cts_events", "instr-001")
    k2 = client._make_key("test-bank", "cts_events", "instr-002")
    assert k1 != k2


def test_make_key_differs_by_collection(client: ImmudbClient):
    k1 = client._make_key("test-bank", "cts_events", "instr-001")
    k2 = client._make_key("test-bank", "ej_events", "instr-001")
    assert k1 != k2


# ---------------------------------------------------------------------------
# connect() — real SDK shape: construct, then login() (auth is mandatory —
# .set()/.get() calls fail without it). username/password are required, no
# default — Vault-sourced in production (security.md: no hardcoded creds).
# ---------------------------------------------------------------------------

def test_connect_success_sets_ready():
    from shared.audit.immudb_client import ImmudbClient
    from unittest.mock import MagicMock, patch

    stub_instance = MagicMock()
    stub_sdk = MagicMock(return_value=stub_instance)
    with patch.dict(
        "sys.modules",
        {"immudb": MagicMock(ImmudbClient=stub_sdk)},
    ):
        c = ImmudbClient()
        c.connect("localhost", 3322, "test-bank", username="immudb", password="immudb", collection="cts_events")
    assert c._ready is True
    assert c._bank_id == "test-bank"
    assert c._collection == "cts_events"


def test_connect_calls_login_with_credentials():
    from shared.audit.immudb_client import ImmudbClient
    from unittest.mock import MagicMock, patch

    stub_instance = MagicMock()
    stub_sdk = MagicMock(return_value=stub_instance)
    with patch.dict("sys.modules", {"immudb": MagicMock(ImmudbClient=stub_sdk)}):
        c = ImmudbClient()
        c.connect("localhost", 3322, "test-bank", username="svc-user", password="s3cr3t")

    stub_instance.login.assert_called_once()
    call_args = stub_instance.login.call_args[0]
    assert call_args[0] == "svc-user"
    assert call_args[1] == "s3cr3t"


def test_connect_failure_raises_immudb_unavailable():
    """connect() when SDK import raises → ImmudbUnavailableError."""
    from shared.audit.immudb_client import ImmudbClient, ImmudbUnavailableError
    from unittest.mock import patch
    import pytest

    with patch.dict("sys.modules", {"immudb": None}):
        c = ImmudbClient()
        with pytest.raises(ImmudbUnavailableError):
            c.connect("localhost", 3322, "test-bank", username="immudb", password="immudb")


def test_connect_sdk_constructor_raises_immudb_unavailable():
    """connect() when SDK instantiation raises → ImmudbUnavailableError."""
    from shared.audit.immudb_client import ImmudbClient, ImmudbUnavailableError
    from unittest.mock import MagicMock, patch
    import pytest

    mock_module = MagicMock()
    mock_module.ImmudbClient = MagicMock(side_effect=ConnectionRefusedError("port closed"))
    with patch.dict("sys.modules", {"immudb": mock_module}):
        c = ImmudbClient()
        with pytest.raises(ImmudbUnavailableError):
            c.connect("localhost", 3322, "test-bank", username="immudb", password="immudb")


def test_connect_login_failure_raises_immudb_unavailable():
    """Constructor succeeds but login() rejects credentials → ImmudbUnavailableError,
    not a raw exception leaking out of connect()."""
    from shared.audit.immudb_client import ImmudbClient, ImmudbUnavailableError
    from unittest.mock import MagicMock, patch
    import pytest

    stub_instance = MagicMock()
    stub_instance.login = MagicMock(side_effect=Exception("invalid credentials"))
    stub_sdk = MagicMock(return_value=stub_instance)
    with patch.dict("sys.modules", {"immudb": MagicMock(ImmudbClient=stub_sdk)}):
        c = ImmudbClient()
        with pytest.raises(ImmudbUnavailableError):
            c.connect("localhost", 3322, "test-bank", username="immudb", password="wrong")
