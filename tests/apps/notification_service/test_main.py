"""
Tests for apps/notification_service/main.py.

The service drains platform.notifications (security violations, config changes, MCP events, manual sends ...) and delivers every event through the
same delivery engine and outbox as the alert system, so there is ONE delivery log (platform.alert_deliveries), one retry policy, one audit trail.

Covers: who an event is for (resolve_targets), the consume loop (submit, unresolved recipients, failure isolation, other banks, bad JSON), and the probes.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from apps.notification_service.main import SERVICE_NAME, _consume_loop, app, resolve_targets
from shared.alerting.engine import SubmitResult, Target


class _Pool:
    """Answers the role lookup (bell users of a role)."""
    def __init__(self, users=("u-a", "u-b")):
        self.users, self.asked = list(users), []

    async def fetch(self, sql, bank, roles, limit, days=0):
        self.asked.append((bank, roles))
        return [{"user_id": u} for u in self.users][:limit]


class _Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


async def _targets(event, pool=None, cfg=None):
    return await resolve_targets(event, pool=pool, config_service=cfg or _Cfg(), bank_id="test-bank")


# ── who an event is for ──────────────────────────────────────────────────────

class TestResolveTargets:
    @pytest.mark.asyncio
    async def test_a_direct_address_is_used_on_the_events_channel(self):
        assert await _targets({"recipient": "admin@x.bank", "channel": "email"}) == [Target("email", "admin@x.bank")]
        assert await _targets({"recipient": "+919800000001", "channel": "whatsapp"}) == [Target("whatsapp", "+919800000001")]

    @pytest.mark.asyncio
    async def test_a_reference_that_is_an_email_address_is_delivered_by_email(self):
        assert await _targets({"recipient_ref": "a@b.in"}) == [Target("email", "a@b.in")]

    @pytest.mark.asyncio
    async def test_a_role_reaches_every_active_user_of_that_role_on_the_bell(self):
        pool = _Pool(["u1", "u2"])
        got = await _targets({"recipient_role": "bank_it_admin"}, pool=pool)
        assert got == [Target("bell", "u1"), Target("bell", "u2")] and pool.asked[0] == ("test-bank", ["bank_it_admin"])

    @pytest.mark.asyncio
    async def test_an_opaque_user_id_is_a_bell_recipient(self):
        assert await _targets({"recipient_ref": "usr-ops-kbl"}) == [Target("bell", "usr-ops-kbl")]

    @pytest.mark.asyncio
    async def test_nothing_to_go_on_is_empty_and_a_role_without_a_database_is_empty(self):
        assert await _targets({}) == []
        assert await _targets({"recipient_role": "bank_it_admin"}, pool=None) == []

    @pytest.mark.asyncio
    async def test_an_unknown_channel_defaults_to_email(self):
        assert await _targets({"recipient": "a@b.in", "channel": "carrier-pigeon"}) == [Target("email", "a@b.in")]


# ── the consume loop ─────────────────────────────────────────────────────────

def _msg(event, offset=0):
    m = MagicMock()
    m.value = json.dumps(event).encode()
    m.offset = offset
    return m


class _Consumer:
    def __init__(self, *msgs):
        self._msgs, self.commit = list(msgs), AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._msgs:
            raise StopAsyncIteration
        return self._msgs.pop(0)


class _Engine:
    def __init__(self, fail=False):
        self.submits, self.undeliverable, self.fail = [], [], fail

    async def submit(self, **kw):
        if self.fail:
            raise RuntimeError("engine down")
        self.submits.append(kw)
        return SubmitResult(sent=1)

    async def record_undeliverable(self, **kw):
        self.undeliverable.append(kw)


def _event(**over):
    base = {"notification_id": str(uuid.uuid4()), "bank_id": "test-bank", "channel": "email", "recipient": "admin@test.bank",
            "template_id": "cts.human_review_escalated", "context": {"instrument_id": "instr-001"}, "priority": "P1", "module": "CTS",
            "event_type": "HUMAN_REVIEW_ESCALATED"}
    base.update(over)
    return base


async def _run(consumer, engine, pool=None):
    await _consume_loop(consumer, engine, pool, "test-bank", _Cfg())


@pytest.mark.asyncio
async def test_an_event_is_submitted_to_the_engine_with_its_id_as_incident_and_occasion_and_the_offset_is_committed():
    ev = _event()
    engine, consumer = _Engine(), _Consumer(_msg(ev, 10))
    await _run(consumer, engine)
    kw = engine.submits[0]
    assert kw["bank_id"] == "test-bank" and kw["incident_id"] == ev["notification_id"] and kw["occasion"] == ev["notification_id"]
    assert kw["targets"] == [Target("email", "admin@test.bank")] and kw["template_id"] == "cts.human_review_escalated" and kw["priority"] == "P1"
    assert kw["context"]["instrument_id"] == "instr-001" and kw["context"]["bank_id"] == "test-bank" and kw["context"]["event_type"] == "HUMAN_REVIEW_ESCALATED"
    consumer.commit.assert_awaited()


@pytest.mark.asyncio
async def test_the_bell_gets_readable_text_even_when_the_event_has_no_message():
    engine = _Engine()
    await _run(_Consumer(_msg(_event(context={}))), engine)
    ctx = engine.submits[0]["context"]
    assert ctx["message"] and ctx["component"]


@pytest.mark.asyncio
async def test_an_events_own_message_is_kept():
    engine = _Engine()
    await _run(_Consumer(_msg(_event(message="Config change awaiting approval"))), engine)
    assert engine.submits[0]["context"]["message"] == "Config change awaiting approval"


@pytest.mark.asyncio
async def test_a_role_event_goes_to_the_bell_users_of_that_role():
    engine = _Engine()
    await _run(_Consumer(_msg(_event(recipient=None, recipient_role="bank_it_admin"))), engine, pool=_Pool(["u1"]))
    assert engine.submits[0]["targets"] == [Target("bell", "u1")]


@pytest.mark.asyncio
async def test_an_event_nobody_can_be_found_for_is_recorded_as_undeliverable_not_silently_dropped():
    engine, consumer = _Engine(), _Consumer(_msg(_event(recipient=None)))
    await _run(consumer, engine)
    assert engine.submits == [] and len(engine.undeliverable) == 1
    assert engine.undeliverable[0]["reason"] and engine.undeliverable[0]["incident_id"]
    consumer.commit.assert_awaited()


@pytest.mark.asyncio
async def test_one_failing_event_never_stops_the_loop():
    engine, consumer = _Engine(fail=True), _Consumer(_msg(_event(), 1), _msg(_event(), 2))
    await _run(consumer, engine)
    assert consumer.commit.await_count == 2


@pytest.mark.asyncio
async def test_other_banks_and_bad_json_are_skipped_and_committed():
    bad = MagicMock()
    bad.value, bad.offset = b"not-json{", 3
    engine, consumer = _Engine(), _Consumer(bad, _msg(_event(bank_id="another-bank"), 4))
    await _run(consumer, engine)
    assert engine.submits == [] and consumer.commit.await_count == 2


# ── health probes ────────────────────────────────────────────────────────────

class TestHealthProbes:
    def test_liveness_always_200(self):
        resp = TestClient(app).get("/health/live")
        assert resp.status_code == 200 and resp.json()["service"] == SERVICE_NAME

    def test_readiness_degraded_when_no_consumer(self):
        resp = TestClient(app).get("/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded" and "kafka_consumer" in data["checks"] and "engine" in data["checks"]
