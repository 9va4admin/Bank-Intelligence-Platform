"""OnCallStore on the real dev YugabyteDB: rotas, overrides (swaps and cover), who is on call now, gap detection, bank isolation, and an audit event naming the actor."""
import asyncio
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.alerting.audit import AlertAuditor
from shared.alerting.oncall import Fallback, Rota, Shift
from shared.alerting.oncall_store import OnCallStore, OverrideInvalid, RotaInvalid
from shared.alerting.routing_policy import Calendar

ROOT = Path(__file__).resolve().parents[3]
HOST, PORT = "localhost", 15433
CAL = Calendar(timezone="Asia/Kolkata")


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


ALL_DAY = Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["alice"])])
NOW = datetime.now(timezone.utc)


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, entity_id, actor_id, payload))
            return "tx"
        try:
            return await fn(OnCallStore(pool, auditor=AlertAuditor(sink)), bank, pool, events)
        finally:
            await pool.execute("DELETE FROM platform.alert_oncall_overrides WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM platform.alert_oncall_rotas WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def test_a_rota_is_saved_read_back_replaced_and_audited_with_the_actor():
    async def go(store, bank, pool, events):
        v1 = await store.save_rota(bank, "ops", ALL_DAY, actor="manager-1")
        assert v1 == 1 and (await store.get_rota(bank, "ops")).shifts[0].users == ["alice"]
        v2 = await store.save_rota(bank, "ops", Rota(shifts=[Shift(days=[0], start="09:00", end="10:00", users=["bob"])]), actor="manager-2")
        assert v2 == 2 and (await store.get_rota(bank, "ops")).shifts[0].users == ["bob"]
        assert [e[0] for e in events] == ["ALERT_ONCALL_CHANGED", "ALERT_ONCALL_CHANGED"] and events[1][2] == "manager-2" and events[1][3]["action"] == "ROTA_SAVED"
        assert [r["name"] for r in await store.list_rotas(bank)] == ["ops"] and await store.get_rota("another-bank", "ops") is None
    _run(go)


def test_a_bad_rota_is_refused_with_reasons():
    async def go(store, bank, pool, events):
        with pytest.raises(RotaInvalid) as err:
            await store.save_rota(bank, "ops", Rota(shifts=[Shift(days=[9], start="25:00", end="10:00", users=[])]), actor="m")
        assert {"bad_day", "bad_time", "shift_needs_people"} <= set(err.value.codes)
        assert await store.get_rota(bank, "ops") is None and events == []
    _run(go)


def test_who_is_on_call_now_follows_the_rota_and_an_override_replaces_it_until_it_ends():
    async def go(store, bank, pool, events):
        await store.save_rota(bank, "ops", ALL_DAY, actor="m")
        assert (await store.current(bank, "ops", NOW, CAL)).users == ["alice"]
        oid = await store.add_override(bank, "ops", "bob", NOW - timedelta(hours=1), NOW + timedelta(hours=1), reason="swap", actor="m")
        r = await store.current(bank, "ops", NOW, CAL)
        assert r.users == ["bob"] and r.source == "override" and events[-1][3]["action"] == "OVERRIDE_ADDED"
        assert (await store.current(bank, "ops", NOW + timedelta(hours=2), CAL)).users == ["alice"]          # it has ended by then
        assert await store.remove_override(bank, oid, actor="m") is True
        assert (await store.current(bank, "ops", NOW, CAL)).users == ["alice"] and events[-1][3]["action"] == "OVERRIDE_REMOVED"
        assert await store.remove_override(bank, oid, actor="m") is False
    _run(go)


def test_an_override_must_end_after_it_starts_and_name_a_known_rota():
    async def go(store, bank, pool, events):
        await store.save_rota(bank, "ops", ALL_DAY, actor="m")
        with pytest.raises(OverrideInvalid):
            await store.add_override(bank, "ops", "bob", NOW, NOW, reason="x", actor="m")
        with pytest.raises(OverrideInvalid):
            await store.add_override(bank, "no-such-rota", "bob", NOW, NOW + timedelta(hours=1), reason="x", actor="m")
    _run(go)


def test_an_unknown_rota_has_nobody_on_call():
    async def go(store, bank, pool, events):
        assert (await store.current(bank, "nope", NOW, CAL)).users == []
        many = await store.current_many(bank, ["ops", "dba"], NOW, CAL)
        assert set(many) == {"ops", "dba"} and many["ops"].users == []
    _run(go)


def test_overrides_are_listed_for_a_rota_within_a_window_and_never_across_banks():
    async def go(store, bank, pool, events):
        await store.save_rota(bank, "ops", ALL_DAY, actor="m")
        await store.add_override(bank, "ops", "bob", NOW + timedelta(days=1), NOW + timedelta(days=2), reason="cover", actor="m")
        await store.add_override(bank, "ops", "old", NOW - timedelta(days=10), NOW - timedelta(days=9), reason="past", actor="m")
        listed = await store.overrides(bank, "ops", since=NOW, days=7)
        assert [o["user_id"] for o in listed] == ["bob"] and listed[0]["reason"] == "cover"
        assert await store.overrides("another-bank", "ops", since=NOW, days=7) == []
    _run(go)


def test_gaps_in_coverage_can_be_listed_for_the_go_live_check():
    async def go(store, bank, pool, events):
        await store.save_rota(bank, "ops", Rota(shifts=[Shift(days=[0, 1, 2, 3, 4], start="09:30", end="18:00", users=["a"])]), actor="m")
        assert await store.gaps(bank, "ops", CAL, start=NOW, days=7, step_minutes=60)
        await store.save_rota(bank, "ops", Rota(shifts=[Shift(days=[0, 1, 2, 3, 4], start="09:30", end="18:00", users=["a"])], fallback=Fallback(users=["m"])), actor="m")
        assert await store.gaps(bank, "ops", CAL, start=NOW, days=7, step_minutes=60) == []
        assert await store.gaps(bank, "missing", CAL, start=NOW, days=1, step_minutes=60) != []          # no rota at all is one big gap
    _run(go)


def test_a_routing_result_with_an_on_call_target_becomes_the_people_on_call_now():
    """The pieces together: the policy engine says "the ops on-call", the store says who that is, expansion makes it real people."""
    from shared.alerting.oncall import expand_oncall_targets
    from shared.alerting.routing_policy import IncidentFacts, Policy, Rule, TargetSpec, resolve_routing

    async def go(store, bank, pool, events):
        await store.save_rota(bank, "ops", ALL_DAY, actor="m")
        await store.add_override(bank, "ops", "bob", NOW - timedelta(hours=1), NOW + timedelta(hours=1), reason="swap", actor="m")
        policy = Policy(rules=[Rule(id="p0", severities=["P0"], targets=[TargetSpec(kind="oncall", ref="ops", channels=["email", "bell"]),
                                                                      TargetSpec(kind="role", ref="ops_manager", channels=["bell"])])])
        routing = resolve_routing(IncidentFacts(severity="P0", component="redis"), {"BANK": policy}, CAL, NOW)
        names = [t.ref for s in routing.steps for t in s.targets if t.kind == "oncall"]
        expanded = expand_oncall_targets(routing, await store.current_many(bank, names, NOW, CAL))
        assert sorted((t.kind, t.ref) for t in expanded.steps[0].targets) == [("role", "ops_manager"), ("user", "bob")]
    _run(go)
