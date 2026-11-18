"""The first notification of an alert, end to end on the real dev YugabyteDB: a stored bank policy and an on-call rota decide who is told (real routing service, real
delivery outbox, real bell inbox); a bank with no policy gets exactly what the flat settings always gave; a held low-priority alert is queued for the next working morning."""
import asyncio
import socket
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput, dispatch_platform_alert
from shared.alerting.bell import BellChannel
from shared.alerting.delivery import DeliveryStore
from shared.alerting.engine import DeliveryEngine, DeliveryPolicy
from shared.alerting.factory import build_routing_service
from shared.alerting.inbox import InboxStore
from shared.alerting.oncall import Rota, Shift
from shared.alerting.oncall_store import OnCallStore
from shared.alerting.policy_store import PolicyStore
from shared.alerting.routing_policy import Policy, Rule, TargetSpec
from shared.alerting.templates import TemplateSettings
from shared.notifications.dispatcher import NotificationDispatcher

pytestmark = pytest.mark.integration
HOST, PORT = "localhost", 15433
KEY, PEPPER = "dispatch-routing-key-not-a-secret", "dispatch-routing-pepper-not-a-secret"
WED_10PM_IST = datetime(2026, 11, 18, 22, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


class Cfg:
    def __init__(self, **v):
        self.v = {"alerting.timezone": "Asia/Kolkata", **v}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]

    async def get_secret(self, key):
        return KEY if key.endswith("pii_enc_key") else PEPPER


def T(kind, ref, *channels):
    return TargetSpec(kind=kind, ref=ref, channels=list(channels))


def _run(fn, **cfg):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        config = Cfg(**cfg)
        dispatcher = NotificationDispatcher(bank)
        dispatcher.connect(bell_channel=BellChannel(InboxStore(pool), TemplateSettings()))
        engine = DeliveryEngine(DeliveryStore(pool, pii_key=KEY, pepper=PEPPER), dispatcher, None, DeliveryPolicy())
        routing = build_routing_service(config, bank, pool)
        try:
            return await fn(pool, bank, engine, routing, config)
        finally:
            for t in ("alert_routing_policies", "alert_oncall_overrides", "alert_oncall_rotas", "alert_deliveries", "user_notifications", "local_auth_accounts"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def _alert(bank, **kw):
    base = dict(bank_id=bank, event_type="COMPONENT_DOWN", component="redis", message="redis is not responding", severity="CRITICAL", priority="P0",
                incident_id=f"inc-{uuid.uuid4().hex[:6]}", occasion="t1")
    base.update(kw)
    return DispatchAlertInput(**base)


async def _dispatch(pool, bank, engine, routing, config, alert):
    return await dispatch_platform_alert(alert, dispatcher=object(), config_service=config, delivery_engine=engine, db_pool=pool, routing_service=routing)


async def _who(pool, bank):
    rows = await pool.fetch("SELECT user_id FROM platform.user_notifications WHERE bank_id=$1", bank)
    return sorted(r["user_id"] for r in rows)


@pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")
def test_a_stored_policy_and_the_on_call_rota_decide_who_is_told():
    async def go(pool, bank, engine, routing, config):
        store, oncall = PolicyStore(pool, pii_key=KEY), OnCallStore(pool)
        await oncall.save_rota(bank, "ops", Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["on-call-alice"])]), actor="m")
        policy = Policy(rules=[Rule(id="p0", severities=["P0"], targets=[T("oncall", "ops", "bell"), T("user", "duty-manager", "bell"), T("external", "ops@bank.example", "email")]),
                               Rule(id="rest", targets=[T("user", "duty-manager", "bell")])])
        p = await store.propose(bank, "BANK", None, policy, proposed_by="maker")
        await store.approve(bank, p.policy_id, approved_by="checker")
        res = await _dispatch(pool, bank, engine, routing, config, _alert(bank))
        assert res.routed is True
        assert await _who(pool, bank) == ["duty-manager", "on-call-alice"]                    # the people the policy names, with today's on-call resolved
        rows = await pool.fetch("SELECT channel, status FROM platform.alert_deliveries WHERE bank_id=$1 ORDER BY channel", bank)
        assert [(r["channel"], r["status"]) for r in rows if r["channel"] == "bell"] == [("bell", "SENT"), ("bell", "SENT")]
    _run(go)


@pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")
def test_a_bank_with_no_policy_gets_what_the_flat_settings_always_gave():
    async def go(pool, bank, engine, routing, config):
        await pool.execute("INSERT INTO platform.local_auth_accounts (user_id, bank_id, entity_type, entity_id, username, password_hash, role) VALUES ($1,$2,'BANK',$2,$1,'x','ops_manager')",
                           f"{bank}-mgr", bank)
        res = await _dispatch(pool, bank, engine, routing, config, _alert(bank))
        assert res.routed is True                                                             # the default policy is itself the routing
        assert await _who(pool, bank) == [f"{bank}-mgr"]                                     # the bell roles, as before
    _run(go, **{"alerting.bell_roles": '["ops_manager"]'})


@pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")
def test_a_held_low_priority_alert_waits_in_the_queue_for_the_next_working_morning():
    async def go(pool, bank, engine, routing, config):
        store = PolicyStore(pool, pii_key=KEY)
        policy = Policy(rules=[Rule(id="p0", severities=["P0"], targets=[T("user", "duty", "bell"), T("external", "a@x.in", "email")]),
                               Rule(id="low", severities=["P2", "P3"], quiet_hold=True, targets=[T("user", "duty", "bell")])])
        p = await store.propose(bank, "BANK", None, policy, proposed_by="maker")
        await store.approve(bank, p.policy_id, approved_by="checker")
        res = await _dispatch(pool, bank, engine, routing, config, _alert(bank, priority="P2", severity="WARN", occurred_at=WED_10PM_IST))
        assert res.sent is False and res.queued_for_retry == 1 and await _who(pool, bank) == []          # nothing yet: held
        row = await pool.fetchrow("SELECT status, next_attempt_at > NOW() AS later FROM platform.alert_deliveries WHERE bank_id=$1", bank)
        assert row["status"] == "PENDING" and row["later"] is True
        await pool.execute("UPDATE platform.alert_deliveries SET next_attempt_at = NOW() - INTERVAL '1 second' WHERE bank_id=$1", bank)
        out = await engine.process_due(bank, resolve_targets=lambda c: _nothing())
        assert out.sent == 1 and await _who(pool, bank) == ["duty"]                           # the next outbox run after opening time delivers it
    _run(go)


async def _nothing():
    return []
