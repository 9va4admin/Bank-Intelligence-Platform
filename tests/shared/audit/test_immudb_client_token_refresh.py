"""An immudb session token expires. A long-running worker or API must re-login once and retry, not fail every
audit write for ever (found 2026-10-16: a worker up for two days answered every write_audit with
'PERMISSION_DENIED: token has expired' and every cheque workflow stalled on its unlimited audit retry)."""
from unittest.mock import MagicMock

import pytest

from shared.audit.exceptions import ImmudbUnavailableError
from shared.audit.immudb_client import ImmudbClient

EXPIRED = Exception("<_InactiveRpcError status = StatusCode.PERMISSION_DENIED details = \"token has expired: token validation error\">")
PAYLOAD = {"event_type": "CTS_DECISION", "instrument_id": "i-1", "bank_id": "test-bank"}


@pytest.fixture
def client():
    c = ImmudbClient()
    c._bank_id, c._collection, c._ready = "test-bank", "cts_events", True
    c._credentials = ("user", "pw", "defaultdb")
    c._stub = MagicMock()
    c._stub.verifiedSet = MagicMock(return_value=MagicMock(id=7, verified=True))
    c._stub.verifiedGet = MagicMock(return_value=MagicMock(verified=True))
    return c


def test_write_relogs_in_once_and_retries_when_the_token_has_expired(client):
    client._stub.verifiedSet.side_effect = [EXPIRED, MagicMock(id=7, verified=True)]
    result = client.write_event(PAYLOAD)
    assert result["tx_id"] == 7
    client._stub.login.assert_called_once_with("user", "pw", database=b"defaultdb")
    assert client._stub.verifiedSet.call_count == 2


def test_verify_relogs_in_once_and_retries_when_the_token_has_expired(client):
    client._stub.verifiedGet.side_effect = [EXPIRED, MagicMock(verified=True)]
    assert client.verify_event(b"k") is True
    client._stub.login.assert_called_once()


def test_a_second_expiry_after_relogin_is_a_failure_not_a_loop(client):
    client._stub.verifiedSet.side_effect = [EXPIRED, EXPIRED]
    with pytest.raises(ImmudbUnavailableError):
        client.write_event(PAYLOAD)
    assert client._stub.login.call_count == 1
    assert client._stub.verifiedSet.call_count == 2


def test_other_errors_do_not_trigger_a_relogin(client):
    client._stub.verifiedSet.side_effect = Exception("connection refused")
    with pytest.raises(ImmudbUnavailableError):
        client.write_event(PAYLOAD)
    client._stub.login.assert_not_called()


def test_relogin_failure_is_unavailable(client):
    client._stub.verifiedSet.side_effect = EXPIRED
    client._stub.login.side_effect = Exception("auth server down")
    with pytest.raises(ImmudbUnavailableError):
        client.write_event(PAYLOAD)
