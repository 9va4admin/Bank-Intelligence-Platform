"""
Tests for EmailChannel — Postal SMTP client, template rendering, masking.

TDD: written BEFORE the implementation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.notifications.email_channel import EmailChannel
from shared.notifications.dispatcher import NotificationRequest
from shared.notifications.exceptions import NotificationDeliveryError


@pytest.fixture
def channel() -> EmailChannel:
    ch = EmailChannel(
        smtp_host="postal.astra.internal",
        smtp_port=25,
        from_address="noreply@astra.bank",
        bank_id="test-bank",
    )
    mock_smtp = MagicMock()
    mock_smtp.sendmail = MagicMock()
    ch._smtp = mock_smtp
    ch._ready = True
    return ch


# ---------------------------------------------------------------------------
# send — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_calls_smtp_sendmail(channel):
    req = NotificationRequest(
        channel="email",
        recipient="ops@bank.com",
        template_id="cts.human_review_escalated",
        context={"instrument_id": "instr-001", "queue_position": 2},
    )
    result = await channel.send(req)
    channel._smtp.sendmail.assert_called_once()
    assert result["status"] == "sent"


@pytest.mark.asyncio
async def test_send_uses_recipient_as_to_address(channel):
    req = NotificationRequest(
        channel="email",
        recipient="fraud@bank.com",
        template_id="cts.fraud_alert",
        context={},
    )
    await channel.send(req)
    call_args = channel._smtp.sendmail.call_args
    to_addr = call_args[0][1]
    assert to_addr == "fraud@bank.com"


@pytest.mark.asyncio
async def test_send_raises_delivery_error_on_smtp_failure(channel):
    channel._smtp.sendmail.side_effect = Exception("connection reset")
    req = NotificationRequest(
        channel="email",
        recipient="ops@bank.com",
        template_id="cts.alert",
        context={},
    )
    with pytest.raises(NotificationDeliveryError):
        await channel.send(req)


@pytest.mark.asyncio
async def test_send_raises_if_not_ready():
    ch = EmailChannel(smtp_host="h", smtp_port=25, from_address="a@b", bank_id="b")
    req = NotificationRequest(channel="email", recipient="x@y.com", template_id="t", context={})
    with pytest.raises(RuntimeError, match="connect"):
        await ch.send(req)


# ---------------------------------------------------------------------------
# Template rendering — context injected into subject/body
# ---------------------------------------------------------------------------

def test_render_template_injects_context(channel):
    subject, body = channel._render(
        template_id="cts.human_review_escalated",
        context={"instrument_id": "instr-001", "queue_position": 3, "bank_id": "test-bank"},
    )
    assert "instr-001" in subject or "instr-001" in body


def test_render_unknown_template_falls_back_to_generic(channel):
    subject, body = channel._render(
        template_id="unknown.template.id",
        context={"event": "something"},
    )
    assert subject is not None
    assert body is not None
    assert len(subject) > 0


# ---------------------------------------------------------------------------
# connect() — success and failure paths
# ---------------------------------------------------------------------------

def test_connect_success_sets_ready():
    """connect() with a mocked smtplib.SMTP should set _ready=True."""
    ch = EmailChannel(smtp_host="postal.astra.internal", smtp_port=25,
                      from_address="noreply@astra.bank", bank_id="test-bank")
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.return_value = MagicMock()
        ch.connect()
    assert ch._ready is True


def test_connect_failure_raises_runtime_error():
    """connect() when SMTP raises must wrap in RuntimeError."""
    ch = EmailChannel(smtp_host="bad-host", smtp_port=25,
                      from_address="noreply@astra.bank", bank_id="test-bank")
    with patch("smtplib.SMTP", side_effect=Exception("connection refused")):
        with pytest.raises(RuntimeError, match="Postal SMTP connect failed"):
            ch.connect()


# ---------------------------------------------------------------------------
# _render() — KeyError fallback (lines 94-95): context missing template keys
# ---------------------------------------------------------------------------

def test_render_template_missing_context_key_falls_back_to_raw_template(channel):
    """If context is missing a key required by the template, return raw subject/body."""
    # cts.human_review_escalated requires {instrument_id} and {queue_position}
    # Provide neither — KeyError must be caught, returning raw template strings
    subject, body = channel._render(
        template_id="cts.human_review_escalated",
        context={},  # missing instrument_id, queue_position
    )
    # Should return the unformatted template strings (no KeyError raised)
    assert "ASTRA CTS" in subject
    assert subject is not None
    assert body is not None
