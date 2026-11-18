"""Readiness proofs: the audit-path proof (a sentinel intent and outcome written, read back and verified) and the store of proof results (real dev YugabyteDB)."""
import asyncio
import socket
import uuid

import asyncpg
import pytest

from shared.alerting.proofs import ProofStore, prove_audit_path

HOST, PORT = "localhost", 15433


class FakeClient:
    def __init__(self, *, verify=True, fail_on=None):
        self.calls, self.verify, self.fail_on, self.collection = [], verify, fail_on, None

    def set_collection(self, collection):
        self.collection = collection

    def write_event(self, payload):
        if self.fail_on == len(self.calls):
            raise ConnectionError("immudb down")
        self.calls.append((self.collection, payload))
        n = len(self.calls)
        return {"key": f"k{n}".encode(), "tx_id": 100 + n, "verified": True}

    def verify_event(self, key):
        return self.verify


def prove(client, **kw):
    return asyncio.run(prove_audit_path(client, bank_id="kbl", collection="alert_events_kbl", actor="admin-1", **kw))


def test_a_sentinel_intent_then_outcome_is_written_in_the_right_collection_and_verified():
    c = FakeClient()
    r = prove(c)
    assert r.ok and r.reason == "ok"
    assert [p["event_type"] for _, p in c.calls] == ["ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_SUCCEEDED"]
    assert {col for col, _ in c.calls} == {"alert_events_kbl"}
    assert r.detail["intent_tx"] == 101 and r.detail["outcome_tx"] == 102


def test_the_sentinel_carries_no_address_phone_or_secret_and_is_marked_as_a_proof():
    c = FakeClient()
    prove(c)
    text = repr(c.calls)
    assert "@" not in text and "+91" not in text and "sentinel" in text


def test_a_record_that_does_not_verify_is_a_failed_proof():
    r = prove(FakeClient(verify=False))
    assert not r.ok and r.reason == "verify_failed"


def test_a_write_that_fails_is_a_failed_proof_not_an_exception():
    r = prove(FakeClient(fail_on=1))                       # the outcome write fails after the intent went in
    assert not r.ok and r.reason == "write_failed"
    r = prove(FakeClient(fail_on=0))
    assert not r.ok and r.reason == "write_failed"


def test_no_audit_connection_is_a_failed_proof_with_its_own_reason():
    r = prove(None)
    assert not r.ok and r.reason == "not_connected"


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


def _store_scenario(fn):
    async def go():
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"pf-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(ProofStore(pool), bank)
        finally:
            await pool.execute("DELETE FROM platform.alert_readiness_proofs WHERE bank_id LIKE 'pf-%'")
            await pool.close()
    return asyncio.run(go())


@pytest.mark.integration
@pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")
def test_the_store_returns_the_latest_proof_per_kind_and_keeps_banks_apart():
    async def fn(store, bank):
        assert await store.latest(bank, "audit_path") is None
        await store.record(bank, "audit_path", False, {"reason": "write_failed"}, "admin-1")
        await asyncio.sleep(0.01)
        await store.record(bank, "audit_path", True, {"reason": "ok"}, "admin-2")
        await store.record(bank, "dns", True, {}, "admin-2")
        await store.record(bank + "x", "audit_path", False, {}, "admin-3")
        latest = await store.latest(bank, "audit_path")
        assert latest.ok is True and latest.ran_by == "admin-2" and latest.detail["reason"] == "ok"
        both = await store.latest_many(bank, ["audit_path", "dns", "test_send"])
        assert set(both) == {"audit_path", "dns"}
    _store_scenario(fn)
