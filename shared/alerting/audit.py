"""The audit trail around every alert (docs/design/alerting-blueprint.md, section 6).

    intent  -> written BEFORE a notification is sent   (ALERT_DISPATCH_INTENDED)
    outcome -> written AFTER each attempt              (ALERT_DELIVERY_SUCCEEDED / ALERT_DELIVERY_FAILED)
    lifecycle -> raised, acknowledged, escalated, resolved ...

An audit problem must never stop an alert from being sent, so nothing here raises: a failed write is reported through `on_failure` (the caller raises
the "audit backlog" alert) and returns None. Recipients are masked and error text is scrubbed of addresses and secrets; the message body is never recorded.

`sink` is an async callable (event_type, bank_id, entity_id, actor_id, payload) -> reference or None. In production it is the Redis audit stream
(durable, fast), with a direct Immudb write as `fallback`.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional

import structlog

from shared.audit.audit_event import AuditEventType
from shared.utils.masking import mask_email, mask_phone

log = structlog.get_logger()

Sink = Callable[[str, str, str, str, dict], Awaitable[Optional[str]]]

SYSTEM_ACTOR = "system:alert-engine"
_PHONE_CHANNELS = ("whatsapp", "sms")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SECRET = re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\b\s*[=:]\s*\S+")


def mask_recipient(recipient: str, channel: str) -> str:
    """An address or phone becomes a masked reference; an internal user reference (the bell) is not personal data and is kept."""
    if channel in _PHONE_CHANNELS:
        return mask_phone(recipient)
    if "@" in recipient:
        return mask_email(recipient)
    return recipient


def scrub_error(text: str, max_chars: int) -> str:
    """Keep the reason, drop addresses and secrets, bound the length."""
    cleaned = _SECRET.sub(lambda m: f"{m.group(1)}=***", _EMAIL.sub(lambda m: mask_email(m.group(0)), text or ""))
    return cleaned[:max_chars]


class AlertAuditor:
    def __init__(self, sink: Optional[Sink], *, fallback: Optional[Sink] = None,
                 on_failure: Optional[Callable[..., Any]] = None, max_error_chars: int = 200) -> None:
        self._sink, self._fallback, self._on_failure, self._max_error_chars = sink, fallback, on_failure, max_error_chars

    async def _write(self, event_type: AuditEventType, bank_id: str, entity_id: str, actor: str, payload: dict[str, Any]) -> Optional[str]:
        for sink in (self._sink, self._fallback):
            if sink is None:
                continue
            try:
                ref = await sink(event_type.value, bank_id, entity_id, actor, payload)
            except Exception as exc:  # noqa: BLE001  - the audit path must never break a send
                log.warning("alert_audit.sink_failed", event_type=event_type.value, bank_id=bank_id, error=scrub_error(str(exc), self._max_error_chars))
                continue
            if ref:
                return ref
        self._report_failure(event_type.value, bank_id, entity_id)
        return None

    def _report_failure(self, event_type: str, bank_id: str, entity_id: str) -> None:
        log.error("alert_audit.not_written", event_type=event_type, bank_id=bank_id, entity_id=entity_id)
        if self._on_failure is not None:
            try:
                self._on_failure(event_type=event_type, bank_id=bank_id, entity_id=entity_id)
            except Exception:  # noqa: BLE001
                pass

    async def intent(self, *, bank_id: str, incident_id: str, delivery_id: str, channel: str, recipient: str, level: int, template_id: str,
                     severity: str, component: str, rule_id: str = "") -> Optional[str]:
        return await self._write(AuditEventType.ALERT_DISPATCH_INTENDED, bank_id, incident_id, SYSTEM_ACTOR, {
            "delivery_id": delivery_id, "channel": channel, "recipient_ref": mask_recipient(recipient, channel), "level": level,
            "template_id": template_id, "severity": severity, "component": component, "rule_id": rule_id,
        })

    async def outcome(self, *, bank_id: str, incident_id: str, delivery_id: str, channel: str, succeeded: bool, attempt: int,
                      intent_ref: Optional[str], error: str = "") -> Optional[str]:
        event = AuditEventType.ALERT_DELIVERY_SUCCEEDED if succeeded else AuditEventType.ALERT_DELIVERY_FAILED
        payload: dict[str, Any] = {"delivery_id": delivery_id, "channel": channel, "attempt": attempt, "intent_ref": intent_ref}
        if not succeeded:
            payload["error"] = scrub_error(error, self._max_error_chars)
        return await self._write(event, bank_id, incident_id, SYSTEM_ACTOR, payload)

    async def lifecycle(self, event: AuditEventType, *, bank_id: str, incident_id: str, actor: str, detail: dict[str, Any]) -> Optional[str]:
        return await self._write(event, bank_id, incident_id, actor, dict(detail))
