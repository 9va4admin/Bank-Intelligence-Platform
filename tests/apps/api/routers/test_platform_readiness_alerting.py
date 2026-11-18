"""GET /v1/platform/readiness includes the alerting items, on the real dev YugabyteDB. Skipped when the database is not reachable."""
import asyncio
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    def __init__(self, key="readiness-api-key-not-a-secret"):
        self.key = key
        self.v = {"alerting.timezone": "Asia/Kolkata", "alerting.oncall_gap_days": 7, "alerting.oncall_gap_step_minutes": 30,
                  "alerting.readiness_test_send_days": 7, "alerting.readiness_audit_proof_days": 30, "alerting.audit_collection_pattern": "alert_events_{bank_id}", "alerting.readiness_open_incident_hours": 24, "alerting.public_mail_hosts": "[]",
                  "alerts.email_recipients": "", "alerting.bell_roles": '["ops_manager"]', "alerting.bell_min_priority": "P3"}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]

    async def get_secret(self, key):
        if not self.key:
            raise KeyError(key)
        return self.key

    def get_platform(self, key):
        raise KeyError(key)


def _scenario(fn, *, role="bank_it_admin", config=None, immudb=None):
    async def go():
        import asyncpg
        from apps.api.routers.platform import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": "u", "role": role}
        app.state.db_pool_cts = pool
        app.state.config_service = config or Cfg()
        app.state.immudb_client = immudb
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool)
        finally:
            for t in ("alert_routing_policies", "alert_oncall_rotas", "alert_deliveries", "alert_incidents", "alert_readiness_proofs"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


def test_the_readiness_list_includes_the_alerting_items_with_words_and_a_link_to_fix_each():
    async def fn(client, bank, pool):
        r = await client.get("/v1/platform/readiness")
        assert r.status_code == 200
        items = {i["check_id"]: i for i in r.json()["items"]}
        for cid in ("alert_routing", "alert_oncall", "alert_email", "alert_recent_delivery", "alert_open_incidents", "alert_audit_path"):
            assert cid in items and items[cid]["label"] and items[cid]["detail"], cid
        assert items["alert_routing"]["status"] == "FAIL" and items["alert_routing"]["action_url"] == "/admin/alert-routing"
        assert r.json()["all_ready"] is False                                  # a failing alerting item blocks go-live like any other
    _scenario(fn)


def test_without_the_encryption_key_routing_is_a_warning_and_the_rest_still_answer():
    async def fn(client, bank, pool):
        items = {i["check_id"]: i for i in (await client.get("/v1/platform/readiness")).json()["items"]}
        assert items["alert_routing"]["status"] == "WARN"
        assert items["alert_email"]["status"] == "FAIL" and items["alert_open_incidents"]["status"] == "PASS"
    _scenario(fn, config=Cfg(key=None))


def test_a_role_that_cannot_read_readiness_is_refused():
    async def fn(client, bank, pool):
        assert (await client.get("/v1/platform/readiness")).status_code == 403
    _scenario(fn, role="ops_reviewer")


class FakeImmudb:
    def __init__(self, verify=True):
        self.verify, self.n, self.collection = verify, 0, None

    def set_collection(self, c):
        self.collection = c

    def write_event(self, payload):
        self.n += 1
        return {"key": b"k", "tx_id": self.n, "verified": True}

    def verify_event(self, key):
        return self.verify


def test_running_the_audit_proof_records_it_and_the_readiness_item_then_passes():
    async def fn(client, bank, pool):
        before = {i["check_id"]: i for i in (await client.get("/v1/platform/readiness")).json()["items"]}
        assert before["alert_audit_path"]["status"] == "FAIL"
        r = await client.post("/v1/platform/alert-proofs/audit-path")
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["reason"] == "ok"
        after = {i["check_id"]: i for i in (await client.get("/v1/platform/readiness")).json()["items"]}
        assert after["alert_audit_path"]["status"] == "PASS"
        latest = (await client.get("/v1/platform/alert-proofs")).json()
        assert latest["audit_path"]["ok"] is True and latest["audit_path"]["ran_by"] == "u"
    _scenario(fn, immudb=FakeImmudb())


def test_a_failed_proof_is_recorded_too_and_the_item_fails_with_the_reason_in_words():
    async def fn(client, bank, pool):
        r = await client.post("/v1/platform/alert-proofs/audit-path")
        assert r.status_code == 200 and r.json()["ok"] is False and r.json()["reason"] == "verify_failed"
        item = {i["check_id"]: i for i in (await client.get("/v1/platform/readiness")).json()["items"]}["alert_audit_path"]
        assert item["status"] == "FAIL" and "did not verify" in item["detail"]
    _scenario(fn, immudb=FakeImmudb(verify=False))


def test_with_no_audit_connection_the_proof_fails_with_its_own_reason():
    async def fn(client, bank, pool):
        r = await client.post("/v1/platform/alert-proofs/audit-path")
        assert r.json()["ok"] is False and r.json()["reason"] == "not_connected"
    _scenario(fn, immudb=None)


def test_only_an_it_admin_may_run_the_proof():
    async def fn(client, bank, pool):
        assert (await client.post("/v1/platform/alert-proofs/audit-path")).status_code == 403
        assert (await client.get("/v1/platform/alert-proofs")).status_code == 200            # an ops manager may read the result
    _scenario(fn, role="ops_manager", immudb=FakeImmudb())
