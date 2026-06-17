"""
EmailChannel — sends email via Postal SMTP (self-hosted MTA).

No cloud dependency. Postal is deployed inside the bank's cluster.
SMTP credentials come from config_service (Vault) at runtime — never hardcoded.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import structlog

from shared.notifications.exceptions import NotificationDeliveryError

log = structlog.get_logger()

# Minimal template library — subject + plain-text body per template_id
_TEMPLATES: dict[str, tuple[str, str]] = {
    "cts.human_review_escalated": (
        "ASTRA CTS — Cheque {instrument_id} requires human review",
        "Cheque instrument {instrument_id} has been escalated for human review.\n"
        "Queue position: {queue_position}\nBank: {bank_id}",
    ),
    "cts.cheque_returned": (
        "ASTRA CTS — Cheque return notice",
        "A cheque has been returned.\nReason: {reason}\nBank: {bank_id}",
    ),
    "cts.fraud_alert": (
        "ASTRA CTS — Fraud alert",
        "Fraud signal detected.\nBank: {bank_id}",
    ),
    "cts.iet_warning": (
        "ASTRA CTS — IET expiry warning",
        "Cheque IET window closing.\nMinutes remaining: {minutes_remaining}\nBank: {bank_id}",
    ),
    "cts.shift_start": (
        "ASTRA CTS — Shift summary",
        "Your shift has started. Bank: {bank_id}",
    ),
}

_GENERIC_SUBJECT = "ASTRA Notification"
_GENERIC_BODY = "You have a new notification from ASTRA.\nDetails: {event}"


class EmailChannel:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_address: str,
        bank_id: str,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._from_address = from_address
        self._bank_id = bank_id
        self._smtp = None
        self._ready = False

    def connect(self) -> None:
        try:
            self._smtp = smtplib.SMTP(self._smtp_host, self._smtp_port)
        except Exception as exc:
            raise RuntimeError(f"Postal SMTP connect failed: {exc}") from exc
        self._ready = True

    async def send(self, request) -> dict[str, Any]:
        self._assert_ready()
        subject, body = self._render(request.template_id, request.context)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_address
        msg["To"] = request.recipient
        msg.attach(MIMEText(body, "plain"))

        try:
            self._smtp.sendmail(self._from_address, request.recipient, msg.as_string())
        except Exception as exc:
            log.error("email.send_failed", recipient=request.recipient, error=str(exc))
            raise NotificationDeliveryError(f"Email send failed: {exc}") from exc

        log.info("email.sent", recipient=request.recipient, template_id=request.template_id)
        return {"message_id": f"postal-{request.notification_id}", "status": "sent"}

    def _render(self, template_id: str, context: dict[str, Any]) -> tuple[str, str]:
        ctx = {**context, "bank_id": context.get("bank_id", self._bank_id)}
        if template_id in _TEMPLATES:
            subject_tpl, body_tpl = _TEMPLATES[template_id]
            try:
                return subject_tpl.format(**ctx), body_tpl.format(**ctx)
            except KeyError:
                return subject_tpl, body_tpl
        # Generic fallback
        body = _GENERIC_BODY.format(event=str(ctx))
        return _GENERIC_SUBJECT, body

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "EmailChannel.connect() has not been called. "
                "Call it in the service startup before sending emails."
            )
