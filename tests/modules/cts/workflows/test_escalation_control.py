"""Starting and stopping an incident's escalation from outside a workflow (the API: a watchdog incident opens one, an acknowledgement stops it). Best effort and never raises:
an acknowledgement must succeed even if Temporal is unreachable (the escalation then stops by itself at its next step when the database says the incident is no longer open)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from modules.cts.workflows.escalation_control import escalation_workflow_id, start_escalation, stop_escalation


class AlreadyStarted(Exception):
    pass


AlreadyStarted.__name__ = "WorkflowAlreadyStartedError"


def test_the_workflow_id_is_deterministic_per_bank_and_incident():
    assert escalation_workflow_id("kbl", "inc1") == "cts-alert-kbl-inc1"


def test_start_uses_the_incident_workflow_id_and_the_banks_task_queue():
    client = MagicMock()
    client.start_workflow = AsyncMock()
    assert asyncio.run(start_escalation(client, "kbl", "inc1", started_at=123.0)) is True
    args, kw = client.start_workflow.await_args
    assert kw["id"] == "cts-alert-kbl-inc1" and kw["task_queue"] == "cts-processing-kbl"
    assert args[1].bank_id == "kbl" and args[1].incident_id == "inc1" and args[1].started_at == 123.0


def test_an_escalation_that_already_runs_is_fine_and_any_other_failure_is_swallowed():
    client = MagicMock()
    client.start_workflow = AsyncMock(side_effect=AlreadyStarted("running"))
    assert asyncio.run(start_escalation(client, "kbl", "inc1", started_at=1.0)) is True
    client.start_workflow = AsyncMock(side_effect=RuntimeError("temporal down"))
    assert asyncio.run(start_escalation(client, "kbl", "inc1", started_at=1.0)) is False
    assert asyncio.run(start_escalation(None, "kbl", "inc1", started_at=1.0)) is False


def test_stop_signals_the_escalation_with_the_reason_and_never_raises():
    handle = MagicMock()
    handle.signal = AsyncMock()
    client = MagicMock()
    client.get_workflow_handle = MagicMock(return_value=handle)
    assert asyncio.run(stop_escalation(client, "kbl", "inc1", "acknowledged")) is True
    client.get_workflow_handle.assert_called_once_with("cts-alert-kbl-inc1")
    assert handle.signal.await_args.args[1] == "acknowledged"
    handle.signal = AsyncMock(side_effect=RuntimeError("not found"))
    assert asyncio.run(stop_escalation(client, "kbl", "inc1", "acknowledged")) is False
    assert asyncio.run(stop_escalation(None, "kbl", "inc1", "acknowledged")) is False
