"""/v1/admin/alert-risks: seed the register from the template, give risks owners, declare mitigated by one person and verify by another. Real ASGI against the real dev YugabyteDB."""
import asyncio
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI

from shared.alerting.audit import AlertAuditor
from shared.alerting.risk_template import RISK_TEMPLATE

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key == "alerting.risk_review_days":
            return 90
        raise ConfigKeyNotFoundError(key)


def _scenario(fn, *, role="ops_manager", user="ops-1"):
    async def go():
        import asyncpg
        from apps.api.routers.alert_risks import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"ar-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, actor_id))
            return "tx"
        who = {"user": user, "role": role}
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": who["user"], "role": who["role"]}
        app.state.db_pool_cts = pool
        app.state.config_service = Cfg()
        app.state.alert_auditor = AlertAuditor(sink)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool, events, who)
        finally:
            await pool.execute("DELETE FROM platform.alert_risks WHERE bank_id LIKE 'ar-%'")
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


def test_seeding_fills_the_register_from_the_template_and_the_summary_counts_risks_without_an_owner():
    async def fn(client, bank, pool, events, who):
        assert (await client.get("/v1/admin/alert-risks")).json()["risks"] == []
        r = await client.post("/v1/admin/alert-risks/seed")
        assert r.status_code == 200 and r.json()["added"] == len(RISK_TEMPLATE)
        again = await client.post("/v1/admin/alert-risks/seed")
        assert again.json()["added"] == 0
        body = (await client.get("/v1/admin/alert-risks")).json()
        assert len(body["risks"]) == len(RISK_TEMPLATE) and body["summary"]["without_owner"] == len(RISK_TEMPLATE)
        assert body["risks"][0]["rating"] == body["risks"][0]["likelihood"] * body["risks"][0]["impact"]
    _scenario(fn)


def test_an_owner_and_a_mitigation_are_set_then_one_person_declares_and_a_different_one_verifies():
    async def fn(client, bank, pool, events, who):
        await client.post("/v1/admin/alert-risks/seed")
        rid = (await client.get("/v1/admin/alert-risks")).json()["risks"][0]["risk_id"]
        p = await client.patch(f"/v1/admin/alert-risks/{rid}", json={"owner": "Duty manager", "mitigation": "Second relay added"})
        assert p.status_code == 200 and p.json()["owner"] == "Duty manager"
        d = await client.post(f"/v1/admin/alert-risks/{rid}/declare-mitigated")
        assert d.status_code == 200 and d.json()["status"] == "MITIGATED"
        same = await client.post(f"/v1/admin/alert-risks/{rid}/verify")
        assert same.status_code == 409 and "different person" in same.json()["detail"].lower()
        who.update(user="compliance-1", role="compliance_officer")
        v = await client.post(f"/v1/admin/alert-risks/{rid}/verify")
        assert v.status_code == 200 and v.json()["status"] == "VERIFIED" and v.json()["verified_by"] == "compliance-1"
        assert (await client.post(f"/v1/admin/alert-risks/{rid}/reopen")).json()["status"] == "OPEN"
        assert {e[0] for e in events} == {"ALERT_RISK_CHANGED"}
    _scenario(fn)


def test_refusals_come_back_in_words_and_a_missing_risk_is_not_found():
    async def fn(client, bank, pool, events, who):
        await client.post("/v1/admin/alert-risks/seed")
        rid = (await client.get("/v1/admin/alert-risks")).json()["risks"][0]["risk_id"]
        early = await client.post(f"/v1/admin/alert-risks/{rid}/declare-mitigated")
        assert early.status_code == 409 and "owner" in early.json()["detail"].lower()
        assert (await client.post(f"/v1/admin/alert-risks/{rid}/verify")).status_code == 409
        bad = await client.patch(f"/v1/admin/alert-risks/{rid}", json={"likelihood": 9})
        assert bad.status_code == 422
        assert (await client.patch("/v1/admin/alert-risks/nope", json={"owner": "x"})).status_code == 404
        blank = await client.patch(f"/v1/admin/alert-risks/{rid}", json={"owner": "   "})
        assert blank.status_code == 422 and blank.json()["detail"]
    _scenario(fn)


def test_roles_a_reviewer_cannot_read_and_an_unrelated_role_cannot_change():
    async def fn(client, bank, pool, events, who):
        assert (await client.get("/v1/admin/alert-risks")).status_code == 200
        assert (await client.post("/v1/admin/alert-risks/seed")).status_code == 403
        assert (await client.patch("/v1/admin/alert-risks/x", json={"owner": "x"})).status_code == 403
    _scenario(fn, role="rbi_examiner")

    async def fn2(client, bank, pool, events, who):
        assert (await client.get("/v1/admin/alert-risks")).status_code == 403
    _scenario(fn2, role="ops_reviewer")
