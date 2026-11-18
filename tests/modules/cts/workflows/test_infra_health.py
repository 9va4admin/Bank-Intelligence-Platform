"""Infrastructure health in the platform health workflow: probe every dependency each tick, turn state changes into emails to the configured recipients,
never repeat the same condition every minute, expose the component states to the dashboard, and survive indefinitely (continue-as-new).
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from modules.cts.health.state_machine import ComponentState, Event, Probe
from modules.cts.workflows.activities.platform_health_activities import (
    CheckHRInput, CheckIETInput, CheckScannerFleetInput, CheckVaultCoverageInput, DispatchAlertInput, DispatchAlertResult,
    HRCheckResult, IETCheckResult, ProbeComponentsInput, ProbeComponentsResult, ScannerFleetCheckResult, StuckWorkflowSweepInput,
    StuckWorkflowSweepResult, VaultCoverageCheckResult, dispatch_platform_alert, probe_components, IncidentRecordResult, ProcessOutboxInput, ProcessOutboxResult, RunRetentionInput, RunRetentionResult,
)
from modules.cts.workflows.activities.alert_escalation_activities import EscalationPlan, EscalationStepResult, PlanStep
from modules.cts.workflows.alert_escalation_workflow import AlertEscalationWorkflow
from modules.cts.workflows.platform_health_check_workflow import PlatformHealthCheckWorkflow, PlatformHealthInput, alerts_for_events
from shared.messages import get_message
from shared.temporal.converter import pydantic_data_converter

# The first get_message() call loads the whole registry (~6 s). Inside a workflow step that trips the SDK's deadlock detector, so a test run in
# isolation (cold registry) hung. The worker warms the registry at start-up (see _start_platform_health); tests warm it here.
get_message("CTS_IET_BREACH_RISK_CHEQUES_WITHIN", near_breach_count=0)


# ---------------- dispatch: recipients come from configuration -----------------

class _Cfg:
    def __init__(self, l3=None):
        self.l3 = l3 or {}

    async def get(self, key):
        if key not in self.l3:
            from shared.config.config_service import ConfigKeyNotFoundError
            raise ConfigKeyNotFoundError(key)
        return self.l3[key]


def _alert(**kw):
    base = dict(bank_id="kbl", event_type="COMPONENT_DOWN", severity="CRITICAL", priority="P0", message="yugabyte is not responding", component="yugabyte")
    base.update(kw)
    return DispatchAlertInput(**base)


@pytest.mark.asyncio
async def test_one_mail_per_configured_recipient_json_or_comma_separated():
    for raw in (json.dumps(["a@bank.example", "b@bank.example"]), "a@bank.example, b@bank.example"):
        sent = []
        d = AsyncMock()
        d.send = AsyncMock(side_effect=lambda r: sent.append(r) or {"status": "sent"})
        res = await dispatch_platform_alert(_alert(), dispatcher=d, config_service=_Cfg({"alerts.email_recipients": raw}))
        assert res.sent is True and [r.recipient for r in sent] == ["a@bank.example", "b@bank.example"]
        assert sent[0].template_id == "PLATFORM_HEALTH_ALERT" and sent[0].context["component"] == "yugabyte" and sent[0].priority == "P0"


@pytest.mark.asyncio
async def test_no_recipients_configured_sends_nothing_and_says_so():
    d = AsyncMock()
    res = await dispatch_platform_alert(_alert(), dispatcher=d, config_service=_Cfg({"alerts.email_recipients": ""}))
    assert res.sent is False and res.degraded is True and d.send.await_count == 0


@pytest.mark.asyncio
async def test_one_failing_recipient_does_not_stop_the_others():
    calls = []

    async def send(r):
        calls.append(r.recipient)
        if r.recipient == "bad@bank.example":
            raise RuntimeError("550 rejected")
        return {"status": "sent"}
    d = AsyncMock()
    d.send = send
    res = await dispatch_platform_alert(_alert(), dispatcher=d, config_service=_Cfg({"alerts.email_recipients": "bad@bank.example, ok@bank.example"}))
    assert calls == ["bad@bank.example", "ok@bank.example"] and res.sent is True


@pytest.mark.asyncio
async def test_a_recovery_uses_the_recovery_template_with_the_down_time():
    sent = []
    d = AsyncMock()
    d.send = AsyncMock(side_effect=lambda r: sent.append(r) or {"status": "sent"})
    await dispatch_platform_alert(_alert(event_type="COMPONENT_RECOVERED", severity="INFO", priority="P3", template="PLATFORM_HEALTH_RECOVERED",
                                         down_for="4m", message="back"), dispatcher=d, config_service=_Cfg({"alerts.email_recipients": "a@bank.example"}))
    assert sent[0].template_id == "PLATFORM_HEALTH_RECOVERED" and sent[0].context["down_for"] == "4m"


# ---------------- events -> alerts -----------------

def test_events_become_alerts_with_the_right_template_priority_and_text():
    events = [Event(kind="DOWN", component="redis", severity="P0", message="redis is not responding"),
              Event(kind="RECOVERED", component="redis", severity="P3", message="redis is responding again", down_for_seconds=240.0)]
    down, rec = alerts_for_events("kbl", events)
    assert (down.template, down.priority, down.severity, down.component) == ("PLATFORM_HEALTH_ALERT", "P0", "CRITICAL", "redis")
    assert (rec.template, rec.priority, rec.down_for) == ("PLATFORM_HEALTH_RECOVERED", "P3", "4m")


# ---------------- the probe activity -----------------

@pytest.mark.asyncio
async def test_probe_activity_runs_every_target_applies_the_state_machine_and_returns_events():
    from modules.cts.health.probes import ProbeSpec
    specs = [ProbeSpec(component="redis", kind="redis", target="r"), ProbeSpec(component="kafka", kind="tcp", target="k:1")]

    async def fake_run(spec):
        return Probe(component=spec.component, ok=spec.component != "redis", latency_ms=5.0 if spec.component != "redis" else None,
                     error=None if spec.component != "redis" else "refused", critical=True)
    cfg = _Cfg({"platform_health.down_after_failures": 2})
    with patch("modules.cts.workflows.activities.platform_health_activities.build_specs", AsyncMock(return_value=specs)), \
         patch("modules.cts.workflows.activities.platform_health_activities.run_probe", fake_run):
        first = await probe_components(ProbeComponentsInput(bank_id="kbl"), config_service=cfg)
        second = await probe_components(ProbeComponentsInput(bank_id="kbl", states=first.states), config_service=cfg)
    assert first.events == [] and first.probes_run == 2
    assert second.states["redis"].status == "DOWN" and [e.kind for e in second.events] == ["DOWN"]      # down_after_failures=2 came from config
    assert second.states["kafka"].status == "OK"


@pytest.mark.asyncio
async def test_a_component_no_longer_configured_is_dropped_from_the_state():
    from modules.cts.health.probes import ProbeSpec
    gone = {"old_service": ComponentState(status="DOWN", since=1.0)}
    with patch("modules.cts.workflows.activities.platform_health_activities.build_specs", AsyncMock(return_value=[ProbeSpec(component="redis", kind="redis", target="r")])), \
         patch("modules.cts.workflows.activities.platform_health_activities.run_probe", AsyncMock(return_value=Probe(component="redis", ok=True, latency_ms=1.0))):
        res = await probe_components(ProbeComponentsInput(bank_id="kbl", states=gone), config_service=_Cfg())
    assert set(res.states) == {"redis"}


@pytest.mark.asyncio
async def test_without_a_config_service_the_probe_degrades_instead_of_crashing():
    res = await probe_components(ProbeComponentsInput(bank_id="kbl"), config_service=None)
    assert res.degraded is True and res.states == {} and res.events == []


# ---------------- the real workflow loop -----------------

DISPATCHED: list[DispatchAlertInput] = []
PROBE_CALLS = {"n": 0}


@activity.defn(name="check_iet_risk_for_alert")
async def _iet(inp: CheckIETInput) -> IETCheckResult:
    return IETCheckResult(bank_id=inp.bank_id, near_breach_count=2, needs_alert=True)        # the condition persists every tick


@activity.defn(name="check_human_review_for_alert")
async def _hr(inp: CheckHRInput) -> HRCheckResult:
    return HRCheckResult(bank_id=inp.bank_id)


@activity.defn(name="check_vault_redis_coverage_for_alert")
async def _vault(inp: CheckVaultCoverageInput) -> VaultCoverageCheckResult:
    return VaultCoverageCheckResult(bank_id=inp.bank_id)


@activity.defn(name="check_scanner_fleet_for_alert")
async def _fleet(inp: CheckScannerFleetInput) -> ScannerFleetCheckResult:
    return ScannerFleetCheckResult(bank_id=inp.bank_id)


@activity.defn(name="sweep_stuck_workflows")
async def _sweep(inp: StuckWorkflowSweepInput) -> StuckWorkflowSweepResult:
    return StuckWorkflowSweepResult(bank_id=inp.bank_id)


@activity.defn(name="dispatch_platform_alert")
async def _dispatch(inp: DispatchAlertInput) -> DispatchAlertResult:
    DISPATCHED.append(inp)
    return DispatchAlertResult(sent=True)


ESCALATION_STEPS: list = []
RECOVER = {"on": False}          # a test can ask the fake monitor to see yugabyte recover on its third tick


@activity.defn(name="plan_escalation")
async def _plan_esc(inp) -> EscalationPlan:
    return EscalationPlan(state="OPEN", steps=[PlanStep(level=1, after_minutes=60)])        # far in the future: the escalation is waiting when the incident resolves


@activity.defn(name="run_escalation_step")
async def _run_esc(inp) -> EscalationStepResult:
    ESCALATION_STEPS.append((inp.incident_id, inp.level))
    return EscalationStepResult()


RECORDED: list[DispatchAlertInput] = []
RETENTION_RUNS = {"n": 0}


@activity.defn(name="run_alert_retention")
async def _retention(inp: RunRetentionInput) -> RunRetentionResult:
    RETENTION_RUNS["n"] += 1
    return RunRetentionResult()


OUTBOX_RUNS = {"n": 0}


@activity.defn(name="process_alert_outbox")
async def _outbox(inp: ProcessOutboxInput) -> ProcessOutboxResult:
    OUTBOX_RUNS["n"] += 1
    return ProcessOutboxResult()


@activity.defn(name="record_alert_incident")
async def _record(inp: DispatchAlertInput) -> IncidentRecordResult:
    from shared.alerting.incidents import dedup_key_for
    from shared.alerting.incidents import is_resolution
    RECORDED.append(inp)
    resolved = is_resolution(inp.event_type)
    return IncidentRecordResult(incident_id=f"inc:{dedup_key_for(inp.event_type, inp.component)}", created=not resolved, resolved=resolved)


@activity.defn(name="probe_components")
async def _probe(inp: ProbeComponentsInput) -> ProbeComponentsResult:
    PROBE_CALLS["n"] += 1
    states = dict(inp.states)
    if PROBE_CALLS["n"] == 1:
        states["yugabyte"] = ComponentState(status="DOWN", since=1.0, consecutive_failures=3, last_error="refused")
        return ProbeComponentsResult(states=states, events=[Event(kind="DOWN", component="yugabyte", severity="P0", message="yugabyte is not responding")], probes_run=1)
    if RECOVER["on"] and PROBE_CALLS["n"] == 3:
        states["yugabyte"] = ComponentState(status="OK", since=1.0)
        return ProbeComponentsResult(states=states, events=[Event(kind="RECOVERED", component="yugabyte", severity="P3", message="yugabyte is responding again", down_for_seconds=120.0)], probes_run=1)
    return ProbeComponentsResult(states=states, events=[], probes_run=1)


_ACTIVITIES = [_iet, _hr, _vault, _fleet, _sweep, _dispatch, _probe, _record, _outbox, _retention, _plan_esc, _run_esc]


@pytest_asyncio.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as e:
        yield e


async def _start(env, inp):
    DISPATCHED.clear()
    RECORDED.clear()
    OUTBOX_RUNS["n"] = 0
    RETENTION_RUNS["n"] = 0
    ESCALATION_STEPS.clear()
    RECOVER["on"] = False
    PROBE_CALLS["n"] = 0
    tq = f"tq-infra-{uuid.uuid4().hex[:8]}"
    worker = Worker(env.client, task_queue=tq, workflows=[PlatformHealthCheckWorkflow, AlertEscalationWorkflow], activities=_ACTIVITIES,
                    workflow_runner=UnsandboxedWorkflowRunner())
    return tq, worker


@pytest.mark.asyncio
async def test_a_component_going_down_sends_one_alert_with_its_name_and_a_persisting_condition_is_not_repeated_every_minute(env):
    inp = PlatformHealthInput(bank_id="kbl", repeat_alert_seconds=1800, iet_repeat_seconds=300)
    tq, worker = await _start(env, inp)
    async with worker:
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=f"h-{uuid.uuid4().hex[:6]}", task_queue=tq)
        await env.sleep(200)                       # ~3-4 ticks
        first_window = [(d.event_type, d.component) for d in DISPATCHED]
        await env.sleep(400)                       # past the 300 s IET repeat interval
        later = [d.event_type for d in DISPATCHED]
        await h.cancel()
    assert first_window.count(("COMPONENT_DOWN", "yugabyte")) == 1
    assert [e for e, _ in first_window].count("IET_BREACH_RISK") == 1          # the same IET condition on every tick: sent once, not four times
    assert later.count("IET_BREACH_RISK") >= 2 and later.count("COMPONENT_DOWN") == 1      # repeated only after the interval


@pytest.mark.asyncio
async def test_every_alert_is_recorded_as_an_incident_first_and_dispatched_with_that_incident_id(env):
    inp = PlatformHealthInput(bank_id="kbl", repeat_alert_seconds=1800, iet_repeat_seconds=300)
    tq, worker = await _start(env, inp)
    async with worker:
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=f"h-{uuid.uuid4().hex[:6]}", task_queue=tq)
        await env.sleep(200)
        await h.cancel()
    assert DISPATCHED, "nothing was dispatched"
    for d in DISPATCHED:
        assert d.incident_id == f"inc:{__import__('shared.alerting.incidents', fromlist=['x']).dedup_key_for(d.event_type, d.component)}"
    assert {r.event_type for r in RECORDED} >= {"COMPONENT_DOWN", "IET_BREACH_RISK"}


@pytest.mark.asyncio
async def test_the_outbox_is_worked_every_tick_and_each_tick_is_its_own_occasion(env):
    inp = PlatformHealthInput(bank_id="kbl", repeat_alert_seconds=1800, iet_repeat_seconds=60)
    tq, worker = await _start(env, inp)
    async with worker:
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=f"h-{uuid.uuid4().hex[:6]}", task_queue=tq)
        await env.sleep(400)
        await h.cancel()
    assert OUTBOX_RUNS["n"] >= 3
    iet = [d for d in DISPATCHED if d.event_type == "IET_BREACH_RISK"]
    assert len(iet) >= 2 and all(d.occasion for d in iet) and len({d.occasion for d in iet}) == len(iet)     # a reminder is a new occasion; none repeats


@pytest.mark.asyncio
async def test_old_history_is_pruned_on_the_first_tick_and_then_only_at_the_configured_interval(env):
    inp = PlatformHealthInput(bank_id="kbl", prune_every_ticks=4)
    tq, worker = await _start(env, inp)
    async with worker:
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=f"h-{uuid.uuid4().hex[:6]}", task_queue=tq)
        await env.sleep(560)                       # about 9 ticks: pruned on ticks 1, 5 and 9
        await h.cancel()
    assert 2 <= RETENTION_RUNS["n"] <= 3 and OUTBOX_RUNS["n"] > RETENTION_RUNS["n"]


@pytest.mark.asyncio
async def test_a_restart_request_makes_the_monitor_roll_over_at_the_next_tick_and_keep_what_it_knew(env):
    """After an upgrade a monitor that was already running keeps its old code path until it restarts; the worker asks it to restart at once."""
    inp = PlatformHealthInput(bank_id="kbl", max_ticks_before_restart=1000)
    tq, worker = await _start(env, inp)
    async with worker:
        wid = f"h-{uuid.uuid4().hex[:6]}"
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=wid, task_queue=tq)
        first_run = h.result_run_id
        await env.sleep(100)
        await h.signal(PlatformHealthCheckWorkflow.request_restart)
        await env.sleep(150)
        latest = env.client.get_workflow_handle(wid)
        desc = await latest.describe()
        snap = await latest.query(PlatformHealthCheckWorkflow.component_states)
        await latest.cancel()
    assert desc.run_id != first_run
    assert snap["states"]["yugabyte"]["status"] == "DOWN"                       # state carried across the rollover
    assert [d.event_type for d in DISPATCHED].count("COMPONENT_DOWN") == 1       # and the outage was not announced a second time


@pytest.mark.asyncio
async def test_a_new_incident_gets_an_escalation_workflow_and_its_resolution_stops_it(env):
    inp = PlatformHealthInput(bank_id="kbl", repeat_alert_seconds=1800, iet_repeat_seconds=100000)
    tq, worker = await _start(env, inp)
    RECOVER["on"] = True
    async with worker:
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=f"h-{uuid.uuid4().hex[:6]}", task_queue=tq)
        await env.sleep(30)                                                   # the first tick: yugabyte goes down, an incident opens
        child = env.client.get_workflow_handle("cts-alert-kbl-inc:component:yugabyte:down")
        assert (await child.describe()).status is not None                    # it exists, and is waiting for its first step
        await env.sleep(240)                                                  # the third tick: yugabyte recovers, the incident resolves
        assert await child.result() == "STOPPED:resolved"
        await h.cancel()
    assert ESCALATION_STEPS == []                                             # it never escalated: it was resolved first


@pytest.mark.asyncio
async def test_the_dashboard_can_ask_the_workflow_for_component_states(env):
    inp = PlatformHealthInput(bank_id="kbl")
    tq, worker = await _start(env, inp)
    async with worker:
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=f"h-{uuid.uuid4().hex[:6]}", task_queue=tq)
        await env.sleep(100)
        snap = await h.query(PlatformHealthCheckWorkflow.component_states)
        await h.cancel()
    assert snap["states"]["yugabyte"]["status"] == "DOWN" and snap["tick"] >= 1 and snap["last_tick_at"] is not None


@pytest.mark.asyncio
async def test_the_loop_continues_as_new_and_carries_its_state_forward(env):
    inp = PlatformHealthInput(bank_id="kbl", max_ticks_before_restart=3)
    tq, worker = await _start(env, inp)
    async with worker:
        wid = f"h-{uuid.uuid4().hex[:6]}"
        h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=wid, task_queue=tq)
        first_run = h.result_run_id
        await env.sleep(400)                      # several restarts of 3 ticks each
        latest = env.client.get_workflow_handle(wid)
        desc = await latest.describe()
        snap = await latest.query(PlatformHealthCheckWorkflow.component_states)
        await latest.cancel()
    assert desc.run_id != first_run                                     # it restarted
    assert snap["states"]["yugabyte"]["status"] == "DOWN"               # and kept what it knew
    assert [d.event_type for d in DISPATCHED].count("COMPONENT_DOWN") == 1      # without re-announcing the outage after the restart


# ---------------- found on the first live run -----------------

def test_every_activity_the_monitor_runs_is_registered_on_the_worker():
    """check_scanner_fleet_for_alert was called by the workflow but never registered on the worker: that step retried forever and the whole
    monitor stopped ticking. Mocked tests cannot see a missing registration."""
    import ast
    import inspect
    import modules.cts.worker as worker
    from modules.cts.workflows import platform_health_check_workflow as wf

    called = set()
    for node in ast.walk(ast.parse(inspect.getsource(wf))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute_activity" and node.args:
            if isinstance(node.args[0], ast.Name):
                called.add(node.args[0].id)
    registered = {getattr(fn, "__name__", "") for fn in worker.NO_DI_ACTIVITIES}
    assert called, "found no execute_activity calls: the test needs updating"
    assert called <= registered, f"called by the health workflow but not registered on the worker: {sorted(called - registered)}"


FAIL_FLEET = {"on": False}


@activity.defn(name="check_scanner_fleet_for_alert")
async def _fleet_maybe_failing(inp: CheckScannerFleetInput) -> ScannerFleetCheckResult:
    if FAIL_FLEET["on"]:
        raise RuntimeError("scanner table missing")
    return ScannerFleetCheckResult(bank_id=inp.bank_id)


@pytest.mark.asyncio
async def test_one_failing_check_does_not_stop_the_monitor(env):
    DISPATCHED.clear()
    PROBE_CALLS["n"] = 0
    FAIL_FLEET["on"] = True
    inp = PlatformHealthInput(bank_id="kbl")
    tq = f"tq-infra-{uuid.uuid4().hex[:8]}"
    acts = [_iet, _hr, _vault, _fleet_maybe_failing, _sweep, _dispatch, _probe]
    try:
        async with Worker(env.client, task_queue=tq, workflows=[PlatformHealthCheckWorkflow], activities=acts, workflow_runner=UnsandboxedWorkflowRunner()):
            h = await env.client.start_workflow(PlatformHealthCheckWorkflow.run, inp, id=f"h-{uuid.uuid4().hex[:6]}", task_queue=tq)
            await env.sleep(400)
            ticks = PROBE_CALLS["n"]
            await h.cancel()
    finally:
        FAIL_FLEET["on"] = False
    assert ticks >= 4          # it kept ticking (infrastructure probes keep running) although a later step failed every time
