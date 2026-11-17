"""Component health state machine: probe results in, state and alert events out. No I/O, no clock of its own.

Rules under test: one failed probe is not an outage (N consecutive failures are); a component that is down is reminded about, not re-announced every
minute; recovery needs consecutive successes; slowness is its own state with its own consecutive count; the first probe after start-up never alerts on one failure.
"""
import pytest

from modules.cts.health.state_machine import ComponentState, Event, Probe, Thresholds, step

T = Thresholds(down_after_failures=3, recover_after_successes=2, slow_after=3, reminder_every_seconds=1800)


def _ok(ms=5.0, slow_ms=None, critical=True):
    return Probe(component="yugabyte", ok=True, latency_ms=ms, slow_ms=slow_ms, error=None, critical=critical)


def _fail(error="refused", critical=True):
    return Probe(component="yugabyte", ok=False, latency_ms=None, slow_ms=None, error=error, critical=critical)


def _run(probes, start=None, t0=1000.0, every=60.0, thresholds=T):
    state, events = start or ComponentState(), []
    for i, p in enumerate(probes):
        state, ev = step(state, p, now=t0 + i * every, thresholds=thresholds)
        events.append(ev)
    return state, events


def test_first_success_is_ok_and_silent():
    state, events = _run([_ok()])
    assert state.status == "OK" and events == [[]]


def test_one_or_two_failures_do_not_raise_an_alert():
    state, events = _run([_ok(), _fail(), _fail()])
    assert state.status == "OK" and state.consecutive_failures == 2 and all(e == [] for e in events)


def test_the_third_consecutive_failure_marks_it_down_and_alerts_once_at_p0_for_a_critical_component():
    state, events = _run([_ok(), _fail("refused"), _fail("refused"), _fail("refused")])
    assert state.status == "DOWN" and state.since == 1000.0 + 3 * 60
    assert [e.kind for e in events[-1]] == ["DOWN"] and events[-1][0].severity == "P0" and "refused" in events[-1][0].message
    assert all(e == [] for e in events[:-1])


def test_a_non_critical_component_is_p1():
    _, events = _run([_ok(critical=False), _fail(critical=False), _fail(critical=False), _fail(critical=False)])
    assert events[-1][0].severity == "P1"


def test_a_success_between_failures_resets_the_count():
    state, events = _run([_ok(), _fail(), _fail(), _ok(), _fail(), _fail()])
    assert state.status == "OK" and all(e == [] for e in events)


def test_down_is_not_re_announced_every_minute_but_reminded_after_the_interval():
    probes = [_ok(), _fail(), _fail(), _fail()] + [_fail()] * 40            # 40 more minutes of the same outage
    state, events = _run(probes)
    kinds = [e.kind for ev in events for e in ev]
    assert kinds.count("DOWN") == 1 and kinds.count("REMINDER") == 1       # 1800 s = 30 min: one reminder inside 40 min
    assert state.status == "DOWN"


def test_recovery_needs_consecutive_successes_and_reports_how_long_it_was_down():
    probes = [_ok(), _fail(), _fail(), _fail()] + [_ok(), _fail(), _ok(), _ok()]
    state, events = _run(probes)
    rec = [e for ev in events for e in ev if e.kind == "RECOVERED"]
    assert len(rec) == 1 and state.status == "OK"
    assert rec[0].down_for_seconds == pytest.approx((7 - 3) * 60)          # down at t=3, recovered at t=7 (the 2nd consecutive success)
    # the single success followed by a failure (index 4 then 5) did not recover it
    assert [e.kind for e in events[4]] == [] and [e.kind for e in events[5]] == []


def test_slow_is_a_separate_state_after_consecutive_slow_probes_and_clears_after_consecutive_fast_ones():
    slow, fast = _ok(ms=900.0, slow_ms=500.0), _ok(ms=20.0, slow_ms=500.0)
    state, events = _run([fast, slow, slow, slow])
    assert state.status == "SLOW" and [e.kind for e in events[-1]] == ["SLOW"] and events[-1][0].severity == "P2"
    state, events = _run([fast, slow, slow, slow, fast, fast], thresholds=T)
    assert state.status == "OK" and [e.kind for e in events[-1]] == ["SLOW_CLEARED"]


def test_a_slow_probe_amid_fast_ones_does_not_flip_the_state():
    slow, fast = _ok(ms=900.0, slow_ms=500.0), _ok(ms=20.0, slow_ms=500.0)
    state, events = _run([fast, slow, fast, slow, fast, slow])
    assert state.status == "OK" and all(e == [] for e in events)


def test_down_takes_precedence_over_slow():
    slow = _ok(ms=900.0, slow_ms=500.0)
    state, _ = _run([slow, slow, slow, slow, _fail(), _fail(), _fail()])
    assert state.status == "DOWN"


def test_last_probe_details_are_recorded_for_the_dashboard():
    state, _ = _run([_ok(ms=12.5), _fail("timeout")])
    assert state.last_checked == 1060.0 and state.last_error == "timeout" and state.last_latency_ms == 12.5


def test_a_component_that_starts_down_alerts_after_the_threshold_not_on_the_first_failure():
    state, events = _run([_fail(), _fail(), _fail()])
    assert state.status == "DOWN" and [e.kind for e in events[-1]] == ["DOWN"] and events[0] == [] and events[1] == []


def test_event_is_a_plain_value_object():
    e = Event(kind="DOWN", component="redis", severity="P0", message="m")
    assert e.down_for_seconds is None and e.component == "redis"
