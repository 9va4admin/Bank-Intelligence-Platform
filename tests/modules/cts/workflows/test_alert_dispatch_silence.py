"""A silence in force holds back the notification (and says so in the audit trail); anything not covered, and any failure to look it up, still sends. Real dev YugabyteDB."""
import asyncio
import socket
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput, dispatch_platform_alert
from shared.alerting.audit import AlertAuditor
from shared.alerting.silences import SilenceStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        values = {"alerts.email_recipients": "ops@bank.example"}
        if key not in values:
            raise ConfigKeyNotFoundError(key)
        return values[key]


class Dispatcher:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)


def scenario(fn):
    async def go():
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"sd-{uuid.uuid4().hex[:8]}"
        events, disp = [], Dispatcher()

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, entity_id, payload))
            return "tx"
        try:
            now = datetime.now(timezone.utc)
            await SilenceStore(pool, max_hours=24, allow_p0=False, min_reason_chars=5).create(bank, "redis", ["P1", "P2"], now - timedelta(minutes=5), now + timedelta(hours=1), "Redis maintenance", "admin-1")
            return await fn(pool, bank, disp, events, AlertAuditor(sink))
        finally:
            await pool.execute("DELETE FROM platform.alert_silences WHERE bank_id LIKE 'sd-%'")
            await pool.close()
    return asyncio.run(go())


def alert(bank, component="redis", priority="P1", template="PLATFORM_HEALTH_ALERT"):
    return DispatchAlertInput(bank_id=bank, event_type="COMPONENT_DOWN", component=component, message="m", severity="WARN", priority=priority, incident_id="inc-1", template=template)


def test_a_covered_alert_is_held_back_and_the_audit_trail_says_which_silence_held_it():
    async def fn(pool, bank, disp, events, auditor):
        r = await dispatch_platform_alert(alert(bank), dispatcher=disp, config_service=Cfg(), alert_auditor=auditor, db_pool=pool)
        assert r.sent is False and r.suppressed is True and disp.sent == []
        held = [e for e in events if e[0] == "ALERT_SUPPRESSED"]
        assert held and held[0][1] == "inc-1" and held[0][2]["component"] == "redis" and held[0][2]["silence_id"]
    scenario(fn)


def test_a_recovery_notice_for_a_silenced_component_is_held_back_too():
    async def fn(pool, bank, disp, events, auditor):
        r = await dispatch_platform_alert(alert(bank, template="PLATFORM_HEALTH_RECOVERED"), dispatcher=disp, config_service=Cfg(), alert_auditor=auditor, db_pool=pool)
        assert r.suppressed is True and disp.sent == []
    scenario(fn)


def test_a_critical_alert_another_component_or_a_priority_not_covered_still_sends():
    async def fn(pool, bank, disp, events, auditor):
        for a in (alert(bank, priority="P0"), alert(bank, component="kafka"), alert(bank, priority="P3")):
            r = await dispatch_platform_alert(a, dispatcher=disp, config_service=Cfg(), alert_auditor=auditor, db_pool=pool)
            assert r.suppressed is False and r.sent is True
        assert len(disp.sent) == 3
    scenario(fn)


def test_a_failed_silence_lookup_never_stops_an_alert_and_no_pool_means_no_silences():
    async def fn(pool, bank, disp, events, auditor):
        class Broken:
            async def fetchval(self, *a, **k):
                raise RuntimeError("db down")
        r = await dispatch_platform_alert(alert(bank), dispatcher=disp, config_service=Cfg(), alert_auditor=auditor, db_pool=Broken())
        assert r.sent is True and r.suppressed is False
        r = await dispatch_platform_alert(alert(bank), dispatcher=disp, config_service=Cfg(), alert_auditor=auditor, db_pool=None)
        assert r.sent is True
    scenario(fn)
