"""RoutingService on the real dev YugabyteDB: an incident in, the final routing out. It combines the stored Bank/PU/SMB policies (or the default built from today's
flat settings), the calendar, and the people on call right now. The same call serves escalation, the send path and the simulator."""
import asyncio
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.alerting.oncall import Rota, Shift
from shared.alerting.oncall_store import OnCallStore
from shared.alerting.policy_store import PolicyStore
from shared.alerting.routing_policy import EscalationStep, IncidentFacts, Policy, Rule, TargetSpec
from shared.alerting.routing_service import RoutingService

ROOT = Path(__file__).resolve().parents[3]
HOST, PORT = "localhost", 15433
NOW = datetime.now(timezone.utc)


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


@pytest.fixture(scope="module", autouse=True)
def migrated():
    env = {**os.environ, "PLATFORM_DB_URL": f"postgresql+asyncpg://yugabyte:yugabyte@{HOST}:{PORT}/yugabyte"}
    r = subprocess.run([sys.executable, "-m", "alembic", "-c", "infra/migrations/platform/alembic.ini", "upgrade", "head"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


class Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def T(kind, ref, *channels):
    return TargetSpec(kind=kind, ref=ref, channels=list(channels))


def _run(fn, cfg=None):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        policies, oncall = PolicyStore(pool, pii_key="k-not-a-secret"), OnCallStore(pool)
        svc = RoutingService(config_service=cfg or Cfg(**{"alerts.email_recipients": "ops@x.in", "alerting.timezone": "Asia/Kolkata"}), bank_id=bank,
                             policy_store=policies, oncall_store=oncall)
        try:
            return await fn(svc, policies, oncall, bank, pool)
        finally:
            for t in ("alert_routing_policies", "alert_oncall_overrides", "alert_oncall_rotas"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


async def _activate(store, bank, level, scope, policy):
    p = await store.propose(bank, level, scope, policy, proposed_by="maker")
    await store.approve(bank, p.policy_id, approved_by="checker")


def _bank_policy():
    return Policy(rules=[Rule(id="p0", severities=["P0"], targets=[T("oncall", "ops", "email", "bell"), T("role", "ops_manager", "bell")],
                              escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("role", "bank_it_admin", "email", "bell")])], repeat_minutes=30),
                       Rule(id="rest", targets=[T("role", "ops_manager", "bell")])])


def _incident(**over):
    base = {"incident_id": "inc1", "severity": "P0", "component": "redis", "pu_id": None, "smb_id": None, "state": "OPEN"}
    base.update(over)
    return base


def test_the_stored_bank_policy_and_the_people_on_call_make_the_routing():
    async def go(svc, policies, oncall, bank, pool):
        await _activate(policies, bank, "BANK", None, _bank_policy())
        await oncall.save_rota(bank, "ops", Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["alice"])]), actor="m")
        r = await svc.route_incident(_incident(), NOW)
        assert sorted((t.kind, t.ref) for t in r.routing.steps[0].targets) == [("role", "ops_manager"), ("user", "alice")]
        assert [(s.level, s.after_minutes) for s in r.routing.steps] == [(0, 0), (1, 10)] and r.routing.repeat_minutes == 30 and not r.routing.warnings
    _run(go)


def test_with_no_stored_policy_the_default_from_the_flat_settings_applies():
    async def go(svc, policies, oncall, bank, pool):
        r = await svc.route_incident(_incident(), NOW)
        assert ("external", "ops@x.in") in {(t.kind, t.ref) for t in r.routing.steps[0].targets} and r.used_default is True
    _run(go)


def test_pu_and_smb_policies_apply_to_incidents_of_that_pu_and_smb_only():
    async def go(svc, policies, oncall, bank, pool):
        await _activate(policies, bank, "BANK", None, _bank_policy())
        await _activate(policies, bank, "PU", "PU1", Policy(rules=[Rule(id="pu", targets=[T("role", "pu_head", "bell")])], scope_id="PU1"))
        mine = await svc.route_incident(_incident(pu_id="PU1"), NOW)
        other = await svc.route_incident(_incident(pu_id="PU2"), NOW)
        assert ("role", "pu_head") in {(t.kind, t.ref) for t in mine.routing.steps[0].targets}
        assert ("role", "pu_head") not in {(t.kind, t.ref) for t in other.routing.steps[0].targets}
    _run(go)


def test_the_owning_team_comes_from_the_component_to_team_setting():
    async def go(svc, policies, oncall, bank, pool):
        await _activate(policies, bank, "BANK", None, Policy(rules=[Rule(id="data", teams=["data"], severities=["P0"], targets=[T("role", "dba", "bell", "email")]),
                                                                     Rule(id="rest", targets=[T("role", "ops_manager", "bell", "email")])]))
        r = await svc.route_incident(_incident(component="yugabyte"), NOW)
        assert [(t.kind, t.ref) for t in r.routing.steps[0].targets] == [("role", "dba")] and r.facts.owning_team == "data"
        assert [(t.kind, t.ref) for t in (await svc.route_incident(_incident(component="vllm"), NOW)).routing.steps[0].targets] == [("role", "ops_manager")]
    _run(go, cfg=Cfg(**{"alerting.component_teams": '{"yugabyte": "data", "redis": "data"}', "alerting.timezone": "Asia/Kolkata"}))


def test_an_unfilled_rota_is_reported_and_the_rest_of_the_audience_still_gets_it():
    async def go(svc, policies, oncall, bank, pool):
        await _activate(policies, bank, "BANK", None, _bank_policy())
        r = await svc.route_incident(_incident(), NOW)                          # no rota "ops" exists
        assert "oncall_unfilled:ops" in r.routing.warnings and [(t.kind, t.ref) for t in r.routing.steps[0].targets] == [("role", "ops_manager")]
    _run(go)


def test_the_simulator_form_takes_facts_instead_of_an_incident():
    async def go(svc, policies, oncall, bank, pool):
        await _activate(policies, bank, "BANK", None, _bank_policy())
        r = await svc.route_facts(IncidentFacts(severity="P0", component="redis"), NOW)
        assert r.routing.steps and r.facts.component == "redis"
    _run(go)


def test_a_broken_policy_store_degrades_to_the_default_with_a_warning():
    async def go(svc, policies, oncall, bank, pool):
        class Broken:
            async def effective(self, *a, **k):
                raise ConnectionError("db down")
        svc._policies = Broken()
        r = await svc.route_incident(_incident(), NOW)
        assert r.used_default and "policy_store_unavailable" in r.routing.warnings and r.routing.steps
    _run(go)
