"""AlertEscalationWorkflow: one per open incident. It waits for each escalation step's time (counted from when the incident opened), escalates, stops the moment the
incident is acknowledged or resolved (a signal, or the database says so), and re-notifies on the policy's interval up to a configured number of times.
Run with Temporal's time-skipping server and scripted activities, so minutes cost nothing."""
import time
import uuid

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from modules.cts.workflows.activities.alert_escalation_activities import (
    EscalationPlan, EscalationStepInput, EscalationStepResult, PlanInput, PlanStep,
)
from modules.cts.workflows.alert_escalation_workflow import AlertEscalationInput, AlertEscalationWorkflow
from shared.temporal.converter import pydantic_data_converter

STATE = {"plan": None, "calls": [], "stop_at": None, "fail_levels": set(), "plan_failures": 0}


@activity.defn(name="plan_escalation")
async def _plan(inp: PlanInput) -> EscalationPlan:
    if STATE["plan_failures"] > 0:
        STATE["plan_failures"] -= 1
        raise ApplicationError("db down", non_retryable=True)
    return STATE["plan"]


@activity.defn(name="run_escalation_step")
async def _step(inp: EscalationStepInput) -> EscalationStepResult:
    STATE["calls"].append((inp.kind, inp.level, inp.sequence))
    if inp.level in STATE["fail_levels"] and inp.kind == "ESCALATE":
        raise ApplicationError("boom", non_retryable=True)
    stopped = STATE["stop_at"] is not None and len(STATE["calls"]) >= STATE["stop_at"]
    return EscalationStepResult(stopped=stopped, notified=2)


@pytest_asyncio.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as e:
        yield e


def _plan_of(steps, repeat=None, max_reminders=48, state="OPEN"):
    return EscalationPlan(state=state, steps=[PlanStep(level=lv, after_minutes=m) for lv, m in steps], repeat_minutes=repeat, max_reminders=max_reminders)


async def _start(env, plan, *, started_ago_minutes=0.0, **inp_kw):
    STATE.update(plan=plan, calls=[], stop_at=None, fail_levels=set(), plan_failures=0)
    tq = f"tq-esc-{uuid.uuid4().hex[:8]}"
    worker = Worker(env.client, task_queue=tq, workflows=[AlertEscalationWorkflow], activities=[_plan, _step], workflow_runner=UnsandboxedWorkflowRunner())
    inp = AlertEscalationInput(bank_id="kbl", incident_id="inc1", started_at=time.time() - started_ago_minutes * 60, **inp_kw)
    return tq, worker, inp


async def _run(env, tq, inp):
    return await env.client.start_workflow(AlertEscalationWorkflow.run, inp, id=f"esc-{uuid.uuid4().hex[:6]}", task_queue=tq)


@pytest.mark.asyncio
async def test_each_step_fires_at_its_time_counted_from_when_the_incident_opened(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5), (2, 15)]))
    async with worker:
        h = await _run(env, tq, inp)
        await env.sleep(6 * 60)
        assert STATE["calls"] == [("ESCALATE", 1, 0)]
        await env.sleep(10 * 60)
        assert STATE["calls"] == [("ESCALATE", 1, 0), ("ESCALATE", 2, 0)]
        assert await h.result() == "COMPLETED"


@pytest.mark.asyncio
async def test_time_already_passed_since_the_incident_opened_counts(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5)]), started_ago_minutes=4)
    async with worker:
        h = await _run(env, tq, inp)
        await env.sleep(2 * 60)                                  # only about one minute of the five remained
        assert STATE["calls"] == [("ESCALATE", 1, 0)]
        assert await h.result() == "COMPLETED"


@pytest.mark.asyncio
async def test_an_acknowledgement_signal_stops_escalation_before_it_happens(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5), (2, 15)]))
    async with worker:
        h = await _run(env, tq, inp)
        await env.sleep(3 * 60)
        await h.signal(AlertEscalationWorkflow.stop, "acknowledged")
        await env.sleep(30 * 60)
        assert STATE["calls"] == [] and await h.result() == "STOPPED:acknowledged"


@pytest.mark.asyncio
async def test_when_the_database_says_it_is_no_longer_open_escalation_ends_without_a_signal(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5), (2, 15)]))
    STATE["stop_at"] = 1                                         # the first step finds the incident resolved
    async with worker:
        h = await _run(env, tq, inp)
        assert await h.result() == "STOPPED:closed"
        assert STATE["calls"] == [("ESCALATE", 1, 0)]


@pytest.mark.asyncio
async def test_after_the_last_step_it_reminds_on_the_interval_up_to_the_maximum(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5)], repeat=10, max_reminders=3))
    async with worker:
        h = await _run(env, tq, inp)
        assert await h.result() == "EXHAUSTED"
        assert STATE["calls"] == [("ESCALATE", 1, 0), ("REMIND", 1, 1), ("REMIND", 1, 2), ("REMIND", 1, 3)]


@pytest.mark.asyncio
async def test_a_stop_during_reminders_ends_them(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5)], repeat=10, max_reminders=50))
    async with worker:
        h = await _run(env, tq, inp)
        await env.sleep(26 * 60)                                 # escalated at 5, reminded at 15 and 25
        await h.signal(AlertEscalationWorkflow.stop, "resolved")
        assert await h.result() == "STOPPED:resolved" and len(STATE["calls"]) == 3


@pytest.mark.asyncio
async def test_an_incident_that_is_not_open_ends_at_once(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5)], state="STOPPED"))
    async with worker:
        assert await (await _run(env, tq, inp)).result() == "NOT_OPEN" and STATE["calls"] == []


@pytest.mark.asyncio
async def test_a_policy_with_no_escalation_and_no_reminders_ends_at_once(env):
    tq, worker, inp = await _start(env, _plan_of([]))
    async with worker:
        assert await (await _run(env, tq, inp)).result() == "COMPLETED" and STATE["calls"] == []


@pytest.mark.asyncio
async def test_a_step_that_fails_does_not_stop_the_later_ones(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5), (2, 15)]))
    STATE["fail_levels"] = {1}
    async with worker:
        h = await _run(env, tq, inp)
        assert await h.result() == "COMPLETED"
        assert [c[1] for c in STATE["calls"] if c[0] == "ESCALATE"][-1] == 2


@pytest.mark.asyncio
async def test_a_plan_that_cannot_be_made_is_retried_then_given_up_without_crashing(env):
    tq, worker, inp = await _start(env, _plan_of([(1, 5)]), plan_retry_attempts=3, plan_retry_seconds=60)
    STATE["plan_failures"] = 2
    async with worker:
        assert await (await _run(env, tq, inp)).result() == "COMPLETED"            # the third try worked
    tq, worker, inp = await _start(env, _plan_of([(1, 5)]), plan_retry_attempts=2, plan_retry_seconds=60)
    STATE["plan_failures"] = 5
    async with worker:
        assert await (await _run(env, tq, inp)).result() == "PLAN_FAILED"
