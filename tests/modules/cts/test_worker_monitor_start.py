"""Starting the monitor when the worker starts: a fresh start, or an already-running one that is asked to restart so it picks up upgraded code."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from modules.cts import worker


class AlreadyStarted(Exception):
    pass


AlreadyStarted.__name__ = "WorkflowAlreadyStartedError"


def test_a_fresh_start_does_not_signal_anything():
    client = MagicMock()
    client.start_workflow = AsyncMock(return_value=MagicMock())
    asyncio.run(worker._start_platform_health(client, "kbl"))
    client.get_workflow_handle.assert_not_called()


def test_an_already_running_monitor_is_asked_to_restart_so_it_adopts_the_new_code():
    handle = MagicMock()
    handle.signal = AsyncMock()
    client = MagicMock()
    client.start_workflow = AsyncMock(side_effect=AlreadyStarted("running"))
    client.get_workflow_handle = MagicMock(return_value=handle)
    asyncio.run(worker._start_platform_health(client, "kbl"))
    client.get_workflow_handle.assert_called_once_with("cts-platform-health-kbl")
    assert handle.signal.await_count == 1


def test_a_failing_signal_never_stops_the_worker():
    handle = MagicMock()
    handle.signal = AsyncMock(side_effect=RuntimeError("temporal hiccup"))
    client = MagicMock()
    client.start_workflow = AsyncMock(side_effect=AlreadyStarted("running"))
    client.get_workflow_handle = MagicMock(return_value=handle)
    asyncio.run(worker._start_platform_health(client, "kbl"))      # must return quietly
