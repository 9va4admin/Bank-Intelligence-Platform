"""/v1/ops/oncall: rotas, who is on call now, overrides (swaps and cover), and coverage gaps. Real ASGI against the real dev YugabyteDB."""
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
    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        values = {"alerting.timezone": "Asia/Kolkata"}
        if key not in values:
            raise ConfigKeyNotFoundError(key)
        return values[key]


def _scenario(fn, *, role="ops_manager"):
    async def go():
        import asyncpg
        from apps.api.routers.oncall import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, actor_id, payload))
            return "tx"
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": "mgr-1", "role": role}
        app.state.db_pool_cts, app.state.config_service, app.state.alert_auditor = pool, Cfg(), AlertAuditor(sink)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool, events)
        finally:
            for t in ("alert_oncall_overrides", "alert_oncall_rotas"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


ALL_DAY = {"shifts": [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59", "users": ["alice"]}]}
WEEKDAYS = {"shifts": [{"days": [0, 1, 2, 3, 4], "start": "09:30", "end": "18:00", "users": ["alice"]}]}


def test_a_rota_is_saved_listed_and_read_back_with_who_is_on_call_now():
    async def fn(client, bank, pool, events):
        r = await client.put("/v1/ops/oncall/rotas/ops", json={"rota": ALL_DAY})
        assert r.status_code == 200 and r.json() == {"name": "ops", "version": 1}
        assert (await client.put("/v1/ops/oncall/rotas/ops", json={"rota": ALL_DAY})).json()["version"] == 2
        listed = (await client.get("/v1/ops/oncall/rotas")).json()["rotas"]
        assert [(x["name"], x["on_call"]["users"], x["on_call"]["source"]) for x in listed] == [("ops", ["alice"], "shift")]
        one = (await client.get("/v1/ops/oncall/rotas/ops")).json()
        assert one["rota"]["shifts"][0]["users"] == ["alice"] and one["on_call"]["users"] == ["alice"] and one["gaps"] == [] and one["overrides"] == []
        assert [e[2]["action"] for e in events] == ["ROTA_SAVED", "ROTA_SAVED"] and events[0][1] == "mgr-1"
    _scenario(fn)


def test_an_invalid_rota_is_a_422_with_reasons_and_an_unknown_one_a_404():
    async def fn(client, bank, pool, events):
        r = await client.put("/v1/ops/oncall/rotas/ops", json={"rota": {"shifts": [{"days": [9], "start": "25:00", "end": "10:00", "users": []}]}})
        assert r.status_code == 422 and {"bad_day", "bad_time", "shift_needs_people"} <= set(r.json()["detail"]["codes"])
        assert (await client.get("/v1/ops/oncall/rotas/nope")).status_code == 404
        assert (await client.put("/v1/ops/oncall/rotas/Bad Name!", json={"rota": ALL_DAY})).status_code == 422
    _scenario(fn)


def test_an_override_replaces_the_rota_for_its_period_and_can_be_removed():
    async def fn(client, bank, pool, events):
        await client.put("/v1/ops/oncall/rotas/ops", json={"rota": ALL_DAY})
        now = datetime.now(timezone.utc)
        r = await client.post("/v1/ops/oncall/rotas/ops/overrides", json={"user_id": "bob", "starts_at": (now - timedelta(hours=1)).isoformat(),
                                                                       "ends_at": (now + timedelta(hours=1)).isoformat(), "reason": "swap"})
        assert r.status_code == 201
        oid = r.json()["override_id"]
        view = (await client.get("/v1/ops/oncall/rotas/ops")).json()
        assert view["on_call"] == {"users": ["bob"], "source": "override"} and [o["user_id"] for o in view["overrides"]] == ["bob"]
        assert (await client.delete(f"/v1/ops/oncall/rotas/ops/overrides/{oid}")).status_code == 200
        assert (await client.get("/v1/ops/oncall/rotas/ops")).json()["on_call"]["users"] == ["alice"]
        assert (await client.delete(f"/v1/ops/oncall/rotas/ops/overrides/{oid}")).status_code == 404
    _scenario(fn)


def test_a_bad_override_is_refused():
    async def fn(client, bank, pool, events):
        await client.put("/v1/ops/oncall/rotas/ops", json={"rota": ALL_DAY})
        now = datetime.now(timezone.utc).isoformat()
        assert (await client.post("/v1/ops/oncall/rotas/ops/overrides", json={"user_id": "bob", "starts_at": now, "ends_at": now, "reason": "x"})).status_code == 422
        later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert (await client.post("/v1/ops/oncall/rotas/none/overrides", json={"user_id": "bob", "starts_at": now, "ends_at": later, "reason": "x"})).status_code == 422
    _scenario(fn)


def test_coverage_gaps_are_reported_as_intervals():
    async def fn(client, bank, pool, events):
        await client.put("/v1/ops/oncall/rotas/ops", json={"rota": WEEKDAYS})
        gaps = (await client.get("/v1/ops/oncall/rotas/ops")).json()["gaps"]
        assert gaps and all(g["starts_at"] < g["ends_at"] for g in gaps)
        await client.put("/v1/ops/oncall/rotas/ops", json={"rota": {**WEEKDAYS, "fallback": {"users": ["manager"]}}})
        assert (await client.get("/v1/ops/oncall/rotas/ops")).json()["gaps"] == []
    _scenario(fn)


def test_who_may_read_and_who_may_change():
    async def fn(client, bank, pool, events):
        assert (await client.get("/v1/ops/oncall/rotas")).status_code == 200
        assert (await client.put("/v1/ops/oncall/rotas/ops", json={"rota": ALL_DAY})).status_code == 403
        assert (await client.post("/v1/ops/oncall/rotas/ops/overrides", json={"user_id": "b", "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-01-02T00:00:00Z", "reason": ""})).status_code == 403
    _scenario(fn, role="ops_reviewer")

    async def nobody(client, bank, pool, events):
        assert (await client.get("/v1/ops/oncall/rotas")).status_code == 403
    _scenario(nobody, role="fraud_analyst")
