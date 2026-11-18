"""Alert silences on the real dev YugabyteDB: create with rules (length, reason, P0 only when allowed), match a component and priority at a moment, cancel, list, audit."""
import asyncio
import socket
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from shared.alerting.audit import AlertAuditor
from shared.alerting.silences import SilenceInvalid, SilenceStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


def db(fn):
    def wrapper():
        async def go():
            pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
            bank = f"sl-{uuid.uuid4().hex[:8]}"
            events = []

            async def sink(event_type, bank_id, entity_id, actor_id, payload):
                events.append((event_type, entity_id, actor_id, payload))
                return "tx"
            store = SilenceStore(pool, max_hours=24, allow_p0=False, min_reason_chars=5, auditor=AlertAuditor(sink))
            try:
                await fn(store, pool, bank, events)
            finally:
                await pool.execute("DELETE FROM platform.alert_silences WHERE bank_id LIKE 'sl-%'")
                await pool.close()
        asyncio.run(go())
    return wrapper


def hours(n):
    return NOW + timedelta(hours=n)


@db
async def test_a_silence_matches_its_component_and_priorities_only_while_it_is_in_force(store, pool, bank, events):
    s = await store.create(bank, "redis", ["P1", "P2"], hours(0), hours(2), "Redis maintenance", "admin-1")
    assert await store.is_silenced(bank, "redis", "P1", NOW + timedelta(minutes=30)) == s.silence_id
    assert await store.is_silenced(bank, "kafka", "P1", NOW + timedelta(minutes=30)) is None             # another component
    assert await store.is_silenced(bank, "redis", "P0", NOW + timedelta(minutes=30)) is None             # a priority it does not cover
    assert await store.is_silenced(bank, "redis", "P1", NOW - timedelta(minutes=1)) is None              # not started
    assert await store.is_silenced(bank, "redis", "P1", hours(3)) is None                                # over
    assert await store.is_silenced(bank + "-other", "redis", "P1", NOW + timedelta(minutes=30)) is None


@db
async def test_a_silence_with_no_component_covers_every_component(store, pool, bank, events):
    s = await store.create(bank, "", ["P2", "P3"], hours(0), hours(1), "Planned release", "admin-1")
    assert await store.is_silenced(bank, "anything", "P3", NOW + timedelta(minutes=5)) == s.silence_id


@db
async def test_p0_cannot_be_silenced_unless_the_bank_allows_it_and_long_or_unexplained_silences_are_refused(store, pool, bank, events):
    for args, code in (((["P0"], hours(0), hours(1), "Maintenance window"), "p0_not_allowed"), ((["P1"], hours(0), hours(30), "Maintenance window"), "too_long"),
                       ((["P1"], hours(0), hours(1), "ok"), "reason_too_short"), ((["P1"], hours(2), hours(1), "Maintenance window"), "ends_before_start"),
                       (([], hours(0), hours(1), "Maintenance window"), "no_priority"), ((["P9"], hours(0), hours(1), "Maintenance window"), "unknown_priority")):
        with pytest.raises(SilenceInvalid) as e:
            await store.create(bank, "redis", *args, "admin-1")
        assert e.value.code == code, (args, e.value.code)
    allowing = SilenceStore(pool, max_hours=24, allow_p0=True, min_reason_chars=5)
    assert (await allowing.create(bank, "redis", ["P0"], hours(0), hours(1), "Planned failover test", "admin-1")).priorities == ["P0"]


@db
async def test_a_silence_can_be_cancelled_early_and_then_no_longer_matches(store, pool, bank, events):
    s = await store.create(bank, "redis", ["P1"], hours(0), hours(5), "Redis maintenance", "admin-1")
    assert await store.cancel(bank, s.silence_id, "admin-2", at=NOW + timedelta(minutes=10)) is True
    assert await store.is_silenced(bank, "redis", "P1", NOW + timedelta(minutes=20)) is None
    assert await store.cancel(bank, s.silence_id, "admin-2") is False                                   # already cancelled
    assert await store.cancel(bank, "nope", "admin-2") is False


@db
async def test_listing_separates_in_force_upcoming_and_recent_and_every_change_is_audited_without_the_reason_text(store, pool, bank, events):
    a = await store.create(bank, "redis", ["P1"], hours(-1), hours(1), "Redis maintenance", "admin-1")
    b = await store.create(bank, "kafka", ["P2"], hours(5), hours(6), "Kafka upgrade tonight", "admin-1")
    old = await store.create(bank, "cbs", ["P3"], hours(-10), hours(-9), "Earlier work done", "admin-1")
    listing = await store.listing(bank, NOW)
    assert [x.silence_id for x in listing.in_force] == [a.silence_id] and [x.silence_id for x in listing.upcoming] == [b.silence_id] and [x.silence_id for x in listing.recent] == [old.silence_id]
    await store.cancel(bank, b.silence_id, "admin-2")
    kinds = [e[0] for e in events]
    assert kinds.count("ALERT_SILENCE_CHANGED") == 4
    assert "maintenance" not in str(events).lower() and {e[2] for e in events} == {"admin-1", "admin-2"}
