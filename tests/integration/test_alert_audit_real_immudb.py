"""The alert audit trail against the REAL dev Immudb (container astra-immudb): the intent record is written before the send, the outcome after, both
are cryptographically verified, and nothing sensitive is stored. Skipped when the dev Immudb is not reachable.

Connection: host/port/user/password from IMMUDB_DEV_HOST, IMMUDB_DEV_PORT, IMMUDB_DEV_USER, IMMUDB_DEV_PASSWORD; the defaults are the dev container's.
"""
import asyncio
import json
import os
import socket
import uuid

import pytest

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput, dispatch_platform_alert
from shared.alerting.factory import build_alert_auditor
from shared.audit.immudb_client import ImmudbClient

pytestmark = pytest.mark.integration

HOST = os.environ.get("IMMUDB_DEV_HOST", "localhost")
PORT = int(os.environ.get("IMMUDB_DEV_PORT", "13322"))
USER = os.environ.get("IMMUDB_DEV_USER", "immudb")
PASSWORD = os.environ.get("IMMUDB_DEV_PASSWORD", "immudb")


def _client(bank_id):
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
    except OSError:
        pytest.skip("dev Immudb not reachable")
    c = ImmudbClient()
    try:
        c.connect(HOST, PORT, bank_id, username=USER, password=PASSWORD)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dev Immudb login not possible: {type(exc).__name__}")
    return c


class _RecordingWriter:
    """The async writer the worker uses, but remembering each record's key so the test can verify it afterwards."""

    def __init__(self, client):
        self.client, self.keys = client, []

    async def write(self, *, collection, event_type, bank_id, payload, instrument_id=None):
        def go():
            self.client.set_collection(collection)
            body = {"event_type": event_type, "bank_id": bank_id, "payload": payload}
            if instrument_id is not None:
                body["instrument_id"] = instrument_id
            return self.client.write_event(body)
        result = await asyncio.to_thread(go)
        self.keys.append((event_type, result["key"], result["tx_id"], result["verified"]))
        return str(result["tx_id"])


class _Disp:
    def __init__(self, fail_whatsapp=True):
        self.fail_whatsapp = fail_whatsapp

    async def send(self, request):
        if request.channel == "whatsapp" and self.fail_whatsapp:
            raise RuntimeError("401 token expired for +919800000001 token=abc123")


class _Cfg:
    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        values = {"alerts.email_recipients": "ops@bank.example", "alerts.whatsapp_recipients": "+919800000001"}
        if key not in values:
            raise ConfigKeyNotFoundError(key)
        return values[key]


def test_intent_then_outcome_are_written_verified_and_free_of_secrets(monkeypatch):
    bank = f"it-{uuid.uuid4().hex[:8]}"
    client = _client(bank)
    writer = _RecordingWriter(client)
    auditor = asyncio.run(build_alert_auditor(_Cfg(), bank, redis=None, immudb_writer=writer))
    alert = DispatchAlertInput(bank_id=bank, event_type="COMPONENT_DOWN", component="redis", message="redis down", severity="CRITICAL",
                               priority="P0", incident_id="inc-live-1")
    res = asyncio.run(dispatch_platform_alert(alert, dispatcher=_Disp(), config_service=_Cfg(), alert_auditor=auditor))
    assert res.sent                                                 # the email went; the WhatsApp failure did not stop it

    kinds = [k for k, *_ in writer.keys]
    assert kinds == ["ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_SUCCEEDED", "ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_FAILED"]
    tx_ids = [t for _, _, t, _ in writer.keys]
    assert tx_ids == sorted(tx_ids)                                 # written in the order they happened: intent before outcome
    for _, key, _, verified in writer.keys:
        assert verified is True and client.verify_event(key) is True    # cryptographically verified in the Merkle tree, read back from Immudb
    blob = json.dumps(writer.keys, default=str)
    assert "ops@bank.example" not in blob and "9800000001" not in blob and "abc123" not in blob
