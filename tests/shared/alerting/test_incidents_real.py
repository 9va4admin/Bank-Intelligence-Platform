"""IncidentStore against the real dev YugabyteDB (platform.alert_incidents, migration 20261117_alerting_tables). Skipped when it is not reachable."""
import asyncio
import socket
import uuid

import pytest

from shared.alerting.incidents import IncidentStore

pytestmark = pytest.mark.integration

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _run(coro_fn):
    """Fresh pool per test (the event loop is per asyncio.run)."""
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=8)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            return await coro_fn(IncidentStore(pool), bank, pool)
        finally:
            for t in ("alert_incidents", "component_state_history"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def _raise(store, bank, key="component:redis:down", severity="P0", summary="redis down"):
    return store.open_or_update(bank_id=bank, dedup_key=key, alert_id="COMPONENT_DOWN", component="redis", severity=severity, summary=summary)


def test_the_same_problem_is_one_incident_not_many():
    async def go(store, bank, pool):
        a = await _raise(store, bank)
        b = await _raise(store, bank, summary="still down")
        assert a.created and not b.created and a.incident_id == b.incident_id
        row = await pool.fetchrow("SELECT summary, state FROM platform.alert_incidents WHERE incident_id=$1", a.incident_id)
        assert row["summary"] == "still down" and row["state"] == "OPEN"
    _run(go)


def test_twenty_simultaneous_raises_make_exactly_one_incident():
    async def go(store, bank, pool):
        results = await asyncio.gather(*[_raise(store, bank) for _ in range(20)])
        assert len({r.incident_id for r in results}) == 1 and sum(1 for r in results if r.created) == 1
        assert await pool.fetchval("SELECT COUNT(*) FROM platform.alert_incidents WHERE bank_id=$1", bank) == 1
    _run(go)


def test_a_worse_severity_raises_the_incident_and_a_milder_one_does_not_lower_it():
    async def go(store, bank, pool):
        a = await _raise(store, bank, severity="P1")
        b = await _raise(store, bank, severity="P0")
        c = await _raise(store, bank, severity="P2")
        assert (a.severity, b.severity, c.severity) == ("P1", "P0", "P0") and b.severity_raised and not c.severity_raised
    _run(go)


def test_acknowledge_moves_open_to_acked_once_and_records_who():
    async def go(store, bank, pool):
        a = await _raise(store, bank)
        assert await store.acknowledge(bank, a.incident_id, "user-7") is True
        assert await store.acknowledge(bank, a.incident_id, "user-8") is False          # already acknowledged: nothing changes
        row = await pool.fetchrow("SELECT state, acked_by FROM platform.alert_incidents WHERE incident_id=$1", a.incident_id)
        assert (row["state"], row["acked_by"]) == ("ACKED", "user-7")
        b = await _raise(store, bank)                                                    # a new alert for the same problem keeps it acknowledged
        assert b.incident_id == a.incident_id and b.state == "ACKED"
    _run(go)


def test_resolve_closes_it_and_the_next_failure_is_a_new_incident():
    async def go(store, bank, pool):
        a = await _raise(store, bank)
        closed = await store.resolve(bank, "component:redis:down", "system:alert-engine")
        assert closed is not None and closed.incident_id == a.incident_id and closed.duration_seconds is not None
        assert await store.resolve(bank, "component:redis:down", "system:alert-engine") is None     # nothing open any more
        b = await _raise(store, bank)
        assert b.created and b.incident_id != a.incident_id
    _run(go)


def test_acknowledging_or_resolving_someone_elses_incident_is_refused():
    async def go(store, bank, pool):
        a = await _raise(store, bank)
        assert await store.acknowledge("another-bank", a.incident_id, "u") is False
        assert await store.resolve("another-bank", "component:redis:down", "u") is None
    _run(go)


def test_notifications_are_counted_and_open_incidents_listed_per_bank():
    async def go(store, bank, pool):
        a = await _raise(store, bank)
        await store.record_notification(bank, a.incident_id)
        await store.record_notification(bank, a.incident_id)
        row = await pool.fetchrow("SELECT notification_count, last_notified_at FROM platform.alert_incidents WHERE incident_id=$1", a.incident_id)
        assert row["notification_count"] == 2 and row["last_notified_at"] is not None
        await _raise(store, bank, key="component:kafka:down")
        assert len(await store.list_open(bank)) == 2 and await store.list_open("another-bank") == []
    _run(go)


def test_state_changes_are_recorded_for_history():
    async def go(store, bank, pool):
        await store.record_state_change(bank, "redis", "OK", "DOWN", latency_ms=None, error="refused", incident_id="i1")
        await store.record_state_change(bank, "redis", "DOWN", "OK", latency_ms=12.5, error=None, incident_id="i1")
        rows = await pool.fetch("SELECT from_status, to_status FROM platform.component_state_history WHERE bank_id=$1 ORDER BY id", bank)
        assert [(r["from_status"], r["to_status"]) for r in rows] == [("OK", "DOWN"), ("DOWN", "OK")]
    _run(go)
