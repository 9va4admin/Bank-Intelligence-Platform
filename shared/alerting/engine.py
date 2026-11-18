"""The delivery engine: sends what is in the outbox, retries with backoff, gives up cleanly, falls back to another channel, and audits every attempt
(intent before the send, outcome after). Nothing here is fixed: attempts, delays, lease and fallbacks are configuration.

Settings (Layer 3): alerting.delivery_max_attempts, alerting.delivery_backoff_seconds (JSON list, the last value repeats),
alerting.delivery_lease_seconds, alerting.delivery_fallbacks (JSON {"email": ["whatsapp"], ...}), alerting.delivery_batch_size.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.alerting.audit import AlertAuditor, scrub_error
from shared.alerting.delivery import DeliveryRow, DeliveryStore
from shared.audit.audit_event import AuditEventType
from shared.notifications.dispatcher import NotificationRequest

log = structlog.get_logger()

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_SECONDS = [60.0, 300.0, 900.0]
DEFAULT_LEASE_SECONDS = 120.0
DEFAULT_BATCH_SIZE = 20
DEFAULT_FALLBACKS: dict[str, list[str]] = {"email": ["whatsapp", "bell"], "whatsapp": ["email", "bell"]}
ERROR_MAX_CHARS = 200
UNRESOLVED_RECIPIENT = "unresolved"      # placeholder recipient of a record kept for an event nobody could be found for


@dataclass(frozen=True)
class Target:
    channel: str
    recipient: str


class DeliveryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: list[float] = DEFAULT_BACKOFF_SECONDS
    lease_seconds: float = DEFAULT_LEASE_SECONDS
    fallbacks: dict[str, list[str]] = DEFAULT_FALLBACKS
    batch_size: int = DEFAULT_BATCH_SIZE


class SubmitResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    queued: int = 0               # accepted for later (a delayed submission); not tried yet
    sent: int = 0
    retrying: int = 0
    undelivered: int = 0
    skipped: int = 0              # already queued by an earlier identical call (an activity retry)


class ProcessResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    attempted: int = 0
    sent: int = 0
    retrying: int = 0
    undelivered: int = 0


ResolveTargets = Callable[[str], Awaitable[list[Target]]]


_AUTH = re.compile(r"535|authentication|40[13]|unauthor|token|credential")
_NETWORK = re.compile(r"connection|refused|timed.?out|timeout|unreachable|reset|name.?resolution|dns")
_REJECTED = re.compile(r"55[0-4]|mailbox|rejected|recipient")


def classify_failure(error: str) -> str:
    """The kind of problem, without its details: auth | network | rejected | error."""
    text = (error or "").lower()
    if _AUTH.search(text):
        return "auth"
    if _NETWORK.search(text):
        return "network"
    if _REJECTED.search(text):
        return "rejected"
    return "error"


async def _get(config_service: Any, key: str) -> Any:
    try:
        return await config_service.get(key)
    except Exception:
        return None


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


async def load_policy(config_service: Any) -> DeliveryPolicy:
    """Read the policy; a missing or malformed value falls back to the safe default for that setting alone."""
    kw: dict[str, Any] = {}
    try:
        kw["max_attempts"] = max(1, int(await _get(config_service, "alerting.delivery_max_attempts")))
    except (TypeError, ValueError):
        pass
    try:
        kw["lease_seconds"] = float(await _get(config_service, "alerting.delivery_lease_seconds"))
    except (TypeError, ValueError):
        pass
    try:
        kw["batch_size"] = max(1, int(await _get(config_service, "alerting.delivery_batch_size")))
    except (TypeError, ValueError):
        pass
    backoff = _json(await _get(config_service, "alerting.delivery_backoff_seconds"))
    if isinstance(backoff, list) and backoff:
        try:
            kw["backoff_seconds"] = [float(x) for x in backoff]
        except (TypeError, ValueError):
            pass
    fallbacks = _json(await _get(config_service, "alerting.delivery_fallbacks"))
    if isinstance(fallbacks, dict):
        kw["fallbacks"] = {str(k): [str(c) for c in v] for k, v in fallbacks.items() if isinstance(v, list)}
    return DeliveryPolicy(**kw)


class DeliveryEngine:
    def __init__(self, store: DeliveryStore, dispatcher: Any, auditor: Optional[AlertAuditor], policy: DeliveryPolicy) -> None:
        self._store, self._dispatcher, self._auditor, self._policy = store, dispatcher, auditor, policy

    async def submit(self, *, bank_id: str, incident_id: str, occasion: str, targets: list[Target], template_id: str, context: dict[str, Any],
                     priority: str, component: str, resolve_targets: ResolveTargets, level: int = 0, delay_seconds: float = 0.0) -> SubmitResult:
        """Queue every target, then try each one now (or leave it queued until `delay_seconds` have passed). Identical calls (an activity retry) queue nothing new."""
        out = {"sent": 0, "retrying": 0, "undelivered": 0, "skipped": 0, "queued": 0}
        for target in targets:
            queued = await self._store.enqueue(bank_id=bank_id, incident_id=incident_id, occasion=occasion, level=level, channel=target.channel,
                                               recipient=target.recipient, template_id=template_id, payload=context, priority=priority,
                                               delay_seconds=delay_seconds)
            if not queued.created:
                out["skipped"] += 1
                continue
            if delay_seconds > 0:
                out["queued"] += 1
                continue
            row = await self._store.claim(bank_id, queued.delivery_id, lease_seconds=self._policy.lease_seconds)
            if row is None:
                continue
            outcome = await self._attempt(row, resolve_targets)
            out[outcome] += 1
        return SubmitResult(**out)

    async def record_undeliverable(self, *, bank_id: str, incident_id: str, occasion: str, channel: str, template_id: str, context: dict[str, Any],
                                   priority: str, reason: str) -> None:
        """An event nobody could be found for: keep a visible record (UNDELIVERED, with the reason) and audit it, instead of dropping it silently."""
        queued = await self._store.enqueue(bank_id=bank_id, incident_id=incident_id, occasion=occasion, level=0, channel=channel,
                                           recipient=UNRESOLVED_RECIPIENT, template_id=template_id, payload=context, priority=priority)
        if not queued.created:
            return
        row = await self._store.claim(bank_id, queued.delivery_id, lease_seconds=self._policy.lease_seconds)
        if row is None:
            return
        await self._record(self._store.mark_undelivered(bank_id, queued.delivery_id, error=reason, provider_class="unresolved"), row)
        if self._auditor is not None:
            await self._auditor.outcome(bank_id=bank_id, incident_id=incident_id, delivery_id=queued.delivery_id, channel=channel, succeeded=False,
                                        attempt=row.attempt, intent_ref=None, error=reason)

    async def process_due(self, bank_id: str, *, resolve_targets: ResolveTargets) -> ProcessResult:
        """Retry what is due and recover deliveries whose sender died."""
        out = {"attempted": 0, "sent": 0, "retrying": 0, "undelivered": 0}
        for delivery_id in await self._store.due_ids(bank_id, limit=self._policy.batch_size):
            row = await self._store.claim(bank_id, delivery_id, lease_seconds=self._policy.lease_seconds)
            if row is None:
                continue
            out["attempted"] += 1
            out[await self._attempt(row, resolve_targets)] += 1
        return ProcessResult(**out)

    async def _attempt(self, row: DeliveryRow, resolve_targets: ResolveTargets) -> str:
        """Send one claimed delivery. Returns 'sent', 'retrying' or 'undelivered'. Never raises."""
        component = str(row.payload.get("component", ""))
        intent_ref = None
        if self._auditor is not None:
            intent_ref = await self._auditor.intent(bank_id=row.bank_id, incident_id=row.incident_id, delivery_id=row.delivery_id, channel=row.channel,
                                                    recipient=row.recipient, level=row.escalation_level, template_id=row.template_id or "",
                                                    severity=row.priority or "", component=component)
        error = ""
        try:
            await self._dispatcher.send(NotificationRequest(channel=row.channel, recipient=row.recipient, template_id=row.template_id or "",
                                                            context=row.payload, priority=row.priority or "P0", event_category="PLATFORM_HEALTH"))
        except Exception as exc:  # noqa: BLE001
            error = str(exc) or type(exc).__name__
        if self._auditor is not None:
            await self._auditor.outcome(bank_id=row.bank_id, incident_id=row.incident_id, delivery_id=row.delivery_id, channel=row.channel,
                                        succeeded=not error, attempt=row.attempt, intent_ref=intent_ref, error=error)
        if not error:
            await self._record(self._store.mark_sent(row.bank_id, row.delivery_id, provider_class="accepted"), row)
            return "sent"
        kind, clean = classify_failure(error), scrub_error(error, ERROR_MAX_CHARS)
        log.warning("alert_delivery.failed", bank_id=row.bank_id, channel=row.channel, attempt=row.attempt, kind=kind, error=clean)
        if row.attempt < self._policy.max_attempts:
            backoff = self._policy.backoff_seconds
            delay = backoff[min(row.attempt - 1, len(backoff) - 1)]
            await self._record(self._store.schedule_retry(row.bank_id, row.delivery_id, delay_seconds=delay, error=clean, provider_class=kind), row)
            return "retrying"
        await self._record(self._store.mark_undelivered(row.bank_id, row.delivery_id, error=clean, provider_class=kind), row)
        await self._fall_back(row, resolve_targets)
        return "undelivered"

    async def _record(self, awaitable: Awaitable[Any], row: DeliveryRow) -> None:
        try:
            await awaitable
        except Exception as exc:  # noqa: BLE001  - a bookkeeping failure must not raise out of a send
            log.error("alert_delivery.bookkeeping_failed", bank_id=row.bank_id, delivery_id=row.delivery_id, error=scrub_error(str(exc), ERROR_MAX_CHARS))

    async def _fall_back(self, row: DeliveryRow, resolve_targets: ResolveTargets) -> None:
        """One hop only: a fallback delivery that also fails is not itself replaced."""
        channels = [] if row.fallback_of else self._policy.fallbacks.get(row.channel, [])
        if self._auditor is not None:
            await self._auditor.lifecycle(AuditEventType.ALERT_ESCALATED, bank_id=row.bank_id, incident_id=row.incident_id, actor="system:alert-engine",
                                          detail={"reason": "delivery_failed", "from_channel": row.channel, "fallback_channels": channels,
                                                  "delivery_id": row.delivery_id})
        for channel in channels:
            try:
                targets = await resolve_targets(channel)
            except Exception:  # noqa: BLE001
                targets = []
            for target in targets:
                queued = await self._store.enqueue(bank_id=row.bank_id, incident_id=row.incident_id, occasion=f"fb:{row.delivery_id}",
                                                   level=row.escalation_level, channel=target.channel, recipient=target.recipient,
                                                   template_id=row.template_id or "", payload=row.payload, priority=row.priority or "P0",
                                                   fallback_of=row.delivery_id)
                if queued.created:
                    claimed = await self._store.claim(row.bank_id, queued.delivery_id, lease_seconds=self._policy.lease_seconds)
                    if claimed is not None:
                        await self._attempt(claimed, resolve_targets)
