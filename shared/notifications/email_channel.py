"""
EmailChannel — sends email via Postal SMTP (self-hosted MTA).

No cloud dependency. Postal is deployed inside the bank's cluster.
SMTP credentials come from config_service (Vault) at runtime — never hardcoded.
"""
import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import structlog

from shared.notifications.exceptions import NotificationDeliveryError
from shared.messages import get_message

log = structlog.get_logger()

# Minimal template library — subject + plain-text body per template_id
_TEMPLATES: dict[str, tuple[str, str]] = {
    "cts.human_review_escalated": (
        "ASTRA CTS — Cheque {instrument_id} requires human review",
        "Cheque instrument {instrument_id} has been escalated for human review.\n"
        "Queue position: {queue_position}\nBank: {bank_id}",
    ),
    "cts.cheque_returned": (
        get_message("PLATFORM_ASTRA_CTS_CHEQUE_RETURN_NOTICE"),
        "A cheque has been returned.\nReason: {reason}\nBank: {bank_id}",
    ),
    "cts.fraud_alert": (
        get_message("PLATFORM_ASTRA_CTS_FRAUD_ALERT"),
        "Fraud signal detected.\nBank: {bank_id}",
    ),
    "cts.iet_warning": (
        get_message("PLATFORM_ASTRA_CTS_IET_EXPIRY_WARNING"),
        "Cheque IET window closing.\nMinutes remaining: {minutes_remaining}\nBank: {bank_id}",
    ),
    "cts.shift_start": (
        get_message("PLATFORM_ASTRA_CTS_SHIFT_SUMMARY"),
        "Your shift has started. Bank: {bank_id}",
    ),
}

# Platform health mails: wording lives in the message registry; each entry is (subject key, body key, body variables).
_MESSAGE_TEMPLATES = {
    "PLATFORM_HEALTH_ALERT": ("PLATFORM_EMAIL_HEALTH_ALERT_SUBJECT", "PLATFORM_EMAIL_HEALTH_ALERT_BODY",
                              ("bank_id", "severity", "component", "event_type", "message")),
    "PLATFORM_HEALTH_RECOVERED": ("PLATFORM_EMAIL_HEALTH_RECOVERED_SUBJECT", "PLATFORM_EMAIL_HEALTH_RECOVERED_BODY",
                                  ("bank_id", "component", "down_for", "message")),
}
_SUBJECT_VARS = {"PLATFORM_EMAIL_HEALTH_ALERT_SUBJECT": ("bank_id", "severity", "component"),
                 "PLATFORM_EMAIL_HEALTH_RECOVERED_SUBJECT": ("bank_id", "component")}

_GENERIC_SUBJECT = "ASTRA Notification"
_GENERIC_BODY = "You have a new notification from ASTRA.\nDetails: {event}"


class EmailChannel:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_address: str,
        bank_id: str,
        *,
        username: str | None = None,
        password: str | None = None,
        security: str = "none",          # none | starttls | ssl  (Gmail: starttls on 587 with an app password)
        timeout: float = 15.0,
        ca_file: str | None = None,      # extra trusted CA / the server's certificate (a bank's private CA); the system store is always used
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._from_address = from_address
        self._bank_id = bank_id
        self._username = username
        self._password = password
        self._security = security
        self._timeout = timeout
        self._ca_file = ca_file
        self._smtp = None
        self._ready = False
        self._opened_by_connect = False   # only then may a dropped connection be reopened

    def _open(self):
        """One authenticated, encrypted-if-configured SMTP session."""
        context = ssl.create_default_context(cafile=self._ca_file)      # verifies the certificate chain and the host name
        if self._security == "ssl":
            smtp = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=self._timeout, context=context)
        else:
            smtp = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=self._timeout)
            if self._security == "starttls":
                smtp.starttls(context=context)
        if self._username:
            smtp.login(self._username, self._password or "")
        return smtp

    def connect(self) -> None:
        try:
            self._smtp = self._open()
        except Exception as exc:
            raise RuntimeError(get_message("PLATFORM_POSTAL_SMTP_CONNECT_FAILED", exc=exc)) from exc
        self._ready = True
        self._opened_by_connect = True

    async def send(self, request) -> dict[str, Any]:
        self._assert_ready()
        subject, body = self._render(request.template_id, request.context)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_address
        msg["To"] = request.recipient
        msg.attach(MIMEText(body, "plain"))

        try:
            await asyncio.to_thread(self._send_sync, request.recipient, msg.as_string())    # smtplib blocks: keep the event loop free
        except Exception as exc:
            log.error("email.send_failed", recipient=request.recipient, error=str(exc))
            raise NotificationDeliveryError(get_message("PLATFORM_EMAIL_SEND_FAILED", exc=exc)) from exc

        log.info("email.sent", recipient=request.recipient, template_id=request.template_id)
        return {"message_id": f"postal-{request.notification_id}", "status": "sent"}

    def _send_sync(self, recipient: str, text: str) -> None:
        try:
            self._smtp.sendmail(self._from_address, recipient, text)
        except (smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError, OSError):
            if not self._opened_by_connect:
                raise
            self._smtp = self._open()                        # the server dropped an idle session: reopen once and resend
            self._smtp.sendmail(self._from_address, recipient, text)

    def _render(self, template_id: str, context: dict[str, Any]) -> tuple[str, str]:
        ctx = {**context, "bank_id": context.get("bank_id", self._bank_id)}
        if template_id in _MESSAGE_TEMPLATES:
            subject_key, body_key, variables = _MESSAGE_TEMPLATES[template_id]
            values = {v: str(ctx.get(v, "")) for v in variables}
            return get_message(subject_key, **{v: values[v] for v in _SUBJECT_VARS[subject_key]}), get_message(body_key, **values)
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
                get_message("PLATFORM_EMAILCHANNEL_CONNECT_HAS_NOT_BEEN")
            )
