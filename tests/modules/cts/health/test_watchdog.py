"""The watchdog runs outside the worker, so it can tell the operators when the health monitor itself has stopped."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from modules.cts.health.state_machine import Thresholds
from modules.cts.health.watchdog import MonitorWatchdog, classify_monitor

_T = Thresholds(down_after_failures=2, recover_after_successes=1, reminder_every_seconds=1800)


def test_a_recent_tick_means_running():
    now = 1000.0
    assert classify_monitor({"last_tick_at": now - 30, "tick": 5}, now, 180) == ("RUNNING", None)


def test_an_old_tick_means_stale():
    status, _ = classify_monitor({"last_tick_at": 0.0, "tick": 5}, 1000.0, 180)
    assert status == "STALE"


def test_no_tick_yet_is_stale_not_running():
    assert classify_monitor({"last_tick_at": None, "tick": 0}, 1000.0, 180)[0] == "STALE"


def test_a_failed_query_means_not_running():
    status, error = classify_monitor(RuntimeError("workflow not found"), 1000.0, 180)
    assert status == "NOT_RUNNING" and "workflow not found" in error


def _client(result):
    handle = MagicMock()
    handle.query = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
    client = MagicMock()
    client.get_workflow_handle = MagicMock(return_value=handle)
    return client


def _wd(sent):
    async def send(alert):
        sent.append(alert)
    return MonitorWatchdog("kbl", thresholds=_T, stale_after=180, send=send)


def test_alerts_once_after_consecutive_bad_checks_then_a_recovery():
    sent = []
    wd = _wd(sent)
    dead = _client(RuntimeError("gone"))
    ok = lambda now: _client({"last_tick_at": now, "tick": 9})

    asyncio.run(wd.check(dead, now=100.0))
    assert sent == []                                   # one blip is not an outage
    asyncio.run(wd.check(dead, now=160.0))
    assert len(sent) == 1 and sent[0].component == "health_monitor" and sent[0].priority == "P0"
    asyncio.run(wd.check(dead, now=220.0))
    assert len(sent) == 1                               # not every minute
    asyncio.run(wd.check(ok(300.0), now=300.0))
    assert len(sent) == 2 and sent[1].template == "PLATFORM_HEALTH_RECOVERED"


def test_a_failing_send_never_breaks_the_check():
    async def boom(alert):
        raise RuntimeError("smtp down")
    wd = MonitorWatchdog("kbl", thresholds=_T, stale_after=180, send=boom)
    dead = _client(RuntimeError("gone"))
    asyncio.run(wd.check(dead, now=1.0))
    asyncio.run(wd.check(dead, now=61.0))               # would send; the failure is contained


def test_a_missing_temporal_client_counts_as_not_running():
    sent = []
    wd = _wd(sent)
    asyncio.run(wd.check(None, now=1.0))
    asyncio.run(wd.check(None, now=61.0))
    assert len(sent) == 1
