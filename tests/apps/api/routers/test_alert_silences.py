"""/v1/admin/alert-silences: create a planned quiet period, list what is in force / upcoming / recent, cancel early. Real ASGI against the real dev YugabyteDB."""
import asyncio
import socket
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI

from shared.alerting.audit import AlertAuditor

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    def __init__(self, allow_p0=False):
        self.v = {"alerting.silence_max_hours": 24, "alerting.silence_allow_p0": allow_p0, "alerting.silence_min_reason_chars": 10}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def _scenario(fn, *, role="ops_manager", allow_p0=False):
    async def go():
        import asyncpg
        from apps.api.routers.alert_silences import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"as-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, actor_id))
            return "tx"
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": "ops-1", "role": role}
        app.state.db_pool_cts = pool
        app.state.config_service = Cfg(allow_p0)
        app.state.alert_auditor = AlertAuditor(sink)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool, events)
        finally:
            await pool.execute("DELETE FROM platform.alert_silences WHERE bank_id LIKE 'as-%'")
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


def body(**over):
    now = datetime.now(timezone.utc)
    return {"component": "redis", "priorities": ["P1", "P2"], "starts_at": (now - timedelta(minutes=1)).isoformat(), "ends_at": (now + timedelta(hours=2)).isoformat(), "reason": "Redis maintenance window", **over}


def test_a_silence_is_created_listed_as_in_force_and_cancelled_early_with_audit():
    async def fn(client, bank, pool, events):
        r = await client.post("/v1/admin/alert-silences", json=body())
        assert r.status_code == 201 and r.json()["component"] == "redis" and r.json()["created_by"] == "ops-1"
        listing = (await client.get("/v1/admin/alert-silences")).json()
        assert [s["component"] for s in listing["in_force"]] == ["redis"] and listing["upcoming"] == []
        assert (await client.delete(f"/v1/admin/alert-silences/{r.json()['silence_id']}")).status_code == 204
        assert (await client.get("/v1/admin/alert-silences")).json()["in_force"] == []
        assert [e[0] for e in events] == ["ALERT_SILENCE_CHANGED", "ALERT_SILENCE_CHANGED"]
    _scenario(fn)


def test_a_silence_that_starts_later_is_upcoming_and_an_empty_start_means_now():
    async def fn(client, bank, pool, events):
        later = datetime.now(timezone.utc) + timedelta(hours=3)
        assert (await client.post("/v1/admin/alert-silences", json=body(starts_at=later.isoformat(), ends_at=(later + timedelta(hours=1)).isoformat()))).status_code == 201
        now_one = body(component="kafka")
        del now_one["starts_at"]
        assert (await client.post("/v1/admin/alert-silences", json=now_one)).status_code == 201
        listing = (await client.get("/v1/admin/alert-silences")).json()
        assert [s["component"] for s in listing["upcoming"]] == ["redis"] and [s["component"] for s in listing["in_force"]] == ["kafka"]
    _scenario(fn)


def test_a_refused_silence_says_why_in_words():
    async def fn(client, bank, pool, events):
        now = datetime.now(timezone.utc)
        for over, text in ((dict(priorities=["P0"]), "critical"), (dict(ends_at=(now + timedelta(hours=40)).isoformat()), "longer"), (dict(reason="short"), "reason"),
                           (dict(ends_at=(now - timedelta(hours=1)).isoformat()), "end"), (dict(priorities=[]), "priority")):
            r = await client.post("/v1/admin/alert-silences", json=body(**over))
            assert r.status_code == 422 and text in r.json()["detail"].lower(), (over, r.text)
    _scenario(fn)


def test_critical_alerts_can_be_silenced_only_when_the_bank_allows_it():
    async def fn(client, bank, pool, events):
        assert (await client.post("/v1/admin/alert-silences", json=body(priorities=["P0"]))).status_code == 201
    _scenario(fn, allow_p0=True)


def test_cancelling_a_missing_silence_is_not_found_and_roles_are_enforced():
    async def fn(client, bank, pool, events):
        assert (await client.delete("/v1/admin/alert-silences/nope")).status_code == 404
    _scenario(fn)

    async def readonly(client, bank, pool, events):
        assert (await client.get("/v1/admin/alert-silences")).status_code == 200
        assert (await client.post("/v1/admin/alert-silences", json=body())).status_code == 403
        assert (await client.delete("/v1/admin/alert-silences/x")).status_code == 403
    _scenario(readonly, role="compliance_officer")

    async def nothing(client, bank, pool, events):
        assert (await client.get("/v1/admin/alert-silences")).status_code == 403
    _scenario(nothing, role="ops_reviewer")
