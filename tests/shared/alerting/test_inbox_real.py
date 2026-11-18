"""InboxStore (platform.user_notifications) on the real dev YugabyteDB: the bell's data. Every read and write is scoped to bank AND user."""
import asyncio
import socket
import uuid

import pytest

from shared.alerting.inbox import InboxStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(InboxStore(pool), bank, pool)
        finally:
            await pool.execute("DELETE FROM platform.user_notifications WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def _add(store, bank, user="u1", severity="P0", title="t", **kw):
    return store.add(bank_id=bank, user_id=user, severity=severity, title=title, body=kw.pop("body", "b"), **kw)


def test_a_notification_is_unread_until_read_and_counted_by_severity():
    async def go(store, bank, pool):
        a = await _add(store, bank, severity="P0")
        await _add(store, bank, severity="P1")
        await _add(store, bank, severity="P1")
        assert await store.unread_counts(bank, "u1") == {"total": 3, "P0": 1, "P1": 2, "P2": 0, "P3": 0}
        assert await store.mark_read(bank, "u1", a) is True
        assert (await store.unread_counts(bank, "u1"))["total"] == 2
        assert await store.mark_read(bank, "u1", a) is False                  # already read: nothing changes
    _run(go)


def test_a_user_sees_only_their_own_and_only_in_their_bank():
    async def go(store, bank, pool):
        mine = await _add(store, bank, user="u1")
        theirs = await _add(store, bank, user="u2")
        assert [r["notification_id"] for r in (await store.list_for_user(bank, "u1", limit=10)).items] == [mine]
        assert (await store.list_for_user("another-bank", "u1", limit=10)).items == []
        assert await store.mark_read(bank, "u1", theirs) is False             # cannot touch someone else's
        assert await store.unread_counts(bank, "u2") == {"total": 1, "P0": 1, "P1": 0, "P2": 0, "P3": 0}
    _run(go)


def test_listing_is_newest_first_pageable_and_can_show_unread_only():
    async def go(store, bank, pool):
        ids = []
        for i in range(5):
            n = await _add(store, bank, title=f"n{i}")
            await pool.execute("UPDATE platform.user_notifications SET created_at = NOW() - make_interval(secs => $2) WHERE notification_id=$1", n, float(100 - i))
            ids.append(n)
        await store.mark_read(bank, "u1", ids[4])
        p1 = await store.list_for_user(bank, "u1", limit=2)
        assert [r["title"] for r in p1.items] == ["n4", "n3"] and p1.next_cursor
        p2 = await store.list_for_user(bank, "u1", limit=2, cursor=p1.next_cursor)
        assert [r["title"] for r in p2.items] == ["n2", "n1"]
        unread = await store.list_for_user(bank, "u1", limit=10, unread_only=True)
        assert [r["title"] for r in unread.items] == ["n3", "n2", "n1", "n0"]
    _run(go)


def test_read_all_marks_only_this_users_and_reports_how_many():
    async def go(store, bank, pool):
        for _ in range(3):
            await _add(store, bank, user="u1")
        await _add(store, bank, user="u2")
        assert await store.mark_all_read(bank, "u1") == 3
        assert (await store.unread_counts(bank, "u1"))["total"] == 0 and (await store.unread_counts(bank, "u2"))["total"] == 1
        assert await store.mark_all_read(bank, "u1") == 0
    _run(go)


def test_acknowledging_a_notification_returns_its_incident_and_marks_it_read():
    async def go(store, bank, pool):
        n = await _add(store, bank, incident_id="inc-5")
        got = await store.acknowledge(bank, "u1", n)
        assert got == {"incident_id": "inc-5"}
        row = (await store.list_for_user(bank, "u1", limit=5)).items[0]
        assert row["acked_at"] is not None and row["read_at"] is not None
        assert await store.acknowledge(bank, "u1", n) is None                 # second time: already acknowledged
        assert await store.acknowledge(bank, "u2", n) is None                 # not theirs
    _run(go)


def test_unacknowledged_p0_are_listed_for_the_pinned_banner():
    async def go(store, bank, pool):
        p0 = await _add(store, bank, severity="P0", title="down")
        await _add(store, bank, severity="P1")
        done = await _add(store, bank, severity="P0", title="done")
        await store.acknowledge(bank, "u1", done)
        pinned = await store.pinned(bank, "u1", limit=5)
        assert [r["notification_id"] for r in pinned] == [p0]
    _run(go)
