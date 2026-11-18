"""Go-Live alerting readiness checks on the real dev YugabyteDB: routing policy, on-call coverage, channels, a recent delivery on each channel, stale incidents."""
import asyncio
import functools
import socket
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from shared.alerting.contacts import ContactStore
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
                  "alerting.readiness_test_send_days": 7, "alerting.readiness_audit_proof_days": 30, "alerting.fire_drill_ack_minutes": 15, "alerting.readiness_drill_days": 90, "alerting.readiness_dns_proof_days": 30, "alerting.mail_dns_risk_accepted": False, "alerting.regulatory_windows": "[]", "alerting.regulatory_windows_pending": False, "alerting.readiness_open_incident_hours": 24,
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
TABLES = ("alert_deliveries", "alert_incidents", "alert_routing_policies", "alert_oncall_rotas", "alert_readiness_proofs", "alert_contacts", "alert_silences")


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
    stores = dict(policy_store=PolicyStore(pool, pii_key="readiness-key-not-a-secret"), oncall_store=OnCallStore(pool), proof_store=ProofStore(pool),
                  contact_store=ContactStore(pool, pii_key="readiness-contacts-key", pepper="readiness-contacts-pepper"))
    items = await alerting_readiness(config=cfg, bank_id=bank, pool=pool, **{**stores, **kw})
    return {i.check_id: i for i in items}


async def approve_good(pool, bank):
    store = PolicyStore(pool, pii_key="readiness-key-not-a-secret")
    rec = await store.propose(bank, "BANK", None, good_policy(), proposed_by="maker")
    await store.approve(bank, rec.policy_id, approved_by="checker")


@db
async def test_every_check_is_reported_with_a_label_and_an_action(pool):
    items = await run(pool, _bank(), Cfg())
    assert {"alert_routing", "alert_oncall", "alert_email", "alert_recent_delivery", "alert_open_incidents", "alert_audit_path", "alert_mail_dns", "alert_simulated", "alert_fire_drill", "alert_contacts", "alert_silences", "alert_regulatory"} <= set(items)
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


FROM = {"smtp.host": "mail.bank.example", "smtp.from_address": "Alerts <alerts@bank.example>"}


@db
async def test_mail_dns_is_skipped_until_a_sending_address_exists_then_must_have_been_checked(pool):
    bank = _bank()
    assert (await run(pool, bank, Cfg()))["alert_mail_dns"].status == "SKIP"
    assert (await run(pool, bank, Cfg(platform=FROM)))["alert_mail_dns"].status == "FAIL"             # never checked


@db
async def test_a_good_mail_dns_check_passes_a_missing_record_fails_by_name_and_an_old_one_warns(pool):
    bank = _bank()
    store = ProofStore(pool)
    await store.record(bank, "mail_dns", False, {"domain": "bank.example", "spf": True, "dmarc": False, "dkim": {"google": False}}, "admin-1")
    bad = (await run(pool, bank, Cfg(platform=FROM)))["alert_mail_dns"]
    assert bad.status == "FAIL" and "DMARC" in bad.detail and "SPF" not in bad.detail and "google" in bad.detail
    await store.record(bank, "mail_dns", True, {"domain": "bank.example", "spf": True, "dmarc": True, "dkim": {}}, "admin-1")
    good = (await run(pool, bank, Cfg(platform=FROM)))["alert_mail_dns"]
    assert good.status == "PASS" and "bank.example" in good.detail
    await pool.execute("UPDATE platform.alert_readiness_proofs SET ran_at = $2 WHERE bank_id = $1 AND ok", bank, datetime.now(timezone.utc) - timedelta(days=45))
    await pool.execute("DELETE FROM platform.alert_readiness_proofs WHERE bank_id = $1 AND NOT ok", bank)
    assert (await run(pool, bank, Cfg(platform=FROM)))["alert_mail_dns"].status == "WARN"


@db
async def test_a_lookup_that_could_not_be_made_says_so_and_an_accepted_risk_passes_with_a_note(pool):
    bank = _bank()
    await ProofStore(pool).record(bank, "mail_dns", False, {"domain": "bank.example", "error": "lookup_failed"}, "admin-1")
    failed = (await run(pool, bank, Cfg(platform=FROM)))["alert_mail_dns"]
    assert failed.status == "FAIL" and "could not be made" in failed.detail
    accepted = (await run(pool, bank, Cfg(platform=FROM, **{"alerting.mail_dns_risk_accepted": True})))["alert_mail_dns"]
    assert accepted.status == "PASS" and "accepted" in accepted.detail.lower()


async def _sim(store, bank, sev, ok=True, **detail):
    await store.record(bank, f"simulation_{sev}", ok, {"severity": sev, "recipients": 2 if ok else 0, **detail}, "admin-1")


@db
async def test_each_of_critical_major_and_warning_must_have_been_simulated_with_someone_told(pool):
    bank = _bank()
    store = ProofStore(pool)
    none = (await run(pool, bank, Cfg()))["alert_simulated"]
    assert none.status == "FAIL" and "P0" in none.detail and "P1" in none.detail and "P2" in none.detail and none.action_url == "/admin/alert-routing"
    await _sim(store, bank, "P0")
    await _sim(store, bank, "P1")
    partly = (await run(pool, bank, Cfg()))["alert_simulated"]
    assert partly.status == "FAIL" and "P2" in partly.detail and "P0" not in partly.detail
    await _sim(store, bank, "P2")
    assert (await run(pool, bank, Cfg()))["alert_simulated"].status == "PASS"


@db
async def test_a_simulation_that_would_tell_nobody_fails_and_names_the_severity(pool):
    bank = _bank()
    store = ProofStore(pool)
    await _sim(store, bank, "P0")
    await _sim(store, bank, "P1", ok=False)
    await _sim(store, bank, "P2")
    item = (await run(pool, bank, Cfg()))["alert_simulated"]
    assert item.status == "FAIL" and "P1" in item.detail and "nobody" in item.detail.lower()


@db
async def test_a_policy_approved_after_the_simulations_makes_them_stale(pool):
    bank = _bank()
    store = ProofStore(pool)
    for sev in ("P0", "P1", "P2"):
        await _sim(store, bank, sev)
    await pool.execute("UPDATE platform.alert_readiness_proofs SET ran_at = $2 WHERE bank_id = $1", bank, datetime.now(timezone.utc) - timedelta(hours=1))
    await approve_good(pool, bank)                                   # approved now: after the simulations
    item = (await run(pool, bank, Cfg()))["alert_simulated"]
    assert item.status == "FAIL" and "changed" in item.detail.lower()


async def _drill(pool, bank, *, started_minutes_ago, acked_after_minutes=None, ran_by="admin-1"):
    """A drill started so long ago, with its incident acknowledged (or not) so many minutes after it started."""
    started = datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago)
    incident = uuid.uuid4().hex
    acked = started + timedelta(minutes=acked_after_minutes) if acked_after_minutes is not None else None
    await pool.execute("INSERT INTO platform.alert_incidents (incident_id, bank_id, dedup_key, alert_id, component, severity, state, summary, opened_at, acked_at, acked_by) "
                       "VALUES ($1,$2,$3,'a','fire-drill','P0',$4,'drill',$5,$6,$7)", incident, bank, f"d-{incident}", "ACKED" if acked else "OPEN", started, acked, "oncall-1" if acked else None)
    await ProofStore(pool).record(bank, "fire_drill", False, {"incident_id": incident}, ran_by)
    await pool.execute("UPDATE platform.alert_readiness_proofs SET ran_at = $2 WHERE bank_id = $1 AND kind = 'fire_drill'", bank, started)


@db
async def test_the_fire_drill_must_have_been_run_and_acknowledged_by_a_person_in_time(pool):
    bank = _bank()
    assert (await run(pool, bank, Cfg()))["alert_fire_drill"].status == "FAIL"                        # never run
    await _drill(pool, bank, started_minutes_ago=3)
    waiting = (await run(pool, bank, Cfg()))["alert_fire_drill"]
    assert waiting.status == "WARN" and "waiting" in waiting.detail.lower()                            # within the window, nobody has acknowledged yet
    ok = _bank()
    await _drill(pool, ok, started_minutes_ago=30, acked_after_minutes=4)
    done = (await run(pool, ok, Cfg()))["alert_fire_drill"]
    assert done.status == "PASS" and "4" in done.detail and "oncall-1" in done.detail


@db
async def test_a_drill_acknowledged_too_late_or_never_acknowledged_in_time_fails(pool):
    late, missed = _bank(), _bank()
    await _drill(pool, late, started_minutes_ago=60, acked_after_minutes=40)
    assert (await run(pool, late, Cfg()))["alert_fire_drill"].status == "FAIL"
    await _drill(pool, missed, started_minutes_ago=60)
    item = (await run(pool, missed, Cfg()))["alert_fire_drill"]
    assert item.status == "FAIL" and "15" in item.detail


@db
async def test_an_old_successful_drill_is_a_warning(pool):
    bank = _bank()
    await _drill(pool, bank, started_minutes_ago=100 * 24 * 60, acked_after_minutes=3)
    assert (await run(pool, bank, Cfg()))["alert_fire_drill"].status == "WARN"


def _contacts(pool):
    return ContactStore(pool, pii_key="readiness-contacts-key", pepper="readiness-contacts-pepper")


@db
async def test_with_no_outside_address_in_use_there_is_nothing_to_verify(pool):
    assert (await run(pool, _bank(), Cfg()))["alert_contacts"].status == "PASS"


@db
async def test_every_address_alerts_use_must_be_a_verified_contact(pool):
    bank = _bank()
    cfg = Cfg(**{"alerts.email_recipients": "duty@bank.example, boss@bank.example", "alerts.whatsapp_recipients": "+919800000001"})
    bad = (await run(pool, bank, cfg))["alert_contacts"]
    assert bad.status == "FAIL" and "3" in bad.detail and "duty@bank.example" not in bad.detail and bad.action_url == "/admin/alert-contacts"
    store = _contacts(pool)
    for kind, addr in (("email", "duty@bank.example"), ("email", "boss@bank.example"), ("phone", "+919800000001")):
        contact, code = await store.add(bank, kind, addr, "", "admin-1")
        if addr != "boss@bank.example":
            await store.verify(bank, contact.contact_id, code, "admin-1")
    partly = (await run(pool, bank, cfg))["alert_contacts"]
    assert partly.status == "FAIL" and "1" in partly.detail and "boss@bank.example" not in partly.detail
    only = await store.list(bank)
    boss = next(c for c in only if c.status == "UNVERIFIED")
    code = await store.issue_code(bank, boss.contact_id)
    await store.verify(bank, boss.contact_id, code, "admin-1")
    assert (await run(pool, bank, cfg))["alert_contacts"].status == "PASS"


@db
async def test_an_outside_address_named_in_the_approved_policy_counts_too(pool):
    bank = _bank()
    store = PolicyStore(pool, pii_key="readiness-key-not-a-secret")
    policy = Policy(rules=[Rule(id="p0", severities=["P0"], hours="always", targets=[T("external", "ops@bank.example", "email"), T("role", "ops_manager", "bell")],
                                escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("role", "bank_it_admin", "email", "bell")])]),
                           Rule(id="rest", severities=[], hours="always", targets=[T("role", "ops_manager", "bell")])])
    rec = await store.propose(bank, "BANK", None, policy, proposed_by="maker")
    await store.approve(bank, rec.policy_id, approved_by="checker")
    assert (await run(pool, bank, Cfg()))["alert_contacts"].status == "FAIL"
    contact, code = await _contacts(pool).add(bank, "email", "ops@bank.example", "", "admin-1")
    await _contacts(pool).verify(bank, contact.contact_id, code, "admin-1")
    assert (await run(pool, bank, Cfg()))["alert_contacts"].status == "PASS"


@db
async def test_without_a_contact_store_the_item_is_a_warning(pool):
    assert (await run(pool, _bank(), Cfg(), contact_store=None))["alert_contacts"].status == "WARN"


@db
async def test_a_silence_still_in_force_is_a_warning_and_none_is_a_pass(pool):
    from shared.alerting.silences import SilenceStore
    bank = _bank()
    assert (await run(pool, bank, Cfg()))["alert_silences"].status == "PASS"
    now = datetime.now(timezone.utc)
    store = SilenceStore(pool, max_hours=24, allow_p0=False, min_reason_chars=5)
    await store.create(bank, "redis", ["P1"], now - timedelta(minutes=5), now + timedelta(hours=1), "Redis maintenance", "admin-1")
    await store.create(bank, "kafka", ["P2"], now + timedelta(hours=3), now + timedelta(hours=4), "Later work", "admin-1")          # not started: not counted
    item = (await run(pool, bank, Cfg()))["alert_silences"]
    assert item.status == "WARN" and "1" in item.detail and item.action_url == "/ops/silences"


import json as _json


@db
async def test_regulatory_windows_are_amber_until_entered_and_never_block(pool):
    bank = _bank()
    none = (await run(pool, bank, Cfg()))["alert_regulatory"]
    assert none.status == "WARN" and "has been entered" in none.detail
    pending = (await run(pool, bank, Cfg(**{"alerting.regulatory_windows_pending": True})))["alert_regulatory"]
    assert pending.status == "WARN" and "pending" in pending.detail.lower()
    windows = _json.dumps([{"name": "RBI cyber incident report", "authority": "RBI", "hours": 6, "reference": "Master Direction on IT Governance"}, {"name": "CERT-In report", "authority": "CERT-In", "hours": 6}])
    ok = (await run(pool, bank, Cfg(**{"alerting.regulatory_windows": windows})))["alert_regulatory"]
    assert ok.status == "PASS" and "2" in ok.detail


@db
async def test_a_window_without_a_name_or_a_positive_number_of_hours_is_incomplete(pool):
    bad = _json.dumps([{"name": "RBI report", "hours": 0}, {"authority": "CERT-In", "hours": 6}])
    item = (await run(pool, _bank(), Cfg(**{"alerting.regulatory_windows": bad})))["alert_regulatory"]
    assert item.status == "WARN" and "incomplete" in item.detail.lower() and "2" in item.detail
    broken = (await run(pool, _bank(), Cfg(**{"alerting.regulatory_windows": "not json"})))["alert_regulatory"]
    assert broken.status == "WARN"
