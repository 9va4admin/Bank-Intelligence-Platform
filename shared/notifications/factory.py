"""Build the notification dispatcher from deployment settings. Nothing about the mail provider is hardcoded: the bank (or we, with Gmail for now)
sets these and restarts; the password is a secret.

    SMTP_HOST          mail server, e.g. smtp.gmail.com. Unset = email is NOT configured (no default provider is assumed).
    SMTP_PORT          default 587
    SMTP_SECURITY      starttls (default) | ssl | none
    SMTP_USERNAME      login; omit for an unauthenticated relay
    SMTP_FROM_ADDRESS  default: the username
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
                        from_address=_platform(config_service, "smtp.from_address") or username or f"astra@{host}")


async def build_dispatcher(config_service: Any, bank_id: str) -> Any:
    """A connected NotificationDispatcher with the email channel, or None when email is not configured."""
    try:
        settings = await read_smtp_settings(config_service)
    except Exception as exc:        # a mistyped email setting must never stop the worker: no email, loudly
        log.error("notifications.email_settings_invalid", bank_id=bank_id, error=str(exc))
        return None
    if settings is None:
        log.warning("notifications.email_not_configured", bank_id=bank_id)
        return None
    from shared.notifications.dispatcher import NotificationDispatcher
    from shared.notifications.email_channel import EmailChannel
    channel = EmailChannel(settings.host, settings.port, settings.from_address, bank_id,
                           username=settings.username, password=settings.password, security=settings.security)
    try:
        channel.connect()
    except Exception as exc:
        # An unreachable mail server must not stop the worker: the channel reopens its session on the first send.
        log.warning("notifications.email_connect_failed", bank_id=bank_id, host=settings.host, error=str(exc))
        channel._ready = True
        channel._opened_by_connect = True
    dispatcher = NotificationDispatcher(bank_id)
    dispatcher.connect(email_channel=channel)
    return dispatcher
