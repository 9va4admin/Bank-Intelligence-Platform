"""Go-Live alerting readiness checks on the real dev YugabyteDB: routing policy, on-call coverage, channels, a recent delivery on each channel, stale incidents."""
import asyncio
import functools
import socket
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from shared.alerting.oncall import Fallback, Rota, Shift
from shared.alerting.oncall_store import OnCallStore
from shared.alerting.policy_store import PolicyStore
from shared.alerting.proofs import ProofStore
from shared.alerting.readiness import alerting_readiness
from shared.alerting.routing_policy import EscalationStep, Policy, Rule, TargetSpec

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    def __init__(self, platform=None, **v):
        self.v = {"alerting.timezone": "Asia/Kolkata", "alerting.oncall_gap_days": 7, "alerting.oncall_gap_step_minutes": 30,
                  "alerting.readiness_test_send_days": 7, "alerting.readiness_audit_proof_days": 30, "alerting.readiness_open_incident_hours": 24,
                  "alerting.public_mail_hosts": '["smtp.gmail.com"]', "alerts.email_recipients": "", "alerts.whatsapp_recipients": "",
                  "alerting.bell_roles": '["ops_manager", "bank_it_admin"]', "alerting.bell_min_priority": "P3", **v}
        self.p = platform or {}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]

    def get_platform(self, key):
        if key not in self.p:
            raise KeyError(key)
        return self.p[key]


BANKS: list[str] = []
TABLES = ("alert_deliveries", "alert_incidents", "alert_routing_policies", "alert_oncall_rotas", "alert_readiness_proofs")


def _bank():
    BANKS.append(f"rd-{uuid.uuid4().hex[:8]}")
    return BANKS[-1]


def db(fn):
    """Run the async test body on a real pool, and remove every row the test's banks created."""
    @functools.wraps(fn)
    def wrapper():
        async def go():
            pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
            try:
                await fn(pool)
            finally:
                for t in TABLES:
                    await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id = ANY($1::text[])", BANKS)
                BANKS.clear()
                await pool.close()
        asyncio.run(go())
    del wrapper.__wrapped__          # pytest must not look for a fixture named like the test's pool argument
    return wrapper


def T(kind, ref, *channels):
    return TargetSpec(kind=kind, ref=ref, channels=list(channels))


def good_policy():
    return Policy(rules=[Rule(id="p0", severities=["P0"], hours="always", targets=[T("role", "ops_manager", "email", "bell")],
                              escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("role", "bank_it_admin", "email", "bell")])]),
                         Rule(id="rest", severities=[], hours="always", targets=[T("role", "ops_manager", "bell")])])


async def run(pool, bank, cfg, **kw):
    stores = dict(policy_store=PolicyStore(pool, pii_key="readiness-key-not-a-secret"), oncall_store=OnCallStore(pool), proof_store=ProofStore(pool))
    items = await alerting_readiness(config=cfg, bank_id=bank, pool=pool, **{**stores, **kw})
    return {i.check_id: i for i in items}


async def approve_good(pool, bank):
    store = PolicyStore(pool, pii_key="readiness-key-not-a-secret")
    rec = await store.propose(bank, "BANK", None, good_policy(), proposed_by="maker")
    await store.approve(bank, rec.policy_id, approved_by="checker")


@db
async def test_every_check_is_reported_with_a_label_and_an_action(pool):
    items = await run(pool, _bank(), Cfg())
    assert {"alert_routing", "alert_oncall", "alert_email", "alert_recent_delivery", "alert_open_incidents", "alert_audit_path"} <= set(items)
    for i in items.values():
        assert i.label and i.status in {"PASS", "WARN", "FAIL", "SKIP"} and i.detail


@db
async def test_a_bank_with_only_the_default_bell_policy_fails_because_critical_alerts_need_two_channels(pool):
    items = await run(pool, _bank(), Cfg())
    assert items["alert_routing"].status == "FAIL"
    assert items["alert_routing"].action_url == "/admin/alert-routing"


@db
async def test_an_approved_policy_that_covers_critical_alerts_on_two_channels_passes(pool):
    bank = _bank()
    await approve_good(pool, bank)
    assert (await run(pool, bank, Cfg()))["alert_routing"].status == "PASS"


@db
async def test_no_rota_is_a_warning_a_24x7_rota_passes_and_a_rota_with_a_gap_fails(pool):
    bank = _bank()
    assert (await run(pool, bank, Cfg()))["alert_oncall"].status == "WARN"
    store = OnCallStore(pool)
    await store.save_rota(bank, "ops", Rota(shifts=[Shift(days=[0, 1, 2, 3, 4, 5, 6], start="00:00", end="23:59", users=["a"])], fallback=Fallback(users=["fb"])), actor="t")
    assert (await run(pool, bank, Cfg()))["alert_oncall"].status == "PASS"
    gap = _bank()
    await store.save_rota(gap, "ops", Rota(shifts=[Shift(days=[0], start="09:00", end="10:00", users=["a"])]), actor="t")
    assert (await run(pool, gap, Cfg()))["alert_oncall"].status == "FAIL"


@db
async def test_email_not_set_up_fails_a_public_provider_is_a_pilot_warning_and_an_own_relay_passes(pool):
    assert (await run(pool, _bank(), Cfg()))["alert_email"].status == "FAIL"
    assert (await run(pool, _bank(), Cfg(platform={"smtp.host": "smtp.gmail.com"})))["alert_email"].status == "WARN"
    assert (await run(pool, _bank(), Cfg(platform={"smtp.host": "mail.bank.example"})))["alert_email"].status == "PASS"


async def _delivery(pool, bank, channel, status, age_days):
    await pool.execute(
        "INSERT INTO platform.alert_deliveries (delivery_id, bank_id, incident_id, idempotency_key, channel, recipient_ref, status, created_at, completed_at) "
        "VALUES ($1,$2,'i',$1,$3,'x',$4,$5,$5)", uuid.uuid4().hex, bank, channel, status, datetime.now(timezone.utc) - timedelta(days=age_days))


@db
async def test_a_recent_delivery_is_needed_on_each_channel_that_is_set_up(pool):
    bank = _bank()
    cfg = Cfg(platform={"smtp.host": "mail.bank.example"})
    assert (await run(pool, bank, cfg))["alert_recent_delivery"].status == "FAIL"           # email is set up, nothing ever sent
    await _delivery(pool, bank, "email", "SENT", 10)
    assert (await run(pool, bank, cfg))["alert_recent_delivery"].status == "FAIL"           # too old
    await _delivery(pool, bank, "email", "SENT", 1)
    await _delivery(pool, bank, "bell", "SENT", 1)
    assert (await run(pool, bank, cfg))["alert_recent_delivery"].status == "PASS"


@db
async def test_an_incident_open_for_too_long_is_a_warning(pool):
    bank = _bank()
    assert (await run(pool, bank, Cfg()))["alert_open_incidents"].status == "PASS"
    await pool.execute("INSERT INTO platform.alert_incidents (incident_id, bank_id, dedup_key, alert_id, component, severity, state, summary, opened_at) "
                       "VALUES ($1,$2,'d','a','redis','P1','OPEN','s',$3)", uuid.uuid4().hex, bank, datetime.now(timezone.utc) - timedelta(hours=30))
    assert (await run(pool, bank, Cfg()))["alert_open_incidents"].status == "WARN"


@db
async def test_a_failing_store_gives_a_warning_for_that_item_and_never_breaks_the_rest(pool):
    class Broken:
        async def get_active(self, *a, **k):
            raise RuntimeError("down")

        async def list_rotas(self, *a, **k):
            raise RuntimeError("down")
    items = await run(pool, _bank(), Cfg(), policy_store=Broken(), oncall_store=Broken())
    assert items["alert_routing"].status == "WARN" and items["alert_oncall"].status == "WARN"
    assert items["alert_email"].status == "FAIL"


@db
async def test_the_audit_path_must_have_been_proved_recently_and_successfully(pool):
    bank = _bank()
    store = ProofStore(pool)
    assert (await run(pool, bank, Cfg()))["alert_audit_path"].status == "FAIL"              # never proved
    await store.record(bank, "audit_path", False, {"reason": "write_failed"}, "admin-1")
    failed = (await run(pool, bank, Cfg()))["alert_audit_path"]
    assert failed.status == "FAIL" and failed.action_url == "/admin/alert-settings"
    await store.record(bank, "audit_path", True, {"reason": "ok"}, "admin-1")
    ok = (await run(pool, bank, Cfg()))["alert_audit_path"]
    assert ok.status == "PASS" and "admin-1" in ok.detail


@db
async def test_a_proof_older_than_the_window_is_a_warning(pool):
    bank = _bank()
    await ProofStore(pool).record(bank, "audit_path", True, {"reason": "ok"}, "admin-1")
    await pool.execute("UPDATE platform.alert_readiness_proofs SET ran_at = $2 WHERE bank_id = $1", bank, datetime.now(timezone.utc) - timedelta(days=45))
    assert (await run(pool, bank, Cfg()))["alert_audit_path"].status == "WARN"


@db
async def test_without_a_proof_store_the_audit_item_is_a_warning(pool):
    items = await run(pool, _bank(), Cfg(), proof_store=None)
    assert items["alert_audit_path"].status == "WARN"
