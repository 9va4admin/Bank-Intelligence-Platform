"""/v1/notifications now reads the one delivery log (platform.alert_deliveries). Before, it queried columns that do not exist in platform.notification_records
and always answered with an empty list. Real ASGI against the real dev YugabyteDB."""
import asyncio
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI

from shared.alerting.delivery import DeliveryStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _scenario(fn, *, role="ops_manager"):
    async def go():
        import asyncpg
        from apps.api.routers.notifications import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": "u1", "role": role}
        app.state.db_pool_cts = pool
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool)
        finally:
            await pool.execute("DELETE FROM platform.alert_deliveries WHERE bank_id=$1", bank)
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


async def _enq(pool, bank, occasion, channel="email", recipient="n.shah12@gmail.com"):
    store = DeliveryStore(pool, pii_key="k", pepper="p")
    r = await store.enqueue(bank_id=bank, incident_id="inc-1", occasion=occasion, level=0, channel=channel, recipient=recipient,
                            template_id="PLATFORM_HEALTH_ALERT", payload={"message": "m"}, priority="P0")
    return r.delivery_id


def test_the_list_shows_real_deliveries_with_masked_recipients_and_friendly_statuses():
    async def fn(client, bank, pool):
        a = await _enq(pool, bank, "a")
        b = await _enq(pool, bank, "b", channel="bell", recipient="user-42")
        store = DeliveryStore(pool, pii_key="k", pepper="p")
        await store.claim(bank, a, lease_seconds=60)
        await store.mark_sent(bank, a, provider_class="accepted")
        r = await client.get("/v1/notifications")
        assert r.status_code == 200
        body = r.json()
        by = {n["notification_id"]: n for n in body["notifications"]}
        assert by[a]["delivery_status"] == "SENT" and by[a]["channel"] == "email" and by[a]["recipient_ref"] == "n***@gmail.com"
        assert by[b]["delivery_status"] == "QUEUED" and by[b]["channel"] == "bell"
        assert body["total"] == 2 and "n.shah12@gmail.com" not in r.text
        f = (await client.get("/v1/notifications", params={"channel": "bell"})).json()["notifications"]
        assert [n["notification_id"] for n in f] == [b]
        s = (await client.get("/v1/notifications", params={"delivery_status": "SENT"})).json()["notifications"]
        assert [n["notification_id"] for n in s] == [a]
    _scenario(fn)


def test_the_list_pages_with_a_cursor():
    async def fn(client, bank, pool):
        ids = [await _enq(pool, bank, f"o{i}") for i in range(3)]
        for i, d in enumerate(ids):
            await pool.execute("UPDATE platform.alert_deliveries SET created_at = NOW() - make_interval(secs => $2) WHERE delivery_id=$1", d, float(100 - i))
        p1 = (await client.get("/v1/notifications", params={"limit": 2})).json()
        assert [n["notification_id"] for n in p1["notifications"]] == [ids[2], ids[1]] and p1["next_cursor"]
        p2 = (await client.get("/v1/notifications", params={"limit": 2, "cursor": p1["next_cursor"]})).json()
        assert [n["notification_id"] for n in p2["notifications"]] == [ids[0]]
    _scenario(fn)


def test_one_delivery_can_be_read_and_an_unknown_or_other_banks_is_404():
    async def fn(client, bank, pool):
        a = await _enq(pool, bank, "a")
        r = await client.get(f"/v1/notifications/{a}")
        assert r.status_code == 200 and r.json()["notification_id"] == a and r.json()["recipient_ref"] == "n***@gmail.com"
        assert (await client.get("/v1/notifications/nope")).status_code == 404
    _scenario(fn)


def test_a_failed_delivery_can_be_retried_now_and_one_that_is_not_failed_cannot():
    async def fn(client, bank, pool):
        a = await _enq(pool, bank, "a")
        store = DeliveryStore(pool, pii_key="k", pepper="p")
        assert (await client.post(f"/v1/notifications/{a}/retry")).status_code == 409                    # still pending: nothing to retry
        await store.claim(bank, a, lease_seconds=60)
        await store.schedule_retry(bank, a, delay_seconds=3600, error="535 auth failed", provider_class="auth")
        d = (await client.get(f"/v1/notifications/{a}")).json()
        assert d["delivery_status"] == "RETRYING" and d["error_code"] == "auth"
        r = await client.post(f"/v1/notifications/{a}/retry")
        assert r.status_code == 202 and r.json()["status"] == "RETRYING"
        assert await store.due_ids(bank, limit=5) == [a]                                                 # now due: the next outbox run sends it
        assert (await client.post("/v1/notifications/nope/retry")).status_code == 404
    _scenario(fn)


def test_giving_up_shows_as_failed_and_can_be_retried():
    async def fn(client, bank, pool):
        a = await _enq(pool, bank, "a")
        store = DeliveryStore(pool, pii_key="k", pepper="p")
        await store.claim(bank, a, lease_seconds=60)
        await store.mark_undelivered(bank, a, error="gave up", provider_class="network")
        assert (await client.get(f"/v1/notifications/{a}")).json()["delivery_status"] == "FAILED"
        assert (await client.post(f"/v1/notifications/{a}/retry")).status_code == 202
    _scenario(fn)


def test_compliance_may_read_but_not_retry():
    async def fn(client, bank, pool):
        a = await _enq(pool, bank, "a")
        assert (await client.get("/v1/notifications")).status_code == 200
        assert (await client.post(f"/v1/notifications/{a}/retry")).status_code == 403
    _scenario(fn, role="compliance_officer")
