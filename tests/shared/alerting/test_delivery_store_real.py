"""DeliveryStore (the outbox) against the real dev YugabyteDB: idempotent queueing, recipients kept encrypted, atomic claims with a lease, retry
scheduling and final states."""
import asyncio
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from shared.alerting.delivery import DeliveryStore

ROOT = Path(__file__).resolve().parents[3]
HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]

PII_KEY, PEPPER = "test-pii-key-not-a-secret", "test-pepper-not-a-secret"


@pytest.fixture(scope="module", autouse=True)
def migrated():
    env = {**os.environ, "PLATFORM_DB_URL": f"postgresql+asyncpg://yugabyte:yugabyte@{HOST}:{PORT}/yugabyte"}
    r = subprocess.run([sys.executable, "-m", "alembic", "-c", "infra/migrations/platform/alembic.ini", "upgrade", "head"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=8)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(DeliveryStore(pool, pii_key=PII_KEY, pepper=PEPPER), bank, pool)
        finally:
            await pool.execute("DELETE FROM platform.alert_deliveries WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def _enq(store, bank, *, occasion="t1", recipient="n.shah12@gmail.com", channel="email", level=0, incident="inc1", **kw):
    return store.enqueue(bank_id=bank, incident_id=incident, occasion=occasion, level=level, channel=channel, recipient=recipient,
                         template_id="PLATFORM_HEALTH_ALERT", payload={"message": "redis down", "component": "redis"}, priority="P0", **kw)


def test_the_recipient_is_stored_masked_and_encrypted_never_in_the_clear():
    async def go(store, bank, pool):
        r = await _enq(store, bank)
        row = await pool.fetchrow("SELECT * FROM platform.alert_deliveries WHERE delivery_id=$1", r.delivery_id)
        assert row["recipient_ref"] == "n***@gmail.com" and row["recipient_enc"] is not None
        blob = " ".join(str(v) for v in row.values()) + bytes(row["recipient_enc"]).decode("latin-1")
        assert "n.shah12@gmail.com" not in blob and "shah12" not in blob
    _run(go)


def test_the_same_notification_is_queued_once_and_a_new_occasion_queues_again():
    async def go(store, bank, pool):
        a = await _enq(store, bank)
        b = await _enq(store, bank)
        c = await _enq(store, bank, occasion="t2")
        d = await _enq(store, bank, recipient="other@bank.example")
        assert a.created and not b.created and a.delivery_id == b.delivery_id
        assert c.created and d.created and len({a.delivery_id, c.delivery_id, d.delivery_id}) == 3
    _run(go)


def test_claiming_returns_the_decrypted_recipient_and_holds_a_lease():
    async def go(store, bank, pool):
        r = await _enq(store, bank)
        row = await store.claim(bank, r.delivery_id, lease_seconds=60)
        assert row.recipient == "n.shah12@gmail.com" and row.attempt == 1 and row.channel == "email" and row.payload["component"] == "redis"
        assert await store.claim(bank, r.delivery_id, lease_seconds=60) is None            # someone is already sending it
        await pool.execute("UPDATE platform.alert_deliveries SET claimed_until = NOW() - INTERVAL '1 second' WHERE delivery_id=$1", r.delivery_id)
        again = await store.claim(bank, r.delivery_id, lease_seconds=60)                    # the sender died: the lease expired and it is reclaimed
        assert again is not None and again.attempt == 2
    _run(go)


def test_ten_simultaneous_claims_have_exactly_one_winner():
    async def go(store, bank, pool):
        r = await _enq(store, bank)
        results = await asyncio.gather(*[store.claim(bank, r.delivery_id, lease_seconds=60) for _ in range(10)])
        assert sum(1 for x in results if x is not None) == 1
    _run(go)


def test_a_sent_delivery_is_final_and_cannot_be_claimed_again():
    async def go(store, bank, pool):
        r = await _enq(store, bank)
        await store.claim(bank, r.delivery_id, lease_seconds=60)
        await store.mark_sent(bank, r.delivery_id, provider_class="accepted")
        row = await pool.fetchrow("SELECT status, completed_at, provider_class FROM platform.alert_deliveries WHERE delivery_id=$1", r.delivery_id)
        assert row["status"] == "SENT" and row["completed_at"] is not None and row["provider_class"] == "accepted"
        assert await store.claim(bank, r.delivery_id, lease_seconds=60) is None
    _run(go)


def test_a_failed_attempt_is_retried_only_after_its_delay_and_due_ones_are_found():
    async def go(store, bank, pool):
        r = await _enq(store, bank)
        await store.claim(bank, r.delivery_id, lease_seconds=60)
        await store.schedule_retry(bank, r.delivery_id, delay_seconds=3600, error="535 auth failed", provider_class="auth")
        assert await store.claim(bank, r.delivery_id, lease_seconds=60) is None            # not due yet
        assert await store.due_ids(bank, limit=10) == []
        await pool.execute("UPDATE platform.alert_deliveries SET next_attempt_at = NOW() - INTERVAL '1 second' WHERE delivery_id=$1", r.delivery_id)
        assert await store.due_ids(bank, limit=10) == [r.delivery_id]
        row = await store.claim(bank, r.delivery_id, lease_seconds=60)
        assert row is not None and row.attempt == 2
    _run(go)


def test_giving_up_marks_it_undelivered_and_it_is_never_retried():
    async def go(store, bank, pool):
        r = await _enq(store, bank)
        await store.claim(bank, r.delivery_id, lease_seconds=60)
        await store.mark_undelivered(bank, r.delivery_id, error="gave up")
        assert (await pool.fetchval("SELECT status FROM platform.alert_deliveries WHERE delivery_id=$1", r.delivery_id)) == "UNDELIVERED"
        assert await store.claim(bank, r.delivery_id, lease_seconds=60) is None and await store.due_ids(bank, limit=10) == []
    _run(go)


def test_the_incident_view_lists_masked_deliveries_only_for_that_bank_and_incident():
    async def go(store, bank, pool):
        await _enq(store, bank)
        await _enq(store, bank, channel="whatsapp", recipient="+919800000001")
        await _enq(store, bank, incident="other")
        rows = await store.list_for_incident(bank, "inc1", limit=50)
        assert {r["channel"] for r in rows} == {"email", "whatsapp"}
        assert {r["recipient_ref"] for r in rows} == {"n***@gmail.com", "******0001"}
        assert await store.list_for_incident("another-bank", "inc1", limit=50) == []
    _run(go)
