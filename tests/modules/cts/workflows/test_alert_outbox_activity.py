"""dispatch_platform_alert through the delivery engine, and the activity that retries what is due."""
import asyncio

from modules.cts.workflows.activities.platform_health_activities import (
    DispatchAlertInput, ProcessOutboxInput, dispatch_platform_alert, process_alert_outbox,
)
from shared.alerting.engine import ProcessResult, SubmitResult, Target


class _Engine:
    def __init__(self, result=None):
        self.submits, self.processed, self.result = [], [], result or SubmitResult(sent=2)

    async def submit(self, **kw):
        self.submits.append(kw)
        return self.result

    async def process_due(self, bank_id, *, resolve_targets):
        self.processed.append((bank_id, [await resolve_targets("email"), await resolve_targets("whatsapp")]))
        return ProcessResult(attempted=3, sent=2, retrying=1)


class _Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def _cfg(**extra):
    return _Cfg(**{"alerts.email_recipients": "ops@x.in, dba@x.in", "alerts.whatsapp_recipients": "+919800000001", **extra})


def _alert(**kw):
    base = dict(bank_id="kbl", event_type="COMPONENT_DOWN", component="redis", message="m", severity="CRITICAL", priority="P0",
                incident_id="inc-9", occasion="t5")
    base.update(kw)
    return DispatchAlertInput(**base)


def _run(alert, engine, cfg=None):
    return asyncio.run(dispatch_platform_alert(alert, dispatcher=object(), config_service=cfg or _cfg(), delivery_engine=engine))


def test_a_p0_alert_is_submitted_to_every_email_and_phone_with_the_incident_and_occasion():
    engine = _Engine()
    res = _run(_alert(), engine)
    kw = engine.submits[0]
    assert kw["incident_id"] == "inc-9" and kw["occasion"] == "t5" and kw["priority"] == "P0" and kw["component"] == "redis"
    assert sorted((t.channel, t.recipient) for t in kw["targets"]) == [("email", "dba@x.in"), ("email", "ops@x.in"), ("whatsapp", "+919800000001")]
    assert kw["template_id"] == "PLATFORM_HEALTH_ALERT" and kw["context"]["message"] == "m" and kw["context"]["component"] == "redis"
    assert res.sent is True


def test_the_context_carries_what_the_email_template_needs():
    engine = _Engine()
    _run(_alert(occurred_at=1234.0), engine)
    ctx = engine.submits[0]["context"]
    assert ctx["incident_id"] == "inc-9" and ctx["occurred_at"] == 1234.0 and ctx["priority"] == "P0"


def test_below_the_whatsapp_floor_only_email_targets_are_submitted_but_a_fallback_may_still_reach_the_phones():
    engine = _Engine()
    _run(_alert(priority="P1"), engine)
    kw = engine.submits[0]
    assert {t.channel for t in kw["targets"]} == {"email"}
    phones = asyncio.run(kw["resolve_targets"]("whatsapp"))
    assert phones == [Target("whatsapp", "+919800000001")]               # a delivery failure is itself worth a phone, whatever the floor says
    assert asyncio.run(kw["resolve_targets"]("fax")) == []


def test_the_result_says_not_sent_when_everything_is_queued_for_retry():
    res = _run(_alert(), _Engine(SubmitResult(sent=0, retrying=3)))
    assert res.sent is False and res.queued_for_retry == 3 and not res.degraded


def test_no_recipients_is_degraded_and_submits_nothing():
    engine = _Engine()
    res = _run(_alert(), engine, _Cfg())
    assert res.degraded and not res.sent and engine.submits == []


def test_without_an_engine_the_direct_path_still_sends():
    class D:
        def __init__(self):
            self.sent = []

        async def send(self, r):
            self.sent.append(r.channel)
    d = D()
    res = asyncio.run(dispatch_platform_alert(_alert(), dispatcher=d, config_service=_cfg(), delivery_engine=None))
    assert res.sent and sorted(d.sent) == ["email", "email", "whatsapp"]


def test_the_outbox_activity_retries_what_is_due_using_the_configured_recipients():
    engine = _Engine()
    res = asyncio.run(process_alert_outbox(ProcessOutboxInput(bank_id="kbl"), delivery_engine=engine, config_service=_cfg()))
    assert (res.attempted, res.sent, res.retrying) == (3, 2, 1)
    assert engine.processed[0][0] == "kbl"
    assert [t.recipient for t in engine.processed[0][1][0]] == ["ops@x.in", "dba@x.in"]


def test_the_outbox_activity_degrades_without_an_engine():
    res = asyncio.run(process_alert_outbox(ProcessOutboxInput(bank_id="kbl"), delivery_engine=None, config_service=_cfg()))
    assert res.degraded and res.attempted == 0


# ---------------- the bell -----------------

class _Pool:
    """Stands in for the database: answers the bell-recipient lookup."""
    def __init__(self, users=("u-a", "u-b")):
        self.users, self.asked = list(users), []

    async def fetch(self, sql, bank, roles, limit, days=0):
        self.asked.append((bank, roles, limit))
        return [{"user_id": u} for u in self.users][:limit]


def _run_bell(alert, engine, cfg, pool):
    return asyncio.run(dispatch_platform_alert(alert, dispatcher=object(), config_service=cfg, delivery_engine=engine, db_pool=pool))


def test_every_alert_also_goes_to_the_bell_of_the_configured_roles():
    engine, pool = _Engine(), _Pool()
    _run_bell(_alert(priority="P1"), engine, _cfg(**{"alerting.bell_roles": '["ops_manager"]'}), pool)
    targets = {(t.channel, t.recipient) for t in engine.submits[0]["targets"]}
    assert {("bell", "u-a"), ("bell", "u-b")} <= targets and ("email", "ops@x.in") in targets
    assert pool.asked[0][1] == ["ops_manager"]


def test_the_bell_roles_and_recipient_limit_come_from_configuration_with_defaults():
    engine, pool = _Engine(), _Pool(users=["a", "b", "c"])
    _run_bell(_alert(), engine, _cfg(**{"alerting.bell_max_recipients": 2}), pool)
    assert pool.asked[0][1] == ["ops_manager", "bank_it_admin"] and pool.asked[0][2] == 2
    assert len([t for t in engine.submits[0]["targets"] if t.channel == "bell"]) == 2


def test_the_bell_has_its_own_priority_floor():
    engine, pool = _Engine(), _Pool()
    _run_bell(_alert(priority="P3"), engine, _cfg(**{"alerting.bell_min_priority": "P1"}), pool)
    assert not [t for t in engine.submits[0]["targets"] if t.channel == "bell"] and pool.asked == []


def test_the_bell_works_even_when_nobody_has_email_or_whatsapp_configured():
    engine, pool = _Engine(), _Pool()
    res = asyncio.run(dispatch_platform_alert(_alert(), dispatcher=object(), config_service=_Cfg(), delivery_engine=engine, db_pool=pool))
    assert not res.degraded and [t.channel for t in engine.submits[0]["targets"]] == ["bell", "bell"]


def test_a_failing_lookup_never_stops_the_alert():
    class Broken:
        async def fetch(self, *a):
            raise ConnectionError("db down")
    engine = _Engine()
    res = _run_bell(_alert(), engine, _cfg(), Broken())
    assert res.sent and {t.channel for t in engine.submits[0]["targets"]} == {"email", "whatsapp"}


def test_a_fallback_can_reach_the_bell():
    engine, pool = _Engine(), _Pool()
    _run_bell(_alert(), engine, _cfg(), pool)
    bell = asyncio.run(engine.submits[0]["resolve_targets"]("bell"))
    assert [(t.channel, t.recipient) for t in bell] == [("bell", "u-a"), ("bell", "u-b")]
