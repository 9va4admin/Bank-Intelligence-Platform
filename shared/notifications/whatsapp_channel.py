"""
WhatsAppChannel — sends WhatsApp messages via Meta Business API.

Uses pre-approved message templates only (Meta requirement).
Access token is fetched from config_service (Vault) at startup.
Phone numbers are normalised to E.164 without the leading '+'.

Template name mapping:
  ASTRA template_id  →  Meta pre-approved template name
  The mapping is maintained here and updated when templates are approved.
"""
import re
from typing import Any

import structlog

from shared.notifications.exceptions import NotificationDeliveryError

log = structlog.get_logger()

# Maps ASTRA template IDs to Meta-approved template names
_TEMPLATE_MAP: dict[str, str] = {
    "cts.human_review_escalated": "astra_cts_human_review",
    "cts.cheque_returned":        "astra_cts_cheque_returned",
    "cts.fraud_alert":            "astra_cts_fraud_alert",
    "cts.iet_warning":            "astra_cts_iet_warning",
    "ej.dispute_resolved":        "astra_ej_dispute_resolved",
    "ej.dispute_escalated":       "astra_ej_dispute_escalated",
}

_GENERIC_TEMPLATE = "astra_generic_notification"
_DEFAULT_COUNTRY_CODE = "91"  # India


class WhatsAppChannel:
    def __init__(
        self,
        api_url: str,
        phone_number_id: str,
        bank_id: str,
    ) -> None:
        self._api_url = api_url
        self._phone_number_id = phone_number_id
        self._bank_id = bank_id
        self._http = None
        self._access_token: str = ""
        self._ready = False

    def connect(self, access_token: str, http_client=None) -> None:
        self._access_token = access_token
        if http_client is not None:
            self._http = http_client
        else:
            import httpx  # type: ignore[import]
            self._http = httpx.AsyncClient(timeout=10.0)
        self._ready = True

    async def send(self, request) -> dict[str, Any]:
        self._assert_ready()
        phone = self._normalise_phone(request.recipient)
        meta_template = self._map_template(request.template_id)

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": meta_template,
                "language": {"code": "en"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(v)}
                            for v in request.context.values()
                        ],
                    }
                ],
            },
        }
        url = f"{self._api_url}/{self._phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        try:
            response = await self._http.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("whatsapp.send_failed", recipient=phone, template=meta_template, error=str(exc))
            raise NotificationDeliveryError(f"WhatsApp send failed: {exc}") from exc

        messages = data.get("messages", [{}])
        message_id = messages[0].get("id", "") if messages else ""
        log.info("whatsapp.sent", recipient=phone, template=meta_template, message_id=message_id)
        return {"message_id": message_id, "status": "sent"}

    def _normalise_phone(self, phone: str) -> str:
        digits = re.sub(r"[^\d]", "", phone)
        if not digits.startswith(_DEFAULT_COUNTRY_CODE):
            digits = _DEFAULT_COUNTRY_CODE + digits
        return digits

    def _map_template(self, template_id: str) -> str:
        return _TEMPLATE_MAP.get(template_id, _GENERIC_TEMPLATE)

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "WhatsAppChannel.connect() has not been called. "
                "Call it in the service startup before sending messages."
            )
