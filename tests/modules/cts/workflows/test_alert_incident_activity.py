"""record_alert_incident: an alert opens, updates or resolves an incident, is audited, and never blocks a send when the database is down."""
import asyncio
import socket
import uuid

import pytest

from modules.cts.health.state_machine import ComponentState
from modules.cts.workflows.activities.platform_health_activities import (
    DispatchAlertInput, record_alert_incident, status_changes,
)
from shared.alerting.audit import AlertAuditor
from shared.alerting.incidents import ClosedIncident, OpenResult


class _Store:
    """Stands in for IncidentStore (the real one is exercised against YugabyteDB in tests/shared/alerting/test_incidents_real.py)."""
    def __init__(self, fail=False):
        self.calls, self.fail, self.open_ids = [], fail, {}

    async def open_or_update(self, **kw):
        if self.fail:
            raise ConnectionError("db down")
        self.calls.append(("open", kw["dedup_key"], kw["severity"]))
        key = kw["dedup_key"]
        if key in self.open_ids:
            return OpenResult(incident_id=self.open_ids[key], created=False, severity=kw["severity"], state="OPEN")
        self.open_ids[key] = f"inc-{len(self.open_ids) + 1}"
        return OpenResult(incident_id=self.open_ids[key], created=True, severity=kw["severity"], state="OPEN")

    async def resolve(self, bank_id, dedup_key, by):
        self.calls.append(("resolve", dedup_key, by))
        if dedup_key not in self.open_ids:
            return None
        return ClosedIncident(incident_id=self.open_ids.pop(dedup_key), severity="P0", component="redis", duration_seconds=125.0)

    async def record_notification(self, bank_id, incident_id):
        self.calls.append(("notified", incident_id))


class _Audit:
    def __init__(self):
        self.events = []

    def auditor(self):
        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            self.events.append((event_type, entity_id, payload))
            return f"tx-{len(self.events)}"
        return AlertAuditor(sink)


def _alert(event_type="COMPONENT_DOWN", priority="P0", component="redis"):
    return DispatchAlertInput(bank_id="kbl", event_type=event_type, component=component, message="m", severity="CRITICAL", priority=priority)


def _run(alert, store, audit):
    return asyncio.run(record_alert_incident(alert, db_pool=object(), alert_auditor=audit.auditor(), store=store))


def test_a_new_problem_opens_an_incident_and_is_audited_as_raised():
    store, audit = _Store(), _Audit()
    r = _run(_alert(), store, audit)
    assert r.incident_id == "inc-1" and r.created and not r.resolved
    assert [e[0] for e in audit.events] == ["ALERT_RAISED"] and audit.events[0][1] == "inc-1"


def test_the_same_problem_again_reuses_the_incident_without_a_second_raised_record():
    store, audit = _Store(), _Audit()
    first = _run(_alert(), store, audit)
    again = _run(_alert("COMPONENT_REMINDER"), store, audit)
    assert again.incident_id == first.incident_id and not again.created
    assert [e[0] for e in audit.events] == ["ALERT_RAISED"]


def test_a_recovery_resolves_the_incident_with_its_duration_and_is_audited():
    store, audit = _Store(), _Audit()
    opened = _run(_alert(), store, audit)
    r = _run(_alert("COMPONENT_RECOVERED", "P3"), store, audit)
    assert r.incident_id == opened.incident_id and r.resolved
    assert audit.events[-1][0] == "ALERT_RESOLVED" and audit.events[-1][2]["duration_seconds"] == 125.0


def test_a_recovery_with_nothing_open_is_a_quiet_no_op():
    store, audit = _Store(), _Audit()
    r = _run(_alert("COMPONENT_RECOVERED", "P3"), store, audit)
    assert r.incident_id == "" and not r.resolved and audit.events == []


def test_a_database_failure_degrades_to_no_incident_and_never_raises():
    r = _run(_alert(), _Store(fail=True), _Audit())
    assert r.incident_id == "" and r.degraded


def test_without_a_database_pool_it_degrades():
    r = asyncio.run(record_alert_incident(_alert(), db_pool=None, alert_auditor=None))
    assert r.incident_id == "" and r.degraded


def test_status_changes_lists_only_components_whose_state_changed_including_the_first_reading():
    prior = {"redis": ComponentState(status="OK"), "kafka": ComponentState(status="OK")}
    new = {"redis": ComponentState(status="DOWN", last_error="refused"), "kafka": ComponentState(status="OK", last_latency_ms=5.0),
           "vault": ComponentState(status="OK", last_latency_ms=9.0)}
    changes = {c.component: c for c in status_changes(prior, new)}
    assert set(changes) == {"redis", "vault"}
    assert (changes["redis"].from_status, changes["redis"].to_status, changes["redis"].error) == ("OK", "DOWN", "refused")
    assert (changes["vault"].from_status, changes["vault"].to_status) == ("UNKNOWN", "OK")


# ---------------- the real database -----------------

def _db_up():
    try:
        socket.create_connection(("localhost", 15433), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _db_up(), reason="dev YugabyteDB not reachable")
def test_against_the_real_database_down_then_recovered_leaves_one_closed_incident_with_history():
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host="localhost", port=15433, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        audit = _Audit()
        try:
            down = DispatchAlertInput(bank_id=bank, event_type="COMPONENT_DOWN", component="redis", message="redis down", severity="CRITICAL", priority="P0")
            up = DispatchAlertInput(bank_id=bank, event_type="COMPONENT_RECOVERED", component="redis", message="back", severity="INFO", priority="P3")
            a = await record_alert_incident(down, db_pool=pool, alert_auditor=audit.auditor())
            b = await record_alert_incident(down, db_pool=pool, alert_auditor=audit.auditor())
            c = await record_alert_incident(up, db_pool=pool, alert_auditor=audit.auditor())
            assert a.created and not b.created and a.incident_id == b.incident_id == c.incident_id and c.resolved
            row = await pool.fetchrow("SELECT state, resolved_by FROM platform.alert_incidents WHERE incident_id=$1", a.incident_id)
            assert (row["state"], row["resolved_by"]) == ("RESOLVED", "system:alert-engine")
            assert [e[0] for e in audit.events] == ["ALERT_RAISED", "ALERT_RESOLVED"]
        finally:
            await pool.execute("DELETE FROM platform.alert_incidents WHERE bank_id=$1", bank)
            await pool.close()
    asyncio.run(go())
