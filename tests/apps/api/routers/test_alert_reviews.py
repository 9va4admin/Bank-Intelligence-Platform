"""/v1/ops/alert-reviews: list reviews that are due, submit one, add actions, move them on, verify by a different person. Real ASGI against the real dev YugabyteDB."""
import asyncio
import socket
import uuid
from datetime import date, timedelta

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
    def __init__(self):
        self.v = {"alerting.pir_due_days_p0": 3, "alerting.pir_due_days_p1": 7, "alerting.effectiveness_days": 30, "alerting.review_min_narrative_chars": 20}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def _scenario(fn, *, role="ops_manager", user="ops-1"):
    async def go():
        import asyncpg
        from apps.api.routers.alert_reviews import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"ap-{uuid.uuid4().hex[:8]}"
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
            await pool.execute("INSERT INTO platform.alert_reviews (review_id, bank_id, incident_id, severity, component, dedup_key, resolved_at) VALUES ($1,$2,'inc-1','P0','redis','component:redis:down', NOW() - interval '4 days')",
                               f"rev-{bank}", bank)
            return await fn(client, bank, pool, events, who)
        finally:
            for t in ("alert_actions", "alert_reviews"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id LIKE 'ap-%'")
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


SUBMIT = {"category": "capacity", "narrative": "Redis ran out of memory after the nightly warm-up and evicted keys.", "contributing_factors": "No memory alert", "detection_gap": "Found by users", "impact": "Slow lookups"}


def test_a_due_review_is_listed_with_its_due_date_and_overdue_and_can_be_submitted():
    async def fn(client, bank, pool, events, who):
        listed = (await client.get("/v1/ops/alert-reviews/reviews")).json()["reviews"]
        assert len(listed) == 1 and listed[0]["status"] == "DUE" and listed[0]["overdue"] is True and listed[0]["component"] == "redis"
        rid = listed[0]["review_id"]
        r = await client.post(f"/v1/ops/alert-reviews/reviews/{rid}/submit", json=SUBMIT)
        assert r.status_code == 200 and r.json()["status"] == "SUBMITTED" and r.json()["submitted_by"] == "ops-1"
        again = await client.post(f"/v1/ops/alert-reviews/reviews/{rid}/submit", json=SUBMIT)
        assert again.status_code == 409
        assert (await client.get("/v1/ops/alert-reviews/reviews?status=DUE")).json()["reviews"] == []
        assert {e[0] for e in events} == {"ALERT_REVIEW_CHANGED"}
    _scenario(fn)


def test_actions_are_added_finished_with_evidence_and_verified_by_a_different_person():
    async def fn(client, bank, pool, events, who):
        rid = (await client.get("/v1/ops/alert-reviews/reviews")).json()["reviews"][0]["review_id"]
        assert (await client.post(f"/v1/ops/alert-reviews/reviews/{rid}/actions", json={"kind": "preventive", "description": "Add a memory alert", "owner": "SRE lead",
                                                                                          "due_on": str(date.today() + timedelta(days=10))})).status_code == 409      # not submitted yet
        await client.post(f"/v1/ops/alert-reviews/reviews/{rid}/submit", json=SUBMIT)
        a = await client.post(f"/v1/ops/alert-reviews/reviews/{rid}/actions", json={"kind": "preventive", "description": "Add a memory alert", "owner": "SRE lead", "due_on": str(date.today() + timedelta(days=10))})
        assert a.status_code == 201 and a.json()["status"] == "OPEN"
        aid = a.json()["action_id"]
        no_evidence = await client.post(f"/v1/ops/alert-reviews/actions/{aid}/status", json={"status": "DONE"})
        assert no_evidence.status_code == 422 and "evidence" in no_evidence.json()["detail"].lower()
        done = await client.post(f"/v1/ops/alert-reviews/actions/{aid}/status", json={"status": "DONE", "evidence": "Alert rule merged"})
        assert done.status_code == 200 and done.json()["status"] == "DONE"
        same = await client.post(f"/v1/ops/alert-reviews/actions/{aid}/status", json={"status": "VERIFIED"})
        assert same.status_code == 409 and "different person" in same.json()["detail"].lower()
        who.update(user="compliance-1", role="compliance_officer")
        ok = await client.post(f"/v1/ops/alert-reviews/actions/{aid}/status", json={"status": "VERIFIED", "note": "Checked the rule"})
        assert ok.status_code == 200 and ok.json()["verified_by"] == "compliance-1"
        listed = (await client.get("/v1/ops/alert-reviews/actions")).json()["actions"]
        assert listed[0]["status"] == "VERIFIED" and listed[0]["effectiveness"] == "TOO_EARLY"
    _scenario(fn)


def test_refusals_are_in_words_and_missing_things_are_not_found():
    async def fn(client, bank, pool, events, who):
        rid = (await client.get("/v1/ops/alert-reviews/reviews")).json()["reviews"][0]["review_id"]
        short = await client.post(f"/v1/ops/alert-reviews/reviews/{rid}/submit", json={**SUBMIT, "narrative": "too short"})
        assert short.status_code == 422 and "narrative" in short.json()["detail"].lower()
        assert (await client.post(f"/v1/ops/alert-reviews/reviews/{rid}/submit", json={**SUBMIT, "category": "nope"})).status_code == 422
        assert (await client.post("/v1/ops/alert-reviews/reviews/nope/submit", json=SUBMIT)).status_code == 404
        assert (await client.post("/v1/ops/alert-reviews/actions/nope/status", json={"status": "DONE", "evidence": "x"})).status_code == 404
    _scenario(fn)


def test_roles_an_examiner_can_read_but_not_change_and_a_reviewer_cannot_read():
    async def fn(client, bank, pool, events, who):
        assert (await client.get("/v1/ops/alert-reviews/reviews")).status_code == 200
        assert (await client.post(f"/v1/ops/alert-reviews/reviews/x/submit", json=SUBMIT)).status_code == 403
    _scenario(fn, role="rbi_examiner")

    async def fn2(client, bank, pool, events, who):
        assert (await client.get("/v1/ops/alert-reviews/reviews")).status_code == 403
    _scenario(fn2, role="ops_reviewer")
