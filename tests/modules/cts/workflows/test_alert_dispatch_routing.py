"""The first notification of an alert uses the routing (people, roles, on-call, schedules) when it can, and the original flat settings when it cannot.
The routing service is faked here; its real behaviour is tested against the database in tests/shared/alerting/test_routing_service_real.py."""
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput, dispatch_platform_alert
from shared.alerting.engine import SubmitResult
from shared.alerting.routing_policy import IncidentFacts, ResolvedStep, ResolvedTarget, Routing
from shared.alerting.routing_service import RoutedIncident


class _Engine:
    def __init__(self):
        self.submits = []

    async def submit(self, **kw):
        self.submits.append(kw)
        return SubmitResult(sent=len(kw["targets"]))


class _Routing:
    def __init__(self, routing=None, fail=False):
        self.routing, self.fail, self.asked = routing, fail, []

    async def route_facts(self, facts, now):
        self.asked.append(facts)
        if self.fail:
            raise ConnectionError("db down")
        return RoutedIncident(routing=self.routing, facts=facts)


class _Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


class _Pool:
    async def fetch(self, *a, **k):
        return []


def RT(kind, ref, *channels):
    return ResolvedTarget(kind=kind, ref=ref, channels=list(channels))


def _routing(*targets, held=False, warnings=None, hold_until=None):
    return Routing(steps=[ResolvedStep(level=0, after_minutes=0, targets=list(targets))] if targets else [], held=held, warnings=warnings or [])


def _alert(**kw):
    base = dict(bank_id="kbl", event_type="COMPONENT_DOWN", component="redis", message="m", severity="CRITICAL", priority="P0", incident_id="inc-9", occasion="t5")
    base.update(kw)
    return DispatchAlertInput(**base)


WED_10PM_IST = datetime(2026, 11, 18, 22, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()


def _legacy_cfg():
    return _Cfg(**{"alerts.email_recipients": "legacy@x.in"})


def _run(alert, engine, routing, cfg=None):
    return asyncio.run(dispatch_platform_alert(alert, dispatcher=object(), config_service=cfg or _legacy_cfg(), delivery_engine=engine, db_pool=_Pool(), routing_service=routing))


def _sent(engine):
    return sorted((t.channel, t.recipient) for t in engine.submits[0]["targets"])


def test_the_routing_decides_who_is_told_not_the_flat_lists():
    engine = _Engine()
    res = _run(_alert(), engine, _Routing(_routing(RT("external", "boss@x.in", "email"), RT("user", "u-oncall", "bell"))))
    assert _sent(engine) == [("bell", "u-oncall"), ("email", "boss@x.in")] and res.routed is True and res.sent is True


def test_the_routing_is_asked_about_this_alert_s_severity_and_component():
    routing = _Routing(_routing(RT("external", "a@x.in", "email")))
    _run(_alert(priority="P1", component="kafka"), _Engine(), routing)
    assert routing.asked[0].severity == "P1" and routing.asked[0].component == "kafka"


def test_only_the_first_step_is_sent_now_the_rest_belong_to_escalation():
    routing = Routing(steps=[ResolvedStep(level=0, after_minutes=0, targets=[RT("external", "a@x.in", "email")]),
                             ResolvedStep(level=1, after_minutes=10, targets=[RT("external", "later@x.in", "email")])])
    engine = _Engine()
    _run(_alert(), engine, _Routing(routing))
    assert _sent(engine) == [("email", "a@x.in")]


def test_when_no_rule_matches_the_original_flat_settings_are_used():
    engine = _Engine()
    res = _run(_alert(), engine, _Routing(Routing(steps=[], warnings=["no_rule_matched"], matched=[])))
    assert _sent(engine) == [("email", "legacy@x.in")] and res.routed is False


def test_when_the_routing_cannot_be_read_the_original_settings_are_used():
    engine = _Engine()
    res = _run(_alert(), engine, _Routing(fail=True))
    assert _sent(engine) == [("email", "legacy@x.in")] and res.routed is False


def test_when_the_routing_names_nobody_deliverable_the_original_settings_are_the_safety_net():
    engine = _Engine()
    res = _run(_alert(), engine, _Routing(_routing(RT("group", "everyone", "email"))))               # groups are not deliverable yet
    assert _sent(engine) == [("email", "legacy@x.in")] and res.routed is False


def test_without_a_routing_service_nothing_changes():
    engine = _Engine()
    res = _run(_alert(), engine, None)
    assert _sent(engine) == [("email", "legacy@x.in")] and res.routed is False


def test_a_low_priority_alert_held_for_working_hours_is_queued_for_later_not_sent_now():
    engine = _Engine()
    cfg = _Cfg(**{"alerts.email_recipients": "legacy@x.in", "alerting.timezone": "Asia/Kolkata"})
    _run(_alert(priority="P2", occurred_at=WED_10PM_IST), engine, _Routing(_routing(RT("external", "a@x.in", "email"), held=True)), cfg)
    assert 9 * 3600 < engine.submits[0]["delay_seconds"] < 48 * 3600          # until the next working morning


def test_an_alert_that_is_not_held_is_sent_with_no_delay():
    engine = _Engine()
    _run(_alert(), engine, _Routing(_routing(RT("external", "a@x.in", "email"))))
    assert engine.submits[0].get("delay_seconds", 0) == 0


def test_a_held_alert_with_no_working_hours_ahead_is_sent_now_rather_than_lost():
    engine = _Engine()
    cfg = _Cfg(**{"alerting.business_hours": '{"days": [], "start": "09:00", "end": "17:00"}'})
    _run(_alert(priority="P2", occurred_at=WED_10PM_IST), engine, _Routing(_routing(RT("external", "a@x.in", "email"), held=True)), cfg)
    assert engine.submits[0].get("delay_seconds", 0) == 0
