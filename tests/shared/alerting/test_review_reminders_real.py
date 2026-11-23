"""Reminders for overdue post-incident reviews and actions, on the real dev YugabyteDB: each overdue item is reminded at most once per interval, one alert goes out through the
real alert path, and a recovery notice follows when nothing is overdue any more."""
import asyncio
import socket
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg
import pytest

from modules.cts.health.review_reminders import sweep_overdue_reviews
from shared.alerting.reviews import ReviewStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]
NOW = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
GOOD = dict(category="capacity", narrative="Redis ran out of memory after the nightly warm-up and evicted keys.")


class Cfg:
    def __init__(self):
        self.v = {"alerting.pir_due_days_p0": 3, "alerting.pir_due_days_p1": 7, "alerting.effectiveness_days": 30, "alerting.review_min_narrative_chars": 20, "alerting.review_reminder_hours": 24}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def scenario(fn):
    async def go():
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"rm-{uuid.uuid4().hex[:8]}"
        sent = []

        async def send(alert):
            sent.append(alert)
            if alert.event_type == "COMPONENT_DOWN":                                   # what the real path does: open (or keep open) an incident for this component
                await pool.execute("INSERT INTO platform.alert_incidents (incident_id, bank_id, dedup_key, alert_id, component, severity, state, summary) VALUES ($1,$2,$3,'a',$4,'P2','OPEN','s') "
                                   "ON CONFLICT DO NOTHING", uuid.uuid4().hex, alert.bank_id, "component:alert-reviews:down", alert.component)
            else:
                await pool.execute("UPDATE platform.alert_incidents SET state='RESOLVED' WHERE bank_id=$1 AND component=$2 AND state<>'RESOLVED'", alert.bank_id, alert.component)
        try:
            return await fn(pool, bank, send, sent, ReviewStore(pool, due_days={"P0": 3, "P1": 7}, effectiveness_days=30, min_narrative_chars=20))
        finally:
            for t in ("alert_actions", "alert_reviews", "alert_incidents"):
                await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id LIKE 'rm-%'")
            await pool.close()
    return asyncio.run(go())


async def overdue_review(store, bank, incident="i1"):
    await store.ensure_due(bank, incident, "P0", "redis", "k", resolved_at=NOW - timedelta(days=5))


def run(pool, bank, send, now=NOW):
    return sweep_overdue_reviews(pool, bank, Cfg(), send, now=now)


def test_an_overdue_review_is_reminded_once_through_the_alert_path_and_not_again_within_the_interval():
    async def fn(pool, bank, send, sent, store):
        await overdue_review(store, bank)
        first = await run(pool, bank, send)
        assert first.reviews == 1 and first.actions == 0 and len(sent) == 1
        a = sent[0]
        assert a.event_type == "COMPONENT_DOWN" and a.component == "alert-reviews" and a.priority == "P2" and "1" in a.message and "redis" not in a.message
        again = await run(pool, bank, send, NOW + timedelta(hours=5))
        assert again.reviews == 0 and len(sent) == 1                                          # reminded 5 hours ago: not yet
        later = await run(pool, bank, send, NOW + timedelta(hours=25))
        assert later.reviews == 1 and len(sent) == 2                                          # the interval has passed
    scenario(fn)


def test_overdue_actions_count_and_one_alert_covers_reviews_and_actions_together():
    async def fn(pool, bank, send, sent, store):
        await overdue_review(store, bank)
        rid = (await store.list_reviews(bank, now=NOW))[0].review_id
        await store.submit(bank, rid, "ops-1", **GOOD)
        await store.add_action(bank, rid, "ops-1", "preventive", "Add a memory alert", "SRE lead", date(2026, 11, 25), today=date(2026, 11, 20))
        res = await run(pool, bank, send, NOW + timedelta(days=5))                            # the action's due date has passed
        assert res.actions == 1 and len(sent) == 1 and "action" in sent[0].message.lower()
    scenario(fn)


def test_nothing_overdue_sends_nothing_and_items_that_are_done_are_not_reminded():
    async def fn(pool, bank, send, sent, store):
        assert (await run(pool, bank, send)).reviews == 0 and sent == []
        await store.ensure_due(bank, "i2", "P1", "kafka", "k", resolved_at=NOW)                # due in 7 days: not overdue yet
        assert (await run(pool, bank, send)).reviews == 0 and sent == []
    scenario(fn)


def test_when_everything_is_caught_up_one_recovery_notice_follows_the_reminders_and_only_one():
    async def fn(pool, bank, send, sent, store):
        await overdue_review(store, bank)
        await run(pool, bank, send)
        rid = (await store.list_reviews(bank, now=NOW))[0].review_id
        await store.submit(bank, rid, "ops-1", **GOOD)                                        # the review is written up: nothing overdue now
        res = await run(pool, bank, send, NOW + timedelta(hours=1))
        assert res.recovered is True and [a.event_type for a in sent] == ["COMPONENT_DOWN", "COMPONENT_RECOVERED"]
        again = await run(pool, bank, send, NOW + timedelta(hours=2))
        assert again.recovered is False and len(sent) == 2
    scenario(fn)


def test_a_failing_send_is_reported_not_raised_and_the_item_is_reminded_again_next_time():
    async def fn(pool, bank, send, sent, store):
        await overdue_review(store, bank)

        async def broken(alert):
            raise RuntimeError("alert path down")
        res = await run(pool, bank, broken)
        assert res.failed is True
        ok = await run(pool, bank, send, NOW + timedelta(minutes=1))
        assert ok.reviews == 1 and len(sent) == 1                                              # the claim was undone, so the next sweep tries again
    scenario(fn)
