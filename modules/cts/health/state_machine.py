"""Component health state machine: probe results in, component state and alert events out. Pure: no I/O and no clock of its own.

States: UNKNOWN (before the first probe) -> OK <-> SLOW, and OK/SLOW -> DOWN -> OK.
Flap control: DOWN needs `down_after_failures` consecutive failed probes; recovery needs `recover_after_successes` consecutive good ones; SLOW needs
`slow_after` consecutive slow probes and clears after `recover_after_successes` consecutive fast ones. An outage is announced once and then reminded about
every `reminder_every_seconds`, not every minute. Nothing alerts on the first failed probe after start-up.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from shared.messages import get_message


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    down_after_failures: int = 3
    recover_after_successes: int = 2
    slow_after: int = 3
    reminder_every_seconds: float = 1800.0


class Probe(BaseModel):
    """One probe result. slow_ms: latency above which a successful probe counts as slow (None = latency is not judged)."""
    model_config = ConfigDict(frozen=True)
    component: str
    ok: bool
    latency_ms: Optional[float] = None
    slow_ms: Optional[float] = None
    error: Optional[str] = None
    critical: bool = True


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str                          # DOWN | REMINDER | RECOVERED | SLOW | SLOW_CLEARED
    component: str
    severity: str                      # P0 critical down, P1 non-critical down, P2 slow, P3 recovery
    message: str
    down_for_seconds: Optional[float] = None


class ComponentState(BaseModel):
    status: str = "UNKNOWN"            # UNKNOWN | OK | SLOW | DOWN
    since: Optional[float] = None      # when it entered the current status
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    consecutive_slow: int = 0
    consecutive_fast: int = 0
    last_checked: Optional[float] = None
    last_latency_ms: Optional[float] = None
    last_error: Optional[str] = None
    last_alert_at: Optional[float] = None
    critical: bool = True


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    return f"{minutes // 60}h {minutes % 60}m"


def step(state: ComponentState, probe: Probe, now: float, thresholds: Thresholds) -> tuple[ComponentState, list[Event]]:
    s = state.model_copy()
    events: list[Event] = []
    s.last_checked = now
    s.critical = probe.critical
    down_severity = "P0" if probe.critical else "P1"

    if not probe.ok:
        s.consecutive_failures += 1
        s.consecutive_successes = s.consecutive_slow = s.consecutive_fast = 0
        s.last_error = probe.error
        if s.status != "DOWN" and s.consecutive_failures >= thresholds.down_after_failures:
            s.status, s.since, s.last_alert_at = "DOWN", now, now
            events.append(Event(kind="DOWN", component=probe.component, severity=down_severity,
                                message=get_message("HEALTH_COMPONENT_DOWN", component=probe.component,
                                                    failures=s.consecutive_failures, error=probe.error or "")))
        elif s.status == "DOWN" and now - (s.last_alert_at or now) >= thresholds.reminder_every_seconds:
            s.last_alert_at = now
            down_for = now - (s.since or now)
            events.append(Event(kind="REMINDER", component=probe.component, severity=down_severity, down_for_seconds=down_for,
                                message=get_message("HEALTH_COMPONENT_STILL_DOWN", component=probe.component,
                                                    down_for=human_duration(down_for), error=probe.error or "")))
        return s, events

    s.consecutive_failures = 0
    s.consecutive_successes += 1
    s.last_error = None
    s.last_latency_ms = probe.latency_ms
    slow = probe.slow_ms is not None and probe.latency_ms is not None and probe.latency_ms > probe.slow_ms
    s.consecutive_slow = s.consecutive_slow + 1 if slow else 0
    s.consecutive_fast = 0 if slow else s.consecutive_fast + 1

    if s.status == "UNKNOWN":
        s.status, s.since = "OK", now
    elif s.status == "DOWN":
        if s.consecutive_successes >= thresholds.recover_after_successes:
            down_for = now - (s.since or now)
            s.status, s.since = "OK", now
            events.append(Event(kind="RECOVERED", component=probe.component, severity="P3", down_for_seconds=down_for,
                                message=get_message("HEALTH_COMPONENT_RECOVERED", component=probe.component, down_for=human_duration(down_for))))
            return s, events
    if s.status == "OK" and s.consecutive_slow >= thresholds.slow_after:
        s.status, s.since, s.last_alert_at = "SLOW", now, now
        events.append(Event(kind="SLOW", component=probe.component, severity="P2",
                            message=get_message("HEALTH_COMPONENT_SLOW", component=probe.component,
                                                latency_ms=int(probe.latency_ms or 0), slow_ms=int(probe.slow_ms or 0))))
    elif s.status == "SLOW" and s.consecutive_fast >= thresholds.recover_after_successes:
        slow_for = now - (s.since or now)
        s.status, s.since = "OK", now
        events.append(Event(kind="SLOW_CLEARED", component=probe.component, severity="P3", down_for_seconds=slow_for,
                            message=get_message("HEALTH_COMPONENT_SLOW_CLEARED", component=probe.component)))
    return s, events
