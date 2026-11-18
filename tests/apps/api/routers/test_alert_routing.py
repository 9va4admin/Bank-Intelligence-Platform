"""/v1/admin/alert-routing: the routing policies (propose, approve by someone else, reject, history), the "who would be told" simulator, and the channel status.
Real ASGI against the real dev YugabyteDB. Skipped when the database is not reachable."""
import asyncio
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI

from shared.alerting.audit import AlertAuditor

HOST, PORT = "localhost", 15433
KEY = "alert-routing-api-key-not-a-secret"


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    def __init__(self, platform=None, **v):
        self.v, self.p = {"alerting.timezone": "Asia/Kolkata", **v}, platform or {}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]

    async def get_secret(self, key):
        return KEY

    def get_platform(self, key):
        if key not in self.p:
            raise KeyError(key)
        return self.p[key]


def _scenario(fn, *, role="ops_manager", user="maker-1", config=None):
    async def go():
        import asyncpg
        from apps.api.routers.alert_routing import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, entity_id, actor_id, payload))
            return "tx"
        who = {"user": user, "role": role}
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": who["user"], "role": who["role"]}
        app.state.db_pool_cts = pool
        app.state.config_service = config or Cfg()
        app.state.alert_auditor = AlertAuditor(sink)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool, events, who)
        finally:
            for t in ("alert_routing_policies", "alert_oncall_rotas", "alert_oncall_overrides", "local_auth_accounts"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


def T(kind, ref, *channels):
    return {"kind": kind, "ref": ref, "channels": list(channels)}


def good_policy(email="ops@bank.example", scope_id=None):
    return {"scope_id": scope_id, "rules": [
        {"id": "p0", "severities": ["P0"], "targets": [T("external", email, "email"), T("role", "ops_manager", "bell")],
         "escalation": [{"level": 1, "after_minutes": 10, "targets": [T("role", "bank_it_admin", "email", "bell")]}], "repeat_minutes": 30},
        {"id": "rest", "targets": [T("role", "ops_manager", "bell")]}]}


async def _propose(client, level="BANK", scope=None, policy=None, note="n"):
    return await client.post("/v1/admin/alert-routing/policies", json={"level": level, "scope_id": scope, "policy": policy or good_policy(scope_id=scope), "note": note})


def test_a_policy_is_proposed_then_approved_by_someone_else_and_becomes_active():
    async def fn(client, bank, pool, events, who):
        r = await _propose(client)
        assert r.status_code == 201 and r.json()["status"] == "PENDING" and r.json()["version"] == 1
        pid = r.json()["policy_id"]
        who.update(user="maker-1", role="bank_it_admin")
        assert (await client.post(f"/v1/admin/alert-routing/policies/{pid}/approve")).status_code == 403          # the proposer cannot approve
        who.update(user="checker-2", role="bank_it_admin")
        a = await client.post(f"/v1/admin/alert-routing/policies/{pid}/approve")
        assert a.status_code == 200 and a.json()["status"] == "ACTIVE" and a.json()["approved_by"] == "checker-2"
        view = (await client.get("/v1/admin/alert-routing/policies", params={"level": "BANK"})).json()
        assert view["active"]["policy"]["rules"][0]["id"] == "p0" and view["active"]["record"]["version"] == 1 and view["pending"] == [] and view["used_default"] is False
        assert [e[3]["action"] for e in events if e[0] == "ALERT_ROUTING_POLICY_CHANGED"] == ["PROPOSED", "APPROVED"]
    _scenario(fn)


def test_an_invalid_policy_is_a_422_with_the_reasons():
    async def fn(client, bank, pool, events, who):
        r = await _propose(client, policy={"rules": [{"id": "x", "severities": ["P1"], "targets": [T("role", "a", "email")]}]})
        assert r.status_code == 422 and "p0_not_covered" in r.json()["detail"]["codes"]
        assert (await client.get("/v1/admin/alert-routing/pending")).json()["pending"] == []
    _scenario(fn)


def test_a_pending_proposal_can_be_rejected_and_then_it_is_closed():
    async def fn(client, bank, pool, events, who):
        pid = (await _propose(client)).json()["policy_id"]
        who.update(user="checker-2", role="bank_it_admin")
        r = await client.post(f"/v1/admin/alert-routing/policies/{pid}/reject", json={"note": "too broad"})
        assert r.status_code == 200 and r.json()["status"] == "REJECTED"
        assert (await client.post(f"/v1/admin/alert-routing/policies/{pid}/approve")).status_code == 409
        assert (await client.post("/v1/admin/alert-routing/policies/nope/approve")).status_code == 404
    _scenario(fn)


def test_the_pending_queue_and_the_scopes_with_policies_are_listed():
    async def fn(client, bank, pool, events, who):
        a = (await _propose(client)).json()["policy_id"]
        await _propose(client, "PU", "PU1")
        pending = (await client.get("/v1/admin/alert-routing/pending")).json()["pending"]
        assert sorted((p["scope_level"], p["scope_id"]) for p in pending) == [("BANK", None), ("PU", "PU1")]
        who.update(user="checker-2", role="bank_it_admin")
        await client.post(f"/v1/admin/alert-routing/policies/{a}/approve")
        scopes = (await client.get("/v1/admin/alert-routing/scopes")).json()["scopes"]
        assert [(s["scope_level"], s["scope_id"]) for s in scopes] == [("BANK", None)]
    _scenario(fn)


def test_with_no_active_policy_the_view_shows_the_default_that_is_in_force():
    async def fn(client, bank, pool, events, who):
        view = (await client.get("/v1/admin/alert-routing/policies", params={"level": "BANK"})).json()
        assert view["active"] is None and view["used_default"] is True
        assert {r["id"] for r in view["default_policy"]["rules"]} >= {"default-p0", "default-p3"}
    _scenario(fn, config=Cfg(**{"alerts.email_recipients": "ops@x.in"}))


def test_the_history_of_a_scope_lists_every_version():
    async def fn(client, bank, pool, events, who):
        for i in range(2):
            pid = (await _propose(client, policy=good_policy(f"v{i}@x.in"))).json()["policy_id"]
            who.update(user="checker-2", role="bank_it_admin")
            await client.post(f"/v1/admin/alert-routing/policies/{pid}/approve")
            who.update(user="maker-1", role="ops_manager")
        view = (await client.get("/v1/admin/alert-routing/policies", params={"level": "BANK"})).json()
        assert [(h["version"], h["status"]) for h in view["history"]] == [(2, "ACTIVE"), (1, "SUPERSEDED")]
    _scenario(fn)


def test_the_simulator_says_who_would_be_told_without_sending_anything_and_masks_addresses():
    async def fn(client, bank, pool, events, who):
        await pool.execute("INSERT INTO platform.local_auth_accounts (user_id, bank_id, entity_type, entity_id, username, password_hash, role, email) VALUES ($1,$2,'BANK',$2,$1,'x','ops_manager','boss@bank.example')",
                           f"{bank}-boss", bank)
        pid = (await _propose(client)).json()["policy_id"]
        who.update(user="checker-2", role="bank_it_admin")
        await client.post(f"/v1/admin/alert-routing/policies/{pid}/approve")
        r = await client.post("/v1/admin/alert-routing/simulate", json={"severity": "P0", "component": "redis"})
        assert r.status_code == 200
        body = r.json()
        assert [m["rule_id"] for m in body["matched"]] == ["p0"] and [s["level"] for s in body["steps"]] == [0, 1] and body["repeat_minutes"] == 30
        first = body["steps"][0]
        assert {"kind": "external", "ref": "o***@bank.example"} in [{"kind": t["kind"], "ref": t["ref"]} for t in first["targets"]]
        assert ("bell", f"{bank}-boss") in {(d["channel"], d["recipient_ref"]) for d in first["deliveries"]}
        assert "ops@bank.example" not in r.text and "boss@bank.example" not in r.text
        assert body["held"] is False and body["used_default"] is False
    _scenario(fn)


def test_the_simulator_can_be_asked_about_another_time_and_scope():
    async def fn(client, bank, pool, events, who):
        policy = {"rules": [{"id": "p0", "severities": ["P0"], "targets": [T("role", "ops_manager", "bell", "email")]},
                            {"id": "low", "severities": ["P2"], "quiet_hold": True, "targets": [T("role", "ops_manager", "bell")]}]}
        pid = (await _propose(client, policy=policy)).json()["policy_id"]
        who.update(user="checker-2", role="bank_it_admin")
        await client.post(f"/v1/admin/alert-routing/policies/{pid}/approve")
        night = (await client.post("/v1/admin/alert-routing/simulate", json={"severity": "P2", "at": "2026-11-18T22:00:00+05:30"})).json()
        noon = (await client.post("/v1/admin/alert-routing/simulate", json={"severity": "P2", "at": "2026-11-18T12:00:00+05:30"})).json()
        assert night["held"] is True and noon["held"] is False
        assert (await client.post("/v1/admin/alert-routing/simulate", json={"severity": "P9"})).status_code == 422
    _scenario(fn, config=Cfg())


def test_the_channel_status_says_what_is_configured_and_flags_a_public_mail_provider():
    async def fn(client, bank, pool, events, who):
        body = (await client.get("/v1/admin/alert-routing/channels")).json()
        assert body["email"]["configured"] is True and body["email"]["host"] == "smtp.gmail.com" and body["email"]["public_provider"] is True
        assert body["whatsapp"]["configured"] is False and body["bell"]["configured"] is True
        assert body["email_recipients"] == 2 and "secret" not in str(body).lower()
    _scenario(fn, config=Cfg(platform={"smtp.host": "smtp.gmail.com", "smtp.port": "587", "smtp.security": "starttls", "smtp.username": "x@9va.in"},
                             **{"alerts.email_recipients": "a@x.in, b@x.in"}))


def test_the_channel_status_with_nothing_configured_says_so():
    async def fn(client, bank, pool, events, who):
        body = (await client.get("/v1/admin/alert-routing/channels")).json()
        assert body["email"]["configured"] is False and body["email"]["public_provider"] is False and body["email_recipients"] == 0
    _scenario(fn)


def test_roles_read_roles_cannot_change_and_others_cannot_see_it():
    async def fn(client, bank, pool, events, who):
        assert (await client.get("/v1/admin/alert-routing/policies", params={"level": "BANK"})).status_code == 200
        assert (await _propose(client)).status_code == 403
        assert (await client.post("/v1/admin/alert-routing/policies/x/approve")).status_code == 403
    _scenario(fn, role="compliance_officer")

    async def other(client, bank, pool, events, who):
        assert (await client.get("/v1/admin/alert-routing/policies", params={"level": "BANK"})).status_code == 403
        assert (await client.post("/v1/admin/alert-routing/simulate", json={"severity": "P0"})).status_code == 403
    _scenario(other, role="fraud_analyst")


def test_only_the_admin_role_approves_and_the_ops_manager_proposes():
    async def fn(client, bank, pool, events, who):
        pid = (await _propose(client)).json()["policy_id"]
        who.update(user="other-ops", role="ops_manager")
        assert (await client.post(f"/v1/admin/alert-routing/policies/{pid}/approve")).status_code == 403          # an ops manager proposes, an IT admin approves
    _scenario(fn)


def test_a_pu_policy_must_name_its_scope():
    async def fn(client, bank, pool, events, who):
        r = await _propose(client, "PU", None, policy=good_policy())
        assert r.status_code == 422 and "scope_required" in r.json()["detail"]["codes"]
    _scenario(fn)


def test_an_approver_can_read_the_content_of_a_proposal_before_deciding():
    async def fn(client, bank, pool, events, who):
        pid = (await _propose(client)).json()["policy_id"]
        who.update(user="checker-2", role="bank_it_admin")
        r = await client.get(f"/v1/admin/alert-routing/policies/{pid}")
        assert r.status_code == 200
        body = r.json()
        assert body["record"]["policy_id"] == pid and body["record"]["status"] == "PENDING"
        assert [rule["id"] for rule in body["policy"]["rules"]] == ["p0", "rest"] and body["policy"]["rules"][0]["targets"][0]["ref"] == "ops@bank.example"
        assert (await client.get("/v1/admin/alert-routing/policies/nope")).status_code == 404
    _scenario(fn)


def test_other_banks_proposals_cannot_be_read():
    async def fn(client, bank, pool, events, who):
        pid = (await _propose(client)).json()["policy_id"]
        await pool.execute("UPDATE platform.alert_routing_policies SET bank_id = $2 WHERE policy_id = $1", pid, bank + "-other")
        assert (await client.get(f"/v1/admin/alert-routing/policies/{pid}")).status_code == 404
        await pool.execute("DELETE FROM platform.alert_routing_policies WHERE bank_id = $1", bank + "-other")
    _scenario(fn)
