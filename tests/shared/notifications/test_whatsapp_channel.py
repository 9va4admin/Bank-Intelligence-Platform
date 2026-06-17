"""
Tests for WhatsAppChannel — Meta Business API client, pre-approved templates,
phone number formatting, and error handling.

TDD: written BEFORE the implementation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.notifications.whatsapp_channel import WhatsAppChannel
from shared.notifications.dispatcher import NotificationRequest
from shared.notifications.exceptions import NotificationDeliveryError


@pytest.fixture
def channel() -> WhatsAppChannel:
    ch = WhatsAppChannel(
        api_url="https://graph.facebook.com/v18.0",
        phone_number_id="12345678",
        bank_id="test-bank",
    )
    mock_http = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"messages": [{"id": "wamid.001"}]}
    mock_http.post = AsyncMock(return_value=mock_response)
    ch._http = mock_http
    ch._access_token = "test-token"
    ch._ready = True
    return ch


# ---------------------------------------------------------------------------
# send — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_calls_meta_api(channel):
    req = NotificationRequest(
        channel="whatsapp",
        recipient="+919876543210",
        template_id="cts.cheque_returned",
        context={"reason": "SIGNATURE_MISMATCH"},
    )
    result = await channel.send(req)
    channel._http.post.assert_awaited_once()
    assert result["status"] == "sent"


@pytest.mark.asyncio
async def test_send_result_includes_message_id(channel):
    req = NotificationRequest(
        channel="whatsapp",
        recipient="+919876543210",
        template_id="cts.cheque_returned",
        context={},
    )
    result = await channel.send(req)
    assert "message_id" in result
    assert result["message_id"] == "wamid.001"


@pytest.mark.asyncio
async def test_send_raises_delivery_error_on_api_failure(channel):
    channel._http.post.side_effect = Exception("Meta API 500")
    req = NotificationRequest(
        channel="whatsapp",
        recipient="+919876543210",
        template_id="cts.alert",
        context={},
    )
    with pytest.raises(NotificationDeliveryError):
        await channel.send(req)


@pytest.mark.asyncio
async def test_send_raises_if_not_ready():
    ch = WhatsAppChannel(api_url="u", phone_number_id="p", bank_id="b")
    req = NotificationRequest(channel="whatsapp", recipient="+91999", template_id="t", context={})
    with pytest.raises(RuntimeError, match="connect"):
        await ch.send(req)


# ---------------------------------------------------------------------------
# Phone number normalisation
# ---------------------------------------------------------------------------

def test_normalise_phone_adds_country_code_if_missing(channel):
    assert channel._normalise_phone("9876543210") == "919876543210"


def test_normalise_phone_strips_plus(channel):
    assert channel._normalise_phone("+919876543210") == "919876543210"


def test_normalise_phone_strips_spaces_and_dashes(channel):
    assert channel._normalise_phone("+91 98765-43210") == "919876543210"


# ---------------------------------------------------------------------------
# Template mapping — Meta requires pre-approved template names
# ---------------------------------------------------------------------------

def test_template_map_returns_meta_name_for_known_template(channel):
    meta_name = channel._map_template("cts.cheque_returned")
    assert meta_name is not None
    assert isinstance(meta_name, str)
    assert len(meta_name) > 0


def test_template_map_returns_generic_for_unknown_template(channel):
    meta_name = channel._map_template("unknown.xyz")
    assert meta_name == "astra_generic_notification"
