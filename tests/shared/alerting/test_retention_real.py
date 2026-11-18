"""Pruning the working copy of alert history on the real dev YugabyteDB. Immudb keeps the legal record; this keeps the tables from growing for ever.
Never touches anything still live: open incidents, deliveries in flight, unacknowledged critical notifications."""
import asyncio
import socket
import uuid

import pytest

from shared.alerting.retention import RetentionPolicy, prune_alert_history

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]

POLICY = RetentionPolicy(incident_days=30, history_days=30, inbox_days=10, batch_size=100)


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(pool, bank)
        finally:
            for t in ("alert_deliveries", "alert_incidents", "component_state_history", "user_notifications"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


async def _incident(pool, bank, iid, state, days_ago, key=None):
    await pool.execute(
        "INSERT INTO platform.alert_incidents (incident_id, bank_id, dedup_key, alert_id, component, severity, state, summary, opened_at, resolved_at) "
        "VALUES ($1,$2,$3,'X','redis','P1',$4,'s', NOW() - make_interval(days => $5), CASE WHEN $4='RESOLVED' THEN NOW() - make_interval(days => $5) END)",
        iid, bank, key or iid, state, days_ago)


async def _delivery(pool, bank, did, incident, status, days_ago):
    await pool.execute(
        "INSERT INTO platform.alert_deliveries (delivery_id, bank_id, incident_id, idempotency_key, channel, recipient_ref, status, created_at, completed_at) "
        "VALUES ($1,$2,$3,$1,'email','x***@y',$4, NOW() - make_interval(days => $5), CASE WHEN $4 IN ('SENT','UNDELIVERED') THEN NOW() - make_interval(days => $5) END)",
        did, bank, incident, status, days_ago)


async def _count(pool, table, bank):
    return await pool.fetchval(f"SELECT COUNT(*) FROM platform.{table} WHERE bank_id=$1", bank)


def test_old_resolved_incidents_and_their_deliveries_go_and_everything_live_stays():
    async def go(pool, bank):
        await _incident(pool, bank, "old-resolved", "RESOLVED", 60)
        await _incident(pool, bank, "new-resolved", "RESOLVED", 5)
        await _incident(pool, bank, "old-open", "OPEN", 90)                    # still open: never pruned however old
        await _incident(pool, bank, "old-acked", "ACKED", 90)
        await _delivery(pool, bank, "d-old", "old-resolved", "SENT", 60)
        await _delivery(pool, bank, "d-new", "new-resolved", "SENT", 5)
        await _delivery(pool, bank, "d-open", "old-open", "SENT", 90)
        await _delivery(pool, bank, "d-flight", "old-open", "FAILED", 90)      # awaiting retry: never pruned
        res = await prune_alert_history(pool, bank, POLICY)
        ids = {r["incident_id"] for r in await pool.fetch("SELECT incident_id FROM platform.alert_incidents WHERE bank_id=$1", bank)}
        assert ids == {"new-resolved", "old-open", "old-acked"} and res.incidents == 1
        left = {r["delivery_id"] for r in await pool.fetch("SELECT delivery_id FROM platform.alert_deliveries WHERE bank_id=$1", bank)}
        assert left == {"d-new", "d-open", "d-flight"} and res.deliveries == 1
    _run(go)


def test_old_state_history_goes():
    async def go(pool, bank):
        await pool.execute("INSERT INTO platform.component_state_history (bank_id, component, from_status, to_status, changed_at) "
                           "VALUES ($1,'redis','OK','DOWN', NOW() - INTERVAL '60 days'), ($1,'redis','DOWN','OK', NOW() - INTERVAL '1 day')", bank)
        res = await prune_alert_history(pool, bank, POLICY)
        assert res.state_changes == 1 and await _count(pool, "component_state_history", bank) == 1
    _run(go)


def test_old_notifications_go_but_an_unacknowledged_critical_one_never_does():
    async def go(pool, bank):
        await pool.execute(
            "INSERT INTO platform.user_notifications (notification_id, bank_id, user_id, severity, title, created_at, read_at, acked_at) VALUES "
            "('read-old',$1,'u','P1','t', NOW() - INTERVAL '30 days', NOW(), NULL),"
            "('unread-old',$1,'u','P1','t', NOW() - INTERVAL '30 days', NULL, NULL),"
            "('p0-unacked-old',$1,'u','P0','t', NOW() - INTERVAL '30 days', NOW(), NULL),"
            "('p0-acked-old',$1,'u','P0','t', NOW() - INTERVAL '30 days', NOW(), NOW()),"
            "('new',$1,'u','P1','t', NOW(), NULL, NULL)", bank)
        res = await prune_alert_history(pool, bank, POLICY)
        left = {r["notification_id"] for r in await pool.fetch("SELECT notification_id FROM platform.user_notifications WHERE bank_id=$1", bank)}
        assert left == {"p0-unacked-old", "new"}
        assert res.notifications == 3
    _run(go)


def test_the_batch_size_bounds_one_run_and_other_banks_are_untouched():
    async def go(pool, bank):
        for i in range(5):
            await _incident(pool, bank, f"old-{i}", "RESOLVED", 60)
        await _incident(pool, "other-bank-" + bank, "theirs", "RESOLVED", 60)
        try:
            res = await prune_alert_history(pool, bank, RetentionPolicy(incident_days=30, history_days=30, inbox_days=10, batch_size=2))
            assert res.incidents == 2 and await _count(pool, "alert_incidents", bank) == 3
            assert await _count(pool, "alert_incidents", "other-bank-" + bank) == 1
        finally:
            await pool.execute("DELETE FROM platform.alert_incidents WHERE bank_id=$1", "other-bank-" + bank)
    _run(go)


def test_a_policy_with_zero_days_keeps_everything():
    async def go(pool, bank):
        await _incident(pool, bank, "ancient", "RESOLVED", 3000)
        res = await prune_alert_history(pool, bank, RetentionPolicy(incident_days=0, history_days=0, inbox_days=0, batch_size=100))
        assert res.incidents == 0 and await _count(pool, "alert_incidents", bank) == 1
    _run(go)


def test_the_policy_comes_from_configuration_with_safe_defaults():
    from shared.alerting.retention import load_retention_policy

    class Cfg:
        def __init__(self, **v):
            self.v = v

        async def get(self, key):
            from shared.config.config_service import ConfigKeyNotFoundError
            if key not in self.v:
                raise ConfigKeyNotFoundError(key)
            return self.v[key]
    p = asyncio.run(load_retention_policy(Cfg(**{"alerting.retention_days": 365, "alerting.history_retention_days": "180", "alerting.inbox_retention_days": 7,
                                                 "alerting.prune_batch_size": 50})))
    assert (p.incident_days, p.history_days, p.inbox_days, p.batch_size) == (365, 180, 7, 50)
    d = asyncio.run(load_retention_policy(Cfg(**{"alerting.retention_days": "x", "alerting.prune_batch_size": -3})))
    assert d.incident_days > 0 and d.batch_size >= 1
