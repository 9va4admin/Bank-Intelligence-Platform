"""/v1/ops/alerts: incident list and detail, the delivery log, and acknowledge. Run through real ASGI against the real dev YugabyteDB
(same event loop as the pool). Skipped when the database is not reachable."""
import asyncio
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI

from shared.alerting.audit import AlertAuditor
from shared.alerting.delivery import DeliveryStore
from shared.alerting.incidents import IncidentStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _scenario(fn, *, role="ops_manager", pool_present=True):
    async def go():
        import asyncpg
        from apps.api.routers.alerts import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, entity_id, actor_id, payload))
            return "tx"
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": "user-7", "role": role}
        app.state.db_pool_cts = pool if pool_present else None
        app.state.alert_auditor = AlertAuditor(sink)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool, events)
        finally:
            for t in ("alert_deliveries", "alert_incidents"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


async def _seed(pool, bank, n=3):
    inc = IncidentStore(pool)
    out = []
    for i in range(n):
        r = await inc.open_or_update(bank_id=bank, dedup_key=f"k{i}", alert_id="COMPONENT_DOWN", component="redis" if i % 2 == 0 else "kafka",
                                     severity="P0" if i == 0 else "P1", summary=f"s{i}")
        await pool.execute("UPDATE platform.alert_incidents SET opened_at = NOW() - make_interval(secs => $2) WHERE incident_id=$1", r.incident_id, float(100 - i))
        out.append(r.incident_id)
    return out


async def _seed_delivery(pool, bank, incident_id):
    store = DeliveryStore(pool, pii_key="k", pepper="p")
    r = await store.enqueue(bank_id=bank, incident_id=incident_id, occasion="t1", level=0, channel="email", recipient="n.shah12@gmail.com",
                            template_id="PLATFORM_HEALTH_ALERT", payload={"message": "m"}, priority="P0")
    return r.delivery_id


def test_incidents_are_listed_newest_first_with_filters_and_paging():
    async def fn(client, bank, pool, events):
        await _seed(pool, bank)
        r = await client.get("/v1/ops/alerts/incidents", params={"limit": 2})
        assert r.status_code == 200
        body = r.json()
        assert [i["summary"] for i in body["incidents"]] == ["s2", "s1"] and body["next_cursor"]
        r2 = await client.get("/v1/ops/alerts/incidents", params={"limit": 2, "cursor": body["next_cursor"]})
        assert [i["summary"] for i in r2.json()["incidents"]] == ["s0"] and r2.json()["next_cursor"] is None
        f = await client.get("/v1/ops/alerts/incidents", params={"severity": "P0"})
        assert [i["summary"] for i in f.json()["incidents"]] == ["s0"]
        assert (await client.get("/v1/ops/alerts/incidents", params={"component": "kafka"})).json()["incidents"][0]["component"] == "kafka"
    _scenario(fn)


def test_bad_input_is_a_422_not_a_crash():
    async def fn(client, bank, pool, events):
        assert (await client.get("/v1/ops/alerts/incidents", params={"cursor": "garbage"})).status_code == 422
        assert (await client.get("/v1/ops/alerts/incidents", params={"limit": 101})).status_code == 422
        assert (await client.get("/v1/ops/alerts/incidents", params={"severity": "P9"})).status_code == 422
        assert (await client.get("/v1/ops/alerts/deliveries", params={"status": "MAYBE"})).status_code == 422
    _scenario(fn)


def test_an_incident_shows_its_deliveries_with_masked_recipients_only():
    async def fn(client, bank, pool, events):
        ids = await _seed(pool, bank, 1)
        await _seed_delivery(pool, bank, ids[0])
        r = await client.get(f"/v1/ops/alerts/incidents/{ids[0]}")
        assert r.status_code == 200
        body = r.json()
        assert body["incident"]["incident_id"] == ids[0] and body["deliveries"][0]["recipient_ref"] == "n***@gmail.com"
        assert "n.shah12@gmail.com" not in r.text and "shah12" not in r.text
    _scenario(fn)


def test_an_unknown_incident_is_404():
    async def fn(client, bank, pool, events):
        assert (await client.get("/v1/ops/alerts/incidents/nope")).status_code == 404
    _scenario(fn)


def test_the_delivery_log_can_be_filtered():
    async def fn(client, bank, pool, events):
        ids = await _seed(pool, bank, 1)
        await _seed_delivery(pool, bank, ids[0])
        log = (await client.get("/v1/ops/alerts/deliveries", params={"status": "PENDING", "channel": "email", "incident_id": ids[0]})).json()
        assert [d["status"] for d in log["deliveries"]] == ["PENDING"] and log["next_cursor"] is None
        assert (await client.get("/v1/ops/alerts/deliveries", params={"status": "SENT"})).json()["deliveries"] == []
    _scenario(fn)


def test_acknowledge_records_who_audits_it_and_a_second_ack_is_a_409():
    async def fn(client, bank, pool, events):
        ids = await _seed(pool, bank, 1)
        r = await client.post(f"/v1/ops/alerts/incidents/{ids[0]}/acknowledge")
        assert r.status_code == 200 and r.json() == {"incident_id": ids[0], "state": "ACKED", "acknowledged_by": "user-7"}
        assert events[-1][0] == "ALERT_ACKNOWLEDGED" and events[-1][1] == ids[0] and events[-1][2] == "user-7"
        assert (await client.post(f"/v1/ops/alerts/incidents/{ids[0]}/acknowledge")).status_code == 409
        assert (await client.post("/v1/ops/alerts/incidents/nope/acknowledge")).status_code == 404
        assert [e[0] for e in events].count("ALERT_ACKNOWLEDGED") == 1
    _scenario(fn)


def test_roles_read_roles_cannot_acknowledge_and_others_cannot_read():
    async def ro(client, bank, pool, events):
        ids = await _seed(pool, bank, 1)
        assert (await client.get("/v1/ops/alerts/incidents")).status_code == 200                       # compliance officer may read
        assert (await client.post(f"/v1/ops/alerts/incidents/{ids[0]}/acknowledge")).status_code == 403
    _scenario(ro, role="compliance_officer")

    async def none(client, bank, pool, events):
        assert (await client.get("/v1/ops/alerts/incidents")).status_code == 403
        assert (await client.get("/v1/ops/alerts/deliveries")).status_code == 403
    _scenario(none, role="fraud_analyst")


def test_without_a_database_the_answer_is_a_clean_503():
    async def fn(client, bank, pool, events):
        r = await client.get("/v1/ops/alerts/incidents")
        assert r.status_code == 503 and r.json()["detail"]
    _scenario(fn, pool_present=False)
