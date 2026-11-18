"""DeliveryEngine on the real dev YugabyteDB outbox with a scripted dispatcher: immediate send, retry with backoff, give up and fall back, never a
duplicate, crash recovery, and an audit record around every attempt."""
import asyncio
import socket
import uuid

import pytest

from shared.alerting.audit import AlertAuditor
from shared.alerting.delivery import DeliveryStore
from shared.alerting.engine import DeliveryEngine, DeliveryPolicy, Target, classify_failure, load_policy

pytestmark = [pytest.mark.integration]
HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark.append(pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable"))


class _Disp:
    def __init__(self, fail=()):
        self.sent, self.fail = [], dict.fromkeys(fail, "535 authentication failed")

    async def send(self, request):
        self.sent.append((request.channel, request.recipient))
        if request.recipient in self.fail or request.channel in self.fail:
            raise RuntimeError(self.fail.get(request.recipient) or self.fail[request.channel])


class _Audit:
    def __init__(self, fail=False):
        self.events, self.fail = [], fail

    def auditor(self):
        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            if self.fail:
                raise ConnectionError("immudb down")
            self.events.append((event_type, payload))
            return f"tx-{len(self.events)}"
        return AlertAuditor(sink)

    def kinds(self):
        return [e[0] for e in self.events]


def _policy(**kw):
    base = dict(max_attempts=3, backoff_seconds=[3600.0], lease_seconds=60.0, fallbacks={"email": ["whatsapp"]}, batch_size=20)
    base.update(kw)
    return DeliveryPolicy(**base)


def _run(fn, *, disp=None, audit=None, policy=None):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=8)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        d, a = disp or _Disp(), audit or _Audit()
        store = DeliveryStore(pool, pii_key="k-not-a-secret", pepper="p-not-a-secret")
        engine = DeliveryEngine(store, d, a.auditor(), policy or _policy())
        try:
            return await fn(engine, store, bank, pool, d, a)
        finally:
            await pool.execute("DELETE FROM platform.alert_deliveries WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def _submit(engine, bank, targets, *, occasion="t1", resolver=None):
    return engine.submit(bank_id=bank, incident_id="inc1", occasion=occasion, targets=targets, template_id="PLATFORM_HEALTH_ALERT",
                         context={"message": "redis down", "component": "redis"}, priority="P0", component="redis",
                         resolve_targets=resolver or (lambda channel: _none()))


async def _none():
    return []


def _status(pool, bank):
    return pool.fetch("SELECT channel, status, attempt, fallback_of FROM platform.alert_deliveries WHERE bank_id=$1 ORDER BY created_at", bank)


def test_classify_failure_names_the_kind_of_problem_without_the_details():
    assert classify_failure("535 5.7.8 authentication failed") == "auth"
    assert classify_failure("[Errno 111] Connection refused") == "network"
    assert classify_failure("timed out") == "network"
    assert classify_failure("550 mailbox unavailable") == "rejected"
    assert classify_failure("something odd") == "error"


def test_a_delivery_is_sent_at_once_and_audited_intent_first_outcome_after():
    async def go(engine, store, bank, pool, disp, audit):
        res = await _submit(engine, bank, [Target("email", "ops@bank.example")])
        assert res.sent == 1 and disp.sent == [("email", "ops@bank.example")]
        assert audit.kinds() == ["ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_SUCCEEDED"]
        assert [(r["status"], r["attempt"]) for r in await _status(pool, bank)] == [("SENT", 1)]
    _run(go)


def test_a_failure_is_queued_for_retry_with_the_configured_delay_and_not_resent_now():
    async def go(engine, store, bank, pool, disp, audit):
        res = await _submit(engine, bank, [Target("email", "ops@bank.example")])
        assert res.sent == 0 and res.retrying == 1 and len(disp.sent) == 1
        rows = await _status(pool, bank)
        assert [(r["status"], r["attempt"]) for r in rows] == [("FAILED", 1)]
        assert audit.kinds() == ["ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_FAILED"]
        again = await engine.process_due(bank, resolve_targets=lambda c: _none())
        assert again.attempted == 0 and len(disp.sent) == 1                     # the delay has not passed
    _run(go, disp=_Disp(fail=["ops@bank.example"]))


def test_a_due_retry_is_sent_and_the_attempt_number_is_recorded():
    async def go(engine, store, bank, pool, disp, audit):
        await _submit(engine, bank, [Target("email", "ops@bank.example")])
        disp.fail.clear()
        await pool.execute("UPDATE platform.alert_deliveries SET next_attempt_at = NOW() - INTERVAL '1 second' WHERE bank_id=$1", bank)
        res = await engine.process_due(bank, resolve_targets=lambda c: _none())
        assert res.attempted == 1 and res.sent == 1
        assert [(r["status"], r["attempt"]) for r in await _status(pool, bank)] == [("SENT", 2)]
        attempts = [p["attempt"] for k, p in audit.events if k.startswith("ALERT_DELIVERY")]
        assert attempts == [1, 2]
    _run(go, disp=_Disp(fail=["ops@bank.example"]))


def test_after_the_last_attempt_it_is_undelivered_and_the_fallback_channel_is_tried():
    async def go(engine, store, bank, pool, disp, audit):
        async def resolver(channel):
            return [Target("whatsapp", "+919800000001")] if channel == "whatsapp" else []
        await _submit(engine, bank, [Target("email", "ops@bank.example")], resolver=resolver)
        for _ in range(2):                                                      # attempts 2 and 3
            await pool.execute("UPDATE platform.alert_deliveries SET next_attempt_at = NOW() - INTERVAL '1 second' WHERE bank_id=$1 AND status='FAILED'", bank)
            await engine.process_due(bank, resolve_targets=resolver)
        rows = await _status(pool, bank)
        assert [(r["channel"], r["status"]) for r in rows] == [("email", "UNDELIVERED"), ("whatsapp", "SENT")]
        assert rows[1]["fallback_of"] is not None
        assert ("whatsapp", "+919800000001") in disp.sent and "ALERT_ESCALATED" in audit.kinds()
    _run(go, disp=_Disp(fail=["ops@bank.example"]))


def test_with_no_fallback_target_it_ends_undelivered_and_says_so():
    async def go(engine, store, bank, pool, disp, audit):
        for _ in range(3):
            await pool.execute("UPDATE platform.alert_deliveries SET next_attempt_at = NOW() - INTERVAL '1 second' WHERE bank_id=$1 AND status='FAILED'", bank)
            await (_submit(engine, bank, [Target("email", "ops@bank.example")]) if _ == 0 else engine.process_due(bank, resolve_targets=lambda c: _none()))
        res = await pool.fetch("SELECT status FROM platform.alert_deliveries WHERE bank_id=$1", bank)
        assert [r["status"] for r in res] == ["UNDELIVERED"]
    _run(go, disp=_Disp(fail=["ops@bank.example"]))


def test_submitting_the_same_notification_twice_sends_it_once():
    async def go(engine, store, bank, pool, disp, audit):
        await _submit(engine, bank, [Target("email", "ops@bank.example")])
        await _submit(engine, bank, [Target("email", "ops@bank.example")])        # a Temporal activity retry
        assert disp.sent == [("email", "ops@bank.example")]
        await _submit(engine, bank, [Target("email", "ops@bank.example")], occasion="t2")      # a genuine reminder is a new occasion
        assert len(disp.sent) == 2
    _run(go)


def test_a_sender_that_died_mid_send_is_recovered_when_its_lease_expires():
    async def go(engine, store, bank, pool, disp, audit):
        r = await store.enqueue(bank_id=bank, incident_id="inc1", occasion="t1", level=0, channel="email", recipient="ops@bank.example",
                                template_id="PLATFORM_HEALTH_ALERT", payload={"message": "m", "component": "redis"}, priority="P0")
        await store.claim(bank, r.delivery_id, lease_seconds=60)                  # the "dead" worker took it and vanished
        assert (await engine.process_due(bank, resolve_targets=lambda c: _none())).attempted == 0       # its lease is still valid
        await pool.execute("UPDATE platform.alert_deliveries SET claimed_until = NOW() - INTERVAL '1 second' WHERE bank_id=$1", bank)
        res = await engine.process_due(bank, resolve_targets=lambda c: _none())
        assert res.attempted == 1 and res.sent == 1
    _run(go)


def test_an_audit_outage_never_stops_a_send():
    async def go(engine, store, bank, pool, disp, audit):
        res = await _submit(engine, bank, [Target("email", "ops@bank.example")])
        assert res.sent == 1 and disp.sent
    _run(go, audit=_Audit(fail=True))


def test_one_target_failing_does_not_stop_the_others():
    async def go(engine, store, bank, pool, disp, audit):
        res = await _submit(engine, bank, [Target("email", "bad@bank.example"), Target("email", "ok@bank.example"), Target("whatsapp", "+919800000001")])
        assert res.sent == 2 and res.retrying == 1
    _run(go, disp=_Disp(fail=["bad@bank.example"]))


def test_the_policy_comes_from_configuration_and_bad_values_fall_back_to_safe_defaults():
    class Cfg:
        def __init__(self, **v):
            self.v = v

        async def get(self, key):
            from shared.config.config_service import ConfigKeyNotFoundError
            if key not in self.v:
                raise ConfigKeyNotFoundError(key)
            return self.v[key]
    p = asyncio.run(load_policy(Cfg(**{"alerting.delivery_max_attempts": 5, "alerting.delivery_backoff_seconds": "[10, 20]",
                                       "alerting.delivery_fallbacks": '{"email": ["whatsapp", "bell"]}', "alerting.delivery_lease_seconds": 30})))
    assert (p.max_attempts, p.backoff_seconds, p.lease_seconds) == (5, [10.0, 20.0], 30.0) and p.fallbacks == {"email": ["whatsapp", "bell"]}
    bad = asyncio.run(load_policy(Cfg(**{"alerting.delivery_backoff_seconds": "{nope", "alerting.delivery_fallbacks": "[1]", "alerting.delivery_max_attempts": "x"})))
    assert bad.max_attempts >= 1 and bad.backoff_seconds and isinstance(bad.fallbacks, dict)


def test_an_event_nobody_can_be_found_for_is_recorded_as_undelivered_and_audited_never_dropped():
    async def go(engine, store, bank, pool, disp, audit):
        kw = dict(bank_id=bank, incident_id="n1", occasion="n1", channel="email", template_id="t", context={"message": "m"}, priority="P1",
                  reason="RECIPIENT_UNRESOLVED")
        await engine.record_undeliverable(**kw)
        await engine.record_undeliverable(**kw)                                        # a Kafka redelivery: still one row
        rows = await pool.fetch("SELECT channel, status, error, provider_class FROM platform.alert_deliveries WHERE bank_id=$1", bank)
        assert [(r["channel"], r["status"], r["error"], r["provider_class"]) for r in rows] == [("email", "UNDELIVERED", "RECIPIENT_UNRESOLVED", "unresolved")]
        assert disp.sent == [] and audit.kinds() == ["ALERT_DELIVERY_FAILED"]
    _run(go)
