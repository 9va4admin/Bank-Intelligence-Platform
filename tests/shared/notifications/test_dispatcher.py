"""
Tests for NotificationDispatcher — channel routing, template rendering,
delivery tracking, and graceful degradation when a channel is down.

TDD: written BEFORE the implementation.
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from shared.notifications.dispatcher import NotificationDispatcher, NotificationRequest
from shared.notifications.exceptions import NotificationDeliveryError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def email_channel():
    ch = AsyncMock()
    ch.send = AsyncMock(return_value={"message_id": "email-001", "status": "sent"})
    return ch


@pytest.fixture
def whatsapp_channel():
    ch = AsyncMock()
    ch.send = AsyncMock(return_value={"message_id": "wa-001", "status": "sent"})
    return ch


@pytest.fixture
def dispatcher(email_channel, whatsapp_channel) -> NotificationDispatcher:
    d = NotificationDispatcher(bank_id="test-bank")
    d._email = email_channel
    d._whatsapp = whatsapp_channel
    return d


# ---------------------------------------------------------------------------
# NotificationRequest schema
# ---------------------------------------------------------------------------

def test_notification_request_requires_channel():
    req = NotificationRequest(
        channel="email",
        recipient="ops@bank.com",
        template_id="cts.human_review_escalated",
        context={"instrument_id": "instr-001", "queue_position": 3},
    )
    assert req.channel == "email"
    assert req.template_id == "cts.human_review_escalated"


def test_notification_request_invalid_channel_raises():
    with pytest.raises(Exception):
        NotificationRequest(
            channel="sms",           # not a supported channel
            recipient="1234567890",
            template_id="cts.alert",
            context={},
        )


def test_notification_request_auto_generates_notification_id():
    r1 = NotificationRequest(channel="email", recipient="a@b.com", template_id="t", context={})
    r2 = NotificationRequest(channel="email", recipient="a@b.com", template_id="t", context={})
    assert r1.notification_id != r2.notification_id


# ---------------------------------------------------------------------------
# Dispatcher.send — routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_email_routes_to_email_channel(dispatcher, email_channel):
    req = NotificationRequest(
        channel="email",
        recipient="ops@bank.com",
        template_id="cts.human_review_escalated",
        context={"instrument_id": "instr-001"},
    )
    result = await dispatcher.send(req)
    email_channel.send.assert_awaited_once()
    assert result["status"] == "sent"


@pytest.mark.asyncio
async def test_send_whatsapp_routes_to_whatsapp_channel(dispatcher, whatsapp_channel):
    req = NotificationRequest(
        channel="whatsapp",
        recipient="+919876543210",
        template_id="cts.cheque_returned",
        context={"reason": "SIGNATURE_MISMATCH"},
    )
    result = await dispatcher.send(req)
    whatsapp_channel.send.assert_awaited_once()
    assert result["status"] == "sent"


@pytest.mark.asyncio
async def test_send_passes_request_to_channel(dispatcher, email_channel):
    req = NotificationRequest(
        channel="email",
        recipient="admin@bank.com",
        template_id="cts.iet_warning",
        context={"minutes_remaining": 5},
    )
    await dispatcher.send(req)
    call_req = email_channel.send.call_args[0][0]
    assert call_req.template_id == "cts.iet_warning"
    assert call_req.context["minutes_remaining"] == 5


# ---------------------------------------------------------------------------
# Graceful degradation — channel unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_raises_delivery_error_on_channel_failure(dispatcher, email_channel):
    email_channel.send.side_effect = Exception("SMTP connection refused")
    req = NotificationRequest(
        channel="email",
        recipient="ops@bank.com",
        template_id="cts.alert",
        context={},
    )
    with pytest.raises(NotificationDeliveryError, match="email"):
        await dispatcher.send(req)


@pytest.mark.asyncio
async def test_send_whatsapp_failure_raises_delivery_error(dispatcher, whatsapp_channel):
    whatsapp_channel.send.side_effect = Exception("Meta API rate limit")
    req = NotificationRequest(
        channel="whatsapp",
        recipient="+919876543210",
        template_id="cts.alert",
        context={},
    )
    with pytest.raises(NotificationDeliveryError, match="whatsapp"):
        await dispatcher.send(req)


# ---------------------------------------------------------------------------
# send_bulk — fan-out to multiple recipients
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_bulk_calls_send_for_each_recipient(dispatcher):
    requests = [
        NotificationRequest(channel="email", recipient=f"user{i}@bank.com",
                            template_id="cts.shift_start", context={})
        for i in range(3)
    ]
    results = await dispatcher.send_bulk(requests)
    assert len(results) == 3
    assert all(r["status"] == "sent" for r in results)


@pytest.mark.asyncio
async def test_send_bulk_partial_failure_returns_all_results(dispatcher, email_channel):
    """One failure must not abort the rest — return status per recipient."""
    email_channel.send.side_effect = [
        {"message_id": "ok-1", "status": "sent"},
        Exception("timeout"),
        {"message_id": "ok-3", "status": "sent"},
    ]
    requests = [
        NotificationRequest(channel="email", recipient=f"u{i}@b.com",
                            template_id="t", context={})
        for i in range(3)
    ]
    results = await dispatcher.send_bulk(requests)
    assert len(results) == 3
    statuses = [r["status"] for r in results]
    assert statuses.count("sent") == 2
    assert statuses.count("failed") == 1


# ---------------------------------------------------------------------------
# Notification record — what gets returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_result_includes_notification_id(dispatcher):
    req = NotificationRequest(
        channel="email",
        recipient="ops@bank.com",
        template_id="cts.alert",
        context={},
    )
    result = await dispatcher.send(req)
    assert "notification_id" in result
    assert result["notification_id"] == req.notification_id


@pytest.mark.asyncio
async def test_send_result_includes_channel(dispatcher):
    req = NotificationRequest(channel="email", recipient="a@b.com", template_id="t", context={})
    result = await dispatcher.send(req)
    assert result["channel"] == "email"


# ---------------------------------------------------------------------------
# connect() body — channels stored
# ---------------------------------------------------------------------------

def test_connect_stores_email_and_whatsapp_channels():
    d = NotificationDispatcher(bank_id="test-bank")
    email_ch = MagicMock()
    wa_ch = MagicMock()
    d.connect(email_channel=email_ch, whatsapp_channel=wa_ch)
    assert d._email is email_ch
    assert d._whatsapp is wa_ch


def test_connect_with_no_channels_sets_none():
    d = NotificationDispatcher(bank_id="test-bank")
    d.connect()
    assert d._email is None
    assert d._whatsapp is None


# ---------------------------------------------------------------------------
# send() — NotificationDeliveryError re-raised directly (line 56)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_reraises_delivery_error_unchanged(dispatcher, email_channel):
    """NotificationDeliveryError from channel must propagate without wrapping."""
    email_channel.send.side_effect = NotificationDeliveryError("already a delivery error")
    req = NotificationRequest(channel="email", recipient="ops@bank.com", template_id="t", context={})
    with pytest.raises(NotificationDeliveryError, match="already a delivery error"):
        await dispatcher.send(req)


# ---------------------------------------------------------------------------
# _get_channel() — ValueError for unsupported channel (line 94)
# ---------------------------------------------------------------------------

def test_get_channel_raises_value_error_for_unknown_channel():
    d = NotificationDispatcher(bank_id="test-bank")
    d.connect()
    with pytest.raises(ValueError, match="Unsupported channel"):
        d._get_channel("fax")
