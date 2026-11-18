"""The escalation activities: plan (when does each step fire, how often to remind) and run one step (who is told, through the delivery engine, audited)."""
import asyncio
from datetime import datetime, timezone

from modules.cts.workflows.activities.alert_escalation_activities import (
    EscalationStepInput, PlanInput, plan_escalation, run_escalation_step,
)
from shared.alerting.audit import AlertAuditor
from shared.alerting.engine import SubmitResult, Target
from shared.alerting.routing_policy import IncidentFacts, ResolvedStep, ResolvedTarget, Routing
from shared.alerting.routing_service import RoutedIncident


class _Store:
    def __init__(self, incident=None):
        self.incident, self.levels = incident, []

    async def get(self, bank_id, incident_id):
        return self.incident

    async def set_escalation_level(self, bank_id, incident_id, level):
        self.levels.append(level)


class _Routing:
    def __init__(self, steps, repeat=None, warnings=None):
        self.routed = RoutedIncident(routing=Routing(steps=steps, repeat_minutes=repeat, warnings=warnings or []), facts=IncidentFacts(severity="P0"))

    async def route_incident(self, incident, now):
        return self.routed


class _Engine:
    def __init__(self, fail=False):
        self.submits, self.fail = [], fail

    async def submit(self, **kw):
        if self.fail:
            raise RuntimeError("engine down")
        self.submits.append(kw)
        return SubmitResult(sent=len(kw["targets"]))


class _Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def RT(kind, ref, *channels):
    return ResolvedTarget(kind=kind, ref=ref, channels=list(channels))


def _steps():
    return [ResolvedStep(level=0, after_minutes=0, targets=[RT("external", "ops@x.in", "email")]),
            ResolvedStep(level=1, after_minutes=5, targets=[RT("external", "dba@x.in", "email"), RT("user", "u-boss", "bell")]),
            ResolvedStep(level=2, after_minutes=15, targets=[RT("external", "cto@x.in", "email")])]


def _incident(state="OPEN"):
    return {"incident_id": "inc1", "severity": "P0", "component": "redis", "state": state, "opened_at": datetime.now(timezone.utc)}


def _auditor():
    events = []

    async def sink(event_type, bank_id, entity_id, actor_id, payload):
        events.append((event_type, entity_id, payload))
        return "tx"
    return AlertAuditor(sink), events


def _plan(store, routing, cfg=None):
    return asyncio.run(plan_escalation(PlanInput(bank_id="kbl", incident_id="inc1"), db_pool=object(), config_service=cfg or _Cfg(), store=store, routing=routing))


def _step(kind="ESCALATE", level=1, sequence=0, store=None, routing=None, engine=None, auditor=None):
    return asyncio.run(run_escalation_step(EscalationStepInput(bank_id="kbl", incident_id="inc1", level=level, kind=kind, sequence=sequence), db_pool=object(),
                                           config_service=_Cfg(), delivery_engine=engine, alert_auditor=auditor, store=store, routing=routing))


# ---------------- plan -----------------

def test_the_plan_lists_the_escalation_steps_after_the_first_the_repeat_interval_and_the_reminder_cap():
    plan = _plan(_Store(_incident()), _Routing(_steps(), repeat=30), _Cfg(**{"alerting.escalation_max_reminders": 7}))
    assert plan.state == "OPEN" and [(s.level, s.after_minutes) for s in plan.steps] == [(1, 5), (2, 15)] and plan.repeat_minutes == 30 and plan.max_reminders == 7


def test_the_reminder_cap_has_a_default_and_an_incident_that_is_not_open_has_no_plan():
    assert _plan(_Store(_incident()), _Routing(_steps(), repeat=30)).max_reminders > 0
    assert _plan(_Store(_incident("ACKED")), _Routing(_steps())).state == "STOPPED"
    assert _plan(_Store(_incident("RESOLVED")), _Routing(_steps())).state == "STOPPED"
    assert _plan(_Store(None), _Routing(_steps())).state == "STOPPED"


def test_a_routing_with_no_escalation_gives_an_empty_plan():
    plan = _plan(_Store(_incident()), _Routing([_steps()[0]]))
    assert plan.state == "OPEN" and plan.steps == [] and plan.repeat_minutes is None


def test_without_a_database_the_plan_says_so_instead_of_pretending():
    plan = asyncio.run(plan_escalation(PlanInput(bank_id="kbl", incident_id="inc1"), db_pool=None, config_service=_Cfg()))
    assert plan.state == "UNAVAILABLE"


# ---------------- one step -----------------

def test_an_escalation_step_notifies_that_levels_people_through_the_engine_records_the_level_and_audits_it():
    store, engine = _Store(_incident()), _Engine()
    auditor, events = _auditor()
    res = _step("ESCALATE", 1, store=store, routing=_Routing(_steps()), engine=engine, auditor=auditor)
    kw = engine.submits[0]
    assert sorted((t.channel, t.recipient) for t in kw["targets"]) == [("bell", "u-boss"), ("email", "dba@x.in")]
    assert kw["occasion"] == "esc1" and kw["incident_id"] == "inc1" and kw["level"] == 1 and kw["priority"] == "P0"
    assert res.stopped is False and res.notified == 2 and store.levels == [1]
    assert events[-1][0] == "ALERT_ESCALATED" and events[-1][2]["level"] == 1 and "dba@x.in" not in str(events)


def test_a_reminder_goes_to_everyone_from_the_first_step_up_to_the_current_one_with_its_own_occasion():
    engine = _Engine()
    _step("REMIND", 2, sequence=3, store=_Store(_incident()), routing=_Routing(_steps()), engine=engine, auditor=None)
    kw = engine.submits[0]
    assert sorted((t.channel, t.recipient) for t in kw["targets"]) == [("bell", "u-boss"), ("email", "cto@x.in"), ("email", "dba@x.in"), ("email", "ops@x.in")]
    assert kw["occasion"] == "rem3"


def test_an_incident_that_is_no_longer_open_stops_everything_and_sends_nothing():
    engine, store = _Engine(), _Store(_incident("ACKED"))
    res = _step("ESCALATE", 1, store=store, routing=_Routing(_steps()), engine=engine)
    assert res.stopped is True and engine.submits == [] and store.levels == []


def test_a_step_nobody_can_be_found_for_is_recorded_not_sent_and_does_not_stop_escalation():
    auditor, events = _auditor()
    steps = [_steps()[0], ResolvedStep(level=1, after_minutes=5, targets=[])]
    engine = _Engine()
    res = _step("ESCALATE", 1, store=_Store(_incident()), routing=_Routing(steps, warnings=["oncall_unfilled:ops"]), engine=engine, auditor=auditor)
    assert res.stopped is False and res.notified == 0 and engine.submits == []
    assert events[-1][0] == "ALERT_ESCALATED" and events[-1][2]["notified"] == 0 and "oncall_unfilled:ops" in events[-1][2]["warnings"]


def test_an_engine_failure_is_reported_as_degraded_never_raised():
    res = _step("ESCALATE", 1, store=_Store(_incident()), routing=_Routing(_steps()), engine=_Engine(fail=True))
    assert res.degraded is True and res.stopped is False


def test_without_an_engine_the_step_degrades():
    assert _step("ESCALATE", 1, store=_Store(_incident()), routing=_Routing(_steps()), engine=None).degraded is True
