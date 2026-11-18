"""Build the notification dispatcher from deployment settings. Nothing about the mail provider is hardcoded: the bank (or we, with Gmail for now)
sets these and restarts; the password is a secret.

    SMTP_HOST          mail server, e.g. smtp.gmail.com. Unset = email is NOT configured (no default provider is assumed).
    SMTP_PORT          default 587
    SMTP_SECURITY      starttls (default) | ssl | none
    SMTP_USERNAME      login; omit for an unauthenticated relay
    SMTP_FROM_ADDRESS  default: the username
    SMTP_CA_FILE       optional PEM file of an extra trusted CA (a bank's private CA); certificates are always verified
    secret smtp.password   ASTRA_SECRET_SMTP_PASSWORD in dev, Vault at secret/astra/{bank_id}/smtp/password in production.
                           For Gmail this is an app password (2-step verification must be on), never the account password.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import structlog

from shared.messages import get_message

log = structlog.get_logger()

_SECURITIES = ("starttls", "ssl", "none")


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    security: str
    username: Optional[str]
    password: Optional[str]
    from_address: str
    ca_file: Optional[str] = None


def _platform(config_service: Any, key: str) -> Optional[str]:
    try:
        value = config_service.get_platform(key)
    except Exception:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


async def read_smtp_settings(config_service: Any) -> Optional[SmtpSettings]:
    host = _platform(config_service, "smtp.host")
    if not host:
        return None
    security = (_platform(config_service, "smtp.security") or "starttls").lower()
    if security not in _SECURITIES:
        raise ValueError(get_message("PLATFORM_SMTP_SECURITY_UNKNOWN", value=security))
    port = int(_platform(config_service, "smtp.port") or 587)
    username = _platform(config_service, "smtp.username")
    password = None
    if username:
        try:
            password = (await config_service.get_secret("smtp.password")) or None
        except Exception as exc:
            log.warning("smtp.password_unavailable", error=str(exc))
    return SmtpSettings(host=host, port=port, security=security, username=username, password=password,
                        from_address=_platform(config_service, "smtp.from_address") or username or f"astra@{host}",
                        ca_file=_platform(config_service, "smtp.ca_file"))


@dataclass(frozen=True)
class WhatsAppSettings:
    api_url: str
    phone_number_id: str
    access_token: str


async def read_whatsapp_settings(config_service: Any) -> Optional[WhatsAppSettings]:
    """WhatsApp is on only when the API URL, the phone number id and the access token (secret whatsapp.access_token) are all set."""
    api_url, phone_id = _platform(config_service, "whatsapp.api_url"), _platform(config_service, "whatsapp.phone_number_id")
    if not api_url or not phone_id:
        return None
    try:
        token = await config_service.get_secret("whatsapp.access_token")
    except Exception as exc:
        log.warning("whatsapp.access_token_unavailable", error=str(exc))
        return None
    return WhatsAppSettings(api_url.rstrip("/"), phone_id, token) if token else None


async def build_dispatcher(config_service: Any, bank_id: str, *, db_pool: Any = None, debouncer: Any = None) -> Any:
    """A connected NotificationDispatcher with whichever channels are available: email and WhatsApp when configured, the in-app bell whenever there is a
    database. None when there is none of them."""
    from shared.notifications.dispatcher import NotificationDispatcher
    email_channel = await _build_email_channel(config_service, bank_id)
    whatsapp_channel = None
    try:
        wa = await read_whatsapp_settings(config_service)
        if wa is not None:
            from shared.notifications.whatsapp_channel import WhatsAppChannel
            whatsapp_channel = WhatsAppChannel(wa.api_url, wa.phone_number_id, bank_id)
            whatsapp_channel.connect(wa.access_token)
    except Exception as exc:        # never stops the worker
        log.error("notifications.whatsapp_settings_invalid", bank_id=bank_id, error=str(exc))
        whatsapp_channel = None
    bell_channel = None
    if db_pool is not None:
        from shared.alerting.bell import BellChannel
        from shared.alerting.inbox import InboxStore
        from shared.alerting.templates import load_template_settings
        bell_channel = BellChannel(InboxStore(db_pool), await load_template_settings(config_service))
    if email_channel is None and whatsapp_channel is None and bell_channel is None:
        return None
    dispatcher = NotificationDispatcher(bank_id)
    dispatcher.connect(email_channel=email_channel, whatsapp_channel=whatsapp_channel, bell_channel=bell_channel, debouncer=debouncer)
    return dispatcher


async def _build_email_channel(config_service: Any, bank_id: str) -> Any:
    from shared.alerting.templates import load_template_settings
    template_settings = await load_template_settings(config_service)
    try:
        settings = await read_smtp_settings(config_service)
    except Exception as exc:        # a mistyped email setting must never stop the worker: no email, loudly
        log.error("notifications.email_settings_invalid", bank_id=bank_id, error=str(exc))
        return None
    if settings is None:
        log.warning("notifications.email_not_configured", bank_id=bank_id)
        return None
    from shared.notifications.email_channel import EmailChannel
    channel = EmailChannel(settings.host, settings.port, settings.from_address, bank_id,
                           username=settings.username, password=settings.password, security=settings.security,
                           ca_file=settings.ca_file, template_settings=template_settings)
    try:
        channel.connect()
    except Exception as exc:
        # An unreachable mail server must not stop the worker: the channel reopens its session on the first send.
        log.warning("notifications.email_connect_failed", bank_id=bank_id, host=settings.host, error=str(exc))
        channel._ready = True
        channel._opened_by_connect = True
    return channel
