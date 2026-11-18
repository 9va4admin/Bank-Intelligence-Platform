"""A monitor already running when ASTRA is upgraded must keep running. The history is a REAL one recorded from the dev stack before the alerting
changes; replaying it against today's workflow code must not raise a non-determinism error (it did, until the new steps were put behind patch markers)."""
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner

from modules.cts.workflows.platform_health_check_workflow import PlatformHealthCheckWorkflow
from shared.temporal.converter import pydantic_data_converter

HISTORY = Path(__file__).parent / "histories" / "platform_health_before_alerting.json"


@pytest.mark.asyncio
async def test_a_monitor_started_before_the_alerting_changes_still_replays():
    history = WorkflowHistory.from_json("cts-platform-health-kbl", HISTORY.read_text())
    await Replayer(workflows=[PlatformHealthCheckWorkflow], data_converter=pydantic_data_converter,
                   workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(history)       # the worker runs unsandboxed too
