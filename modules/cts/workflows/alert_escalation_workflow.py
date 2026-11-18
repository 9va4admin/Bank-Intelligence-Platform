"""AlertEscalationWorkflow: one per open incident (id cts-alert-{bank_id}-{incident_id}). docs/design/alerting-1b-plan.md

It waits for each escalation step's time, counted from when the incident opened, and escalates; it ends the moment the incident is acknowledged or resolved (a `stop`
signal, or the database says so at the next step); after the last step it re-notifies on the policy's interval, up to a configured number of times. The first
notification is not its job: the alert send path does that. What each step does (who is told, through which channels) is decided at the moment the step fires, so a
policy or rota changed in the meantime is respected.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from modules.cts.workflows.activities.alert_escalation_activities import EscalationStepInput, PlanInput, plan_escalation, run_escalation_step

_PLAN_TIMEOUT = timedelta(seconds=30)
_STEP_TIMEOUT = timedelta(seconds=90)
_STEP_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
_PLAN_RETRY = RetryPolicy(maximum_attempts=1)


class AlertEscalationInput(BaseModel):
    bank_id: str
    incident_id: str
    started_at: float                        # when the incident opened (epoch seconds); step times count from here
    plan_retry_attempts: int = 5             # the plan needs the database; try this many times before giving up
    plan_retry_seconds: int = 60


@workflow.defn
class AlertEscalationWorkflow:
    def __init__(self) -> None:
        self._stop: Optional[str] = None

    @workflow.signal
    def stop(self, reason: str) -> None:
        """The incident was acknowledged or resolved: end the escalation."""
        if self._stop is None:
            self._stop = reason

    async def _wait(self, seconds: float) -> bool:
        """Sleep, but wake at once on a stop. True if stopped."""
        if seconds > 0:
            try:
                await workflow.wait_condition(lambda: self._stop is not None, timeout=timedelta(seconds=seconds))
            except asyncio.TimeoutError:
                pass
        return self._stop is not None

    async def _plan(self, inp: AlertEscalationInput):
        for attempt in range(1, max(1, inp.plan_retry_attempts) + 1):
            try:
                return await workflow.execute_activity(plan_escalation, PlanInput(bank_id=inp.bank_id, incident_id=inp.incident_id),
                                                       start_to_close_timeout=_PLAN_TIMEOUT, retry_policy=_PLAN_RETRY)
            except ActivityError:
                if attempt >= max(1, inp.plan_retry_attempts) or await self._wait(inp.plan_retry_seconds):
                    return None
        return None

    @workflow.run
    async def run(self, inp: AlertEscalationInput) -> str:
        plan = await self._plan(inp)
        if self._stop is not None:
            return f"STOPPED:{self._stop}"
        if plan is None:
            return "PLAN_FAILED"
        if plan.state != "OPEN":
            return "NOT_OPEN"

        last_level = 0
        for step in sorted(plan.steps, key=lambda s: s.level):
            if await self._wait(inp.started_at + step.after_minutes * 60 - workflow.now().timestamp()):
                return f"STOPPED:{self._stop}"
            try:
                result = await workflow.execute_activity(run_escalation_step, EscalationStepInput(bank_id=inp.bank_id, incident_id=inp.incident_id, level=step.level),
                                                         start_to_close_timeout=_STEP_TIMEOUT, retry_policy=_STEP_RETRY)
                if result.stopped:
                    return "STOPPED:closed"
            except ActivityError:
                pass                                   # a step that fails must not stop the later ones
            last_level = step.level

        if not plan.repeat_minutes:
            return "COMPLETED"
        for sequence in range(1, plan.max_reminders + 1):
            if await self._wait(plan.repeat_minutes * 60):
                return f"STOPPED:{self._stop}"
            try:
                result = await workflow.execute_activity(run_escalation_step,
                                                         EscalationStepInput(bank_id=inp.bank_id, incident_id=inp.incident_id, level=last_level, kind="REMIND", sequence=sequence),
                                                         start_to_close_timeout=_STEP_TIMEOUT, retry_policy=_STEP_RETRY)
                if result.stopped:
                    return "STOPPED:closed"
            except ActivityError:
                pass
        return "EXHAUSTED"
