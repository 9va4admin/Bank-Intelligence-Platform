"""When a P0 or P1 incident is resolved, a post-incident review falls due; lower severities get none; a failure creating it never breaks the alert path. Real dev YugabyteDB."""
import asyncio
import socket
import uuid

import asyncpg
import pytest

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput, record_alert_incident
from shared.alerting.incidents import _COMPONENT_EVENTS, _RECOVERY_EVENTS

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]
DOWN = next(e for e in sorted(_COMPONENT_EVENTS) if e not in _RECOVERY_EVENTS and "SLOW" not in e.upper())
UP = sorted(_RECOVERY_EVENTS)[0]


def scenario(fn):
    async def go():
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"rr-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(pool, bank)
        finally:
            for t in ("alert_reviews", "alert_incidents"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id LIKE 'rr-%'")
            await pool.close()
    return asyncio.run(go())


def alert(bank, event, priority, component="redis"):
    return DispatchAlertInput(bank_id=bank, event_type=event, component=component, message="m", severity="CRITICAL", priority=priority)


def test_resolving_a_p0_or_p1_incident_makes_a_review_due_and_a_p2_does_not():
    async def fn(pool, bank):
        for component, priority in (("redis", "P0"), ("kafka", "P1"), ("cbs", "P2")):
            await record_alert_incident(alert(bank, DOWN, priority, component), db_pool=pool)
            res = await record_alert_incident(alert(bank, UP, priority, component), db_pool=pool)
            assert res.resolved is True
        rows = await pool.fetch("SELECT component, severity, status FROM platform.alert_reviews WHERE bank_id=$1 ORDER BY component", bank)
        assert [(r["component"], r["severity"], r["status"]) for r in rows] == [("kafka", "P1", "DUE"), ("redis", "P0", "DUE")]
    scenario(fn)


def test_a_failure_creating_the_review_never_breaks_the_incident_path():
    async def fn(pool, bank):
        await record_alert_incident(alert(bank, DOWN, "P0"), db_pool=pool)
        await pool.execute("ALTER TABLE platform.alert_reviews RENAME TO alert_reviews_off")
        try:
            res = await record_alert_incident(alert(bank, UP, "P0"), db_pool=pool)
            assert res.resolved is True and res.incident_id
        finally:
            await pool.execute("ALTER TABLE platform.alert_reviews_off RENAME TO alert_reviews")
    scenario(fn)
