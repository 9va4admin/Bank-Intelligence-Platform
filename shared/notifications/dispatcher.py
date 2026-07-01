"""
NotificationDispatcher — routes notification requests to the correct channel.

Supported channels: email (Postal SMTP), whatsapp (Meta Business API).
Channel implementations are injected at startup — dispatcher is channel-agnostic.

Usage:
    dispatcher = NotificationDispatcher(bank_id=bank_id)
    dispatcher.connect(email_config=..., whatsapp_config=...)
    await dispatcher.send(NotificationRequest(
        channel="email",
        recipient="ops@bank.com",
        template_id="cts.human_review_escalated",
        context={"instrument_id": "instr-001"},
    ))
"""
import asyncio
import uuid
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.notifications.exceptions import NotificationDeliveryError

log = structlog.get_logger()

_SUPPORTED_CHANNELS = {"email", "whatsapp", "bell"}


class NotificationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel: Literal["email", "whatsapp", "bell"]
    recipient: str      # email address | E.164 phone | user_id (bell)
    template_id: str
    context: dict[str, Any]
    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class NotificationDispatcher:
    def __init__(self, bank_id: str) -> None:
        self._bank_id = bank_id
        self._email = None
        self._whatsapp = None
        self._bell = None

    def connect(self, email_channel=None, whatsapp_channel=None, bell_channel=None) -> None:
        self._email = email_channel
        self._whatsapp = whatsapp_channel
        self._bell = bell_channel

    async def send(self, request: NotificationRequest) -> dict[str, Any]:
        channel = self._get_channel(request.channel)
        try:
            result = await channel.send(request)
        except NotificationDeliveryError:
            raise
        except Exception as exc:
            log.error("notification.delivery_failed",
                      channel=request.channel,
                      template_id=request.template_id,
                      error=str(exc))
            raise NotificationDeliveryError(
                f"{request.channel} delivery failed for template "
                f"'{request.template_id}': {exc}"
            ) from exc

        return {
            "notification_id": request.notification_id,
            "channel": request.channel,
            "status": result.get("status", "sent"),
            "message_id": result.get("message_id"),
        }

    async def send_bulk(self, requests: list[NotificationRequest]) -> list[dict[str, Any]]:
        results = []
        for req in requests:
            try:
                result = await self.send(req)
                results.append(result)
            except (NotificationDeliveryError, Exception) as exc:
                results.append({
                    "notification_id": req.notification_id,
                    "channel": req.channel,
                    "status": "failed",
                    "error": str(exc),
                })
        return results

    def _get_channel(self, channel: str):
        if channel == "email":
            return self._email
        if channel == "whatsapp":
            return self._whatsapp
        if channel == "bell":
            return self._bell
        raise ValueError(f"Unsupported channel: {channel}")
