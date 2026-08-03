"""
Tests for apps/notification_service/main.py.

Covers:
  - _resolve_recipient: all four resolution paths
  - _record_delivery: DB write + graceful degradation when pool=None
  - _consume_loop: dispatch, DB record, commit per message; failure isolation
  - readiness probe: operational / degraded states
  - liveness probe: always 200
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from apps.notification_service.main import (
    _record_delivery,
    _resolve_recipient,
    _consume_loop,
    app,
    SERVICE_NAME,
)
from shared.notifications.dispatcher import NotificationDispatcher


# ── _resolve_recipient ────────────────────────────────────────────────────────

class TestResolveRecipient:
    def test_direct_recipient_field(self):
        event = {"recipient": "ops@bank.com", "channel": "email"}
        addr, channel = _resolve_recipient(event)
        assert addr == "ops@bank.com"
        assert channel == "email"

    def test_recipient_ref_with_at_sign(self):
        event = {"recipient_ref": "it-admin@saraswat.bank", "channel": "email"}
        addr, channel = _resolve_recipient(event)
        assert addr == "it-admin@saraswat.bank"
        assert channel == "email"

    def test_recipient_role_returns_none(self):
        event = {
            "recipient_role": "bank_it_admin",
            "channel": "whatsapp",
        }
        addr, channel = _resolve_recipient(event)
        assert addr is None
        assert channel == "whatsapp"

    def test_opaque_user_id_returns_none(self):
        event = {"recipient_ref": "user-uuid-without-at-sign", "channel": "email"}
        addr, channel = _resolve_recipient(event)
        assert addr is None

    def test_no_recipient_returns_none(self):
        event = {"channel": "email", "template_id": "cts.alert"}
        addr, channel = _resolve_recipient(event)
        assert addr is None

    def test_unknown_channel_defaults_to_email(self):
        event = {"recipient": "x@y.com", "channel": "sms"}  # sms not supported
        addr, channel = _resolve_recipient(event)
        assert channel == "email"

    def test_whatsapp_channel_preserved(self):
        event = {"recipient": "+919876543210", "channel": "whatsapp"}
        addr, channel = _resolve_recipient(event)
        assert channel == "whatsapp"


# ── _record_delivery ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_delivery_no_pool_does_not_raise():
    # Must not raise when DB pool is None
    await _record_delivery(
        pool=None,
        notification_id=str(uuid.uuid4()),
        bank_id="test-bank",
        channel="email",
        template_id_str="cts.alert",
        event_type="CTS_ALERT",
        module="CTS",
        recipient_type="OPS_MANAGER",
        status="SENT",
        delivery_error=None,
        kafka_offset=42,
    )


@pytest.mark.asyncio
async def test_record_delivery_writes_to_db():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    notif_id = str(uuid.uuid4())
    await _record_delivery(
        pool=pool,
        notification_id=notif_id,
        bank_id="test-bank",
        channel="whatsapp",
        template_id_str="security.isolation_violation",
        event_type="SECURITY_VIOLATION",
        module="PLATFORM",
        recipient_type="BANK_IT_ADMIN",
        status="SENT",
        delivery_error=None,
        kafka_offset=101,
    )
    conn.execute.assert_awaited_once()
    # Verify bank_id is in the call args
    args = conn.execute.await_args.args
    assert "test-bank" in args


@pytest.mark.asyncio
async def test_record_delivery_db_failure_does_not_raise():
    pool = AsyncMock()
    pool.acquire = MagicMock(side_effect=RuntimeError("db down"))

    # Must not propagate the exception
    await _record_delivery(
        pool=pool,
        notification_id=str(uuid.uuid4()),
        bank_id="b1",
        channel="email",
        template_id_str="cts.alert",
        event_type="CTS_ALERT",
        module="CTS",
        recipient_type="OPS_MANAGER",
        status="FAILED",
        delivery_error="RECIPIENT_UNRESOLVED",
        kafka_offset=0,
    )


# ── _consume_loop ─────────────────────────────────────────────────────────────

def _make_kafka_msg(payload: dict, offset: int = 0):
    msg = MagicMock()
    msg.value = json.dumps(payload).encode()
    msg.offset = offset
    return msg


class _FakeConsumer:
    """Minimal async-iterable Kafka consumer stub."""

    def __init__(self, *msgs):
        self._msgs = list(msgs)
        self.commit = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._msgs:
            raise StopAsyncIteration
        return self._msgs.pop(0)


@pytest.mark.asyncio
async def test_consume_loop_dispatches_and_commits():
    event = {
        "notification_id": str(uuid.uuid4()),
        "bank_id": "test-bank",
        "channel": "email",
        "recipient": "admin@test.bank",
        "template_id": "cts.human_review_escalated",
        "context": {"instrument_id": "instr-001"},
        "priority": "P1",
        "module": "CTS",
        "event_type": "HUMAN_REVIEW_ESCALATED",
        "recipient_type": "OPS_MANAGER",
    }

    consumer = _FakeConsumer(_make_kafka_msg(event, offset=10))
    dispatcher = AsyncMock(spec=NotificationDispatcher)
    dispatcher.send = AsyncMock(return_value={"status": "sent"})

    with patch("apps.notification_service.main._record_delivery", new=AsyncMock()):
        await _consume_loop(consumer, dispatcher, None, "test-bank")

    dispatcher.send.assert_awaited()
    consumer.commit.assert_awaited()


@pytest.mark.asyncio
async def test_consume_loop_handles_dispatch_failure():
    """Dispatch failure → status FAILED in DB; consumer still commits; loop continues."""
    event = {
        "notification_id": str(uuid.uuid4()),
        "bank_id": "test-bank",
        "channel": "email",
        "recipient": "admin@test.bank",
        "template_id": "cts.alert",
        "context": {},
        "priority": "P1",
        "module": "CTS",
        "event_type": "CTS_ALERT",
        "recipient_type": "OPS_MANAGER",
    }

    consumer = _FakeConsumer(_make_kafka_msg(event, offset=5))
    dispatcher = AsyncMock(spec=NotificationDispatcher)
    dispatcher.send = AsyncMock(side_effect=RuntimeError("channel down"))

    recorded_statuses = []

    async def fake_record(pool, **kwargs):
        recorded_statuses.append(kwargs.get("status"))

    with patch("apps.notification_service.main._record_delivery", side_effect=fake_record):
        await _consume_loop(consumer, dispatcher, None, "test-bank")

    assert "FAILED" in recorded_statuses
    consumer.commit.assert_awaited()


@pytest.mark.asyncio
async def test_consume_loop_unresolvable_recipient_records_failed():
    """Events with recipient_role (unresolvable) are recorded FAILED; consumer still commits."""
    event = {
        "notification_id": str(uuid.uuid4()),
        "bank_id": "test-bank",
        "channel": "whatsapp",
        "recipient_role": "bank_it_admin",
        "template_id": "security.isolation_violation",
        "context": {},
        "priority": "P0",
        "module": "PLATFORM",
        "event_type": "SECURITY_VIOLATION",
    }

    consumer = _FakeConsumer(_make_kafka_msg(event, offset=7))
    dispatcher = AsyncMock(spec=NotificationDispatcher)
    dispatcher.send = AsyncMock()

    recorded_statuses = []

    async def fake_record(pool, **kwargs):
        recorded_statuses.append(kwargs.get("status"))
        recorded_statuses.append(kwargs.get("delivery_error"))

    with patch("apps.notification_service.main._record_delivery", side_effect=fake_record):
        await _consume_loop(consumer, dispatcher, None, "test-bank")

    # Dispatcher should NOT have been called — recipient unresolved
    dispatcher.send.assert_not_awaited()
    assert "FAILED" in recorded_statuses
    assert "RECIPIENT_UNRESOLVED" in recorded_statuses
    consumer.commit.assert_awaited()


@pytest.mark.asyncio
async def test_consume_loop_skips_malformed_json():
    """A message that isn't valid JSON is skipped; loop continues."""
    bad_msg = MagicMock()
    bad_msg.value = b"not-valid-json{"
    bad_msg.offset = 3

    consumer = _FakeConsumer(bad_msg)
    dispatcher = AsyncMock(spec=NotificationDispatcher)
    dispatcher.send = AsyncMock()

    await _consume_loop(consumer, dispatcher, None, "test-bank")

    dispatcher.send.assert_not_awaited()
    consumer.commit.assert_awaited()


# ── health probes ────────────────────────────────────────────────────────────

class TestHealthProbes:
    def test_liveness_always_200(self):
        client = TestClient(app)
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["service"] == SERVICE_NAME

    def test_readiness_degraded_when_no_consumer(self):
        # app.state is not set up (no lifespan in TestClient by default)
        client = TestClient(app)
        resp = client.get("/health/ready")
        # Should be 503 — no kafka_consumer in state
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert "kafka_consumer" in data["checks"]
