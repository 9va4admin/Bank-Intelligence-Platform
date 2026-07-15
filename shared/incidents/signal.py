"""
emit_incident_signal() — the one new call site the error->incident plan adds
to existing catch blocks (see docs/astra-incident-management-plan, §06).

Reads the incident: block already attached to a messages.yaml entry
(shared/messages/registry.py) and increments a single counter,
astra_incident_signal_total, labelled with everything the generated
Prometheus alert rules (shared/messages/build_alerts.py) match against.
Nothing here talks to Alertmanager, Kafka, or Immudb directly — those all
react to the metric asynchronously, so a broken incident pipeline can never
add latency or a new failure mode to the caller's real workflow.

Fire-and-forget by design: an unknown key or a key with no incident: block
(most WARN/ERROR/CRITICAL keys are not classified yet — see the phased
rollout in the plan) is a silent no-op, not an exception. This must never be
able to break the business logic it's instrumenting.
"""
from typing import Any, Optional

import structlog

from shared.messages import get_entry
from shared.messages.registry import UnknownMessageKey

log = structlog.get_logger()

_METRIC_NAME = "astra_incident_signal_total"
_counter: Optional[Any] = None


def _get_counter() -> Any:
    global _counter
    if _counter is None:
        from shared.observability.otel_setup import get_meter
        meter = get_meter("astra.incidents")
        _counter = meter.create_counter(
            _METRIC_NAME,
            description="Caught errors classified for incident routing, by message key",
        )
    return _counter


def emit_incident_signal(key: str, bank_id: str, *, counter: Any = None) -> None:
    """
    Increment the incident signal counter for `key`, if and only if it
    carries a complete incident: block in the message registry.

    counter is for tests only — production callers never pass it; the real,
    lazily-created OTel counter is reused across every call.
    """
    try:
        entry = get_entry(key)
    except UnknownMessageKey:
        log.warning("incident_signal.unknown_key", key=key, bank_id=bank_id)
        return

    if entry.incident is None:
        return

    active_counter = counter if counter is not None else _get_counter()
    active_counter.add(1, {
        "message_key": key,
        "bank_id": bank_id,
        "incident_class": entry.incident.incident_class,
        "severity": entry.incident.default_severity,
        "owning_team": entry.incident.owning_team,
    })
