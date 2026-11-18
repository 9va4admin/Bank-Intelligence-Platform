"""The audit-path proof against the REAL dev Immudb: the sentinel intent and outcome are written, then verified in the Merkle tree. Skipped when it is not reachable."""
import asyncio
import os
import socket
import uuid

import pytest

from shared.alerting.proofs import prove_audit_path
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


def test_the_proof_writes_two_records_and_both_verify_on_the_real_audit_trail():
    bank = f"it-{uuid.uuid4().hex[:8]}"
    client = _client(bank)
    proof = asyncio.run(prove_audit_path(client, bank_id=bank, collection=f"alert_events_{bank}", actor="admin-1"))
    assert proof.ok and proof.reason == "ok", proof
    assert proof.detail["intent_tx"] < proof.detail["outcome_tx"]           # the intent went in before the outcome
