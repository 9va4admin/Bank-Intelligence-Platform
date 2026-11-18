"""Watches the health monitor from outside the worker. The monitor emails when a dependency fails; if the worker itself dies nothing
runs the monitor, so this runs in the API process (a different process) and reports a monitor that has stopped ticking or cannot be reached."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

import structlog

from modules.cts.health.state_machine import ComponentState, Probe, Thresholds, step
from modules.cts.workflows.platform_health_check_workflow import alerts_for_events
from shared.messages import get_message

log = structlog.get_logger()

COMPONENT = "health_monitor"


def classify_monitor(snapshot: Any, now: float, stale_after: float) -> tuple[str, Optional[str]]:
    """(RUNNING | STALE | NOT_RUNNING, reason). `snapshot` is the monitor's query result, or the exception the query raised."""
    if isinstance(snapshot, Exception):
        return "NOT_RUNNING", str(snapshot)[:200]
    last = snapshot.get("last_tick_at")
    if last is None:
        return "STALE", get_message("HEALTH_MONITOR_NO_TICK_YET")
    age = now - float(last)
    if age > stale_after:
        return "STALE", get_message("HEALTH_MONITOR_STALE_REASON", age_seconds=int(age))
    return "RUNNING", None


class MonitorWatchdog:
    def __init__(self, bank_id: str, *, thresholds: Thresholds, stale_after: float,
                 send: Callable[[Any], Awaitable[None]]) -> None:
        self._bank_id, self._thresholds, self._stale_after, self._send = bank_id, thresholds, stale_after, send
        self._state = ComponentState()

    async def check(self, client: Any, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        if client is None:
            snapshot: Any = RuntimeError(get_message("HEALTH_MONITOR_NO_TEMPORAL"))
        else:
            try:
                snapshot = await client.get_workflow_handle(f"cts-platform-health-{self._bank_id}").query("component_states")
            except Exception as exc:  # noqa: BLE001
                snapshot = exc
        status, reason = classify_monitor(snapshot, now, self._stale_after)
        self._state, events = step(self._state, Probe(component=COMPONENT, ok=status == "RUNNING", error=reason), now, self._thresholds)
        for alert in alerts_for_events(self._bank_id, events):
            try:
                await self._send(alert)
            except Exception as exc:  # noqa: BLE001  - a failing mail server must not stop the watchdog
                log.warning("monitor_watchdog.send_failed", bank_id=self._bank_id, error=str(exc)[:160])


async def run_watchdog(get_client: Callable[[], Any], watchdog: MonitorWatchdog, interval: float = 60.0) -> None:
    """The loop the API starts; never exits on error."""
    while True:
        try:
            await watchdog.check(get_client())
        except Exception as exc:  # noqa: BLE001
            log.warning("monitor_watchdog.check_failed", error=str(exc)[:160])
        await asyncio.sleep(interval)
