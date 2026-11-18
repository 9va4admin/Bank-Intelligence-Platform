"""/v1/inbox: each user's own notifications (the bell). Real ASGI against the real dev YugabyteDB. A user never sees or touches anyone else's."""
import asyncio
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI

from shared.alerting.audit import AlertAuditor
from shared.alerting.incidents import IncidentStore
from shared.alerting.inbox import InboxStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _scenario(fn, *, role="ops_manager", user="user-7", pool_present=True):
    async def go():
        import asyncpg
        from apps.api.routers.inbox import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, entity_id, actor_id))
            return "tx"
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": user, "role": role}
        app.state.db_pool_cts = pool if pool_present else None
        app.state.alert_auditor = AlertAuditor(sink)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool, events)
        finally:
            for t in ("user_notifications", "alert_incidents"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


def _add(pool, bank, user="user-7", severity="P0", title="t", **kw):
    return InboxStore(pool).add(bank_id=bank, user_id=user, severity=severity, title=title, body="b", **kw)


def test_the_summary_gives_unread_counts_and_the_unacknowledged_critical_ones():
    async def fn(client, bank, pool, events):
        a = await _add(pool, bank, severity="P0", title="redis down")
        await _add(pool, bank, severity="P1")
        await _add(pool, bank, user="someone-else")
        r = await client.get("/v1/inbox/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["unread"] == {"total": 2, "P0": 1, "P1": 1, "P2": 0, "P3": 0}
        assert [p["notification_id"] for p in body["pinned"]] == [a] and body["pinned"][0]["title"] == "redis down"
    _scenario(fn)


def test_the_list_is_newest_first_pageable_and_only_the_users_own():
    async def fn(client, bank, pool, events):
        for i in range(3):
            n = await _add(pool, bank, title=f"n{i}")
            await pool.execute("UPDATE platform.user_notifications SET created_at = NOW() - make_interval(secs => $2) WHERE notification_id=$1", n, float(100 - i))
        await _add(pool, bank, user="someone-else", title="not mine")
        p1 = (await client.get("/v1/inbox", params={"limit": 2})).json()
        assert [n["title"] for n in p1["notifications"]] == ["n2", "n1"] and p1["next_cursor"]
        p2 = (await client.get("/v1/inbox", params={"limit": 2, "cursor": p1["next_cursor"]})).json()
        assert [n["title"] for n in p2["notifications"]] == ["n0"]
        assert (await client.get("/v1/inbox", params={"cursor": "garbage"})).status_code == 422
    _scenario(fn)


def test_read_and_read_all():
    async def fn(client, bank, pool, events):
        a = await _add(pool, bank)
        await _add(pool, bank)
        assert (await client.post(f"/v1/inbox/{a}/read")).status_code == 200
        assert (await client.get("/v1/inbox/summary")).json()["unread"]["total"] == 1
        r = await client.post("/v1/inbox/read-all")
        assert r.status_code == 200 and r.json() == {"marked": 1}
        assert (await client.get("/v1/inbox", params={"unread_only": "true"})).json()["notifications"] == []
        assert (await client.post("/v1/inbox/nope/read")).status_code == 404
    _scenario(fn)


def test_someone_elses_notification_is_a_404_not_a_leak():
    async def fn(client, bank, pool, events):
        theirs = await _add(pool, bank, user="someone-else")
        assert (await client.post(f"/v1/inbox/{theirs}/read")).status_code == 404
        assert (await client.post(f"/v1/inbox/{theirs}/acknowledge")).status_code == 404
        assert (await client.get("/v1/inbox/summary")).json()["unread"]["total"] == 0
    _scenario(fn)


def test_acknowledging_a_critical_notification_also_acknowledges_the_incident_for_a_role_that_may_and_audits_it():
    async def fn(client, bank, pool, events):
        inc = await IncidentStore(pool).open_or_update(bank_id=bank, dedup_key="k", alert_id="COMPONENT_DOWN", component="redis", severity="P0", summary="s")
        n = await _add(pool, bank, incident_id=inc.incident_id)
        r = await client.post(f"/v1/inbox/{n}/acknowledge")
        assert r.status_code == 200 and r.json() == {"notification_id": n, "incident_acknowledged": True}
        assert (await IncidentStore(pool).get(bank, inc.incident_id))["state"] == "ACKED"
        assert ("ALERT_ACKNOWLEDGED", inc.incident_id, "user-7") in events
        assert (await client.get("/v1/inbox/summary")).json()["pinned"] == []                     # no longer pinned
        assert (await client.post(f"/v1/inbox/{n}/acknowledge")).status_code == 409
    _scenario(fn)


def test_a_role_that_may_not_acknowledge_incidents_can_still_dismiss_its_own_notification_without_touching_the_incident():
    async def fn(client, bank, pool, events):
        inc = await IncidentStore(pool).open_or_update(bank_id=bank, dedup_key="k", alert_id="COMPONENT_DOWN", component="redis", severity="P0", summary="s")
        n = await _add(pool, bank, incident_id=inc.incident_id)
        r = await client.post(f"/v1/inbox/{n}/acknowledge")
        assert r.status_code == 200 and r.json()["incident_acknowledged"] is False
        assert (await IncidentStore(pool).get(bank, inc.incident_id))["state"] == "OPEN" and events == []
    _scenario(fn, role="ops_reviewer")


def test_without_a_database_the_answer_is_a_clean_503():
    async def fn(client, bank, pool, events):
        assert (await client.get("/v1/inbox/summary")).status_code == 503
    _scenario(fn, pool_present=False)
