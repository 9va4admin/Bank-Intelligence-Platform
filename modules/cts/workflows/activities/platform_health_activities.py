"""
PlatformHealthCheckWorkflow activities — alert engine for the ASTRA Ops Dashboard.

Three activities:
  check_iet_risk_for_alert    — query IET near-breach count from YugabyteDB
  check_human_review_for_alert — query human review queue depth + avg wait
  dispatch_platform_alert     — send alert via NotificationDispatcher → WhatsApp + email

All activities degrade gracefully when db_pool or dispatcher is None (never crash).
IET near-breach > 0 → always P0 (bypass debouncer).
Human review threshold breaches → P1/WARN.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.health.probes import build_specs, run_probe
from modules.cts.health.state_machine import ComponentState, Event, Thresholds, step
from shared.alerting.audit import SYSTEM_ACTOR, scrub_error
from shared.alerting.engine import Target
from shared.alerting.incidents import IncidentStore, dedup_key_for, is_resolution
from shared.audit.audit_event import AuditEventType
from shared.notifications.dispatcher import NotificationRequest

from shared.observability.otel_setup import get_tracer
from shared.messages import get_message

log = structlog.get_logger()
tracer = get_tracer(__name__)


# ---------------------------------------------------------------------------
# Input / result models
# ---------------------------------------------------------------------------

class CheckIETInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str


class IETCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str = ""
    near_breach_count: int = 0
    in_processing_count: int = 0
    needs_alert: bool = False
    alert_priority: str = "P0"
    degraded: bool = False


class CheckHRInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    max_depth: int          # alert when queue_depth > max_depth
    max_wait_minutes: float # alert when avg_wait > max_wait_minutes


class HRCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str = ""
    queue_depth: int = 0
    avg_wait_minutes: float = 0.0
    needs_alert: bool = False
    alert_severity: str = "WARN"
    alert_reason: str = ""  # "QUEUE_DEPTH" | "WAIT_TIME"
    degraded: bool = False


class DispatchAlertInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    event_type: str    # "IET_BREACH_RISK" | "HUMAN_REVIEW_QUEUE_DEEP"
    severity: str      # "CRITICAL" | "WARN"
    priority: str      # "P0" | "P1" (P0 = never debounced)
    message: str
    component: str = ""                          # which platform component (infrastructure alerts)
    template: str = "PLATFORM_HEALTH_ALERT"      # PLATFORM_HEALTH_ALERT | PLATFORM_HEALTH_RECOVERED
    down_for: str = ""                           # recovery mails: how long it was down
    incident_id: str = ""                        # the incident this alert belongs to (audit correlation); empty = a fresh correlation id
    occurred_at: float = 0.0                     # when it happened (epoch seconds); 0 = now
    occasion: str = ""                           # identifies this notification (a reminder is a new occasion); a retried activity repeats it, so nothing is sent twice


class DispatchAlertResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    sent: bool = False
    degraded: bool = False
    queued_for_retry: int = 0     # deliveries that failed their first attempt and will be retried by the outbox


class CheckVaultCoverageInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    min_coverage_pct: float  # alert when Redis coverage drops below this (e.g. 95.0)


class VaultCoverageCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str = ""
    yugabyte_accounts: int = 0
    redis_sig_keys: int = 0
    coverage_pct: float = 100.0
    gap_accounts: int = 0
    needs_alert: bool = False
    alert_severity: str = "WARN"
    degraded: bool = False


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

@activity.defn
async def check_iet_risk_for_alert(
    inp: CheckIETInput,
    db_pool=None,
) -> IETCheckResult:
    """
    Query YugabyteDB for cheques whose IET deadline is within 30 seconds.
    Any near-breach count > 0 means a P0 alert must fire.
    Degrades gracefully when db_pool is None — returns needs_alert=False, degraded=True.
    """
    with tracer.start_as_current_span("activity.check_iet_risk_for_alert") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if db_pool is None:
            log.warning("check_iet_risk_for_alert.degraded", bank_id=inp.bank_id, reason="db_pool_none")
            return IETCheckResult(bank_id=inp.bank_id, degraded=True)

        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE status = 'IN_PROCESSING'
                              AND iet_deadline < NOW() + INTERVAL '30 seconds'
                              AND iet_deadline > NOW()
                        ) AS near_breach,
                        COUNT(*) FILTER (WHERE status = 'IN_PROCESSING') AS in_processing
                    FROM cts.cheque_instruments
                    WHERE bank_id = $1
                    """,
                    inp.bank_id,
                )
            near_breach = int(row["near_breach"] or 0)
            in_processing = int(row["in_processing"] or 0)
            needs_alert = near_breach > 0
            log.info(
                "check_iet_risk_for_alert.done",
                bank_id=inp.bank_id,
                near_breach=near_breach,
                in_processing=in_processing,
                needs_alert=needs_alert,
            )
            return IETCheckResult(
                bank_id=inp.bank_id,
                near_breach_count=near_breach,
                in_processing_count=in_processing,
                needs_alert=needs_alert,
                alert_priority="P0",
                degraded=False,
            )
        except Exception as exc:
            log.warning("check_iet_risk_for_alert.error", bank_id=inp.bank_id, error=str(exc))
            return IETCheckResult(bank_id=inp.bank_id, degraded=True)


@activity.defn
async def check_human_review_for_alert(
    inp: CheckHRInput,
    db_pool=None,
) -> HRCheckResult:
    """
    Query YugabyteDB for human review queue depth and average wait time.
    Alerts (WARN) when either exceeds the configurable thresholds in inp.
    Degrades gracefully when db_pool is None.
    """
    with tracer.start_as_current_span("activity.check_human_review_for_alert") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if db_pool is None:
            log.warning("check_human_review_for_alert.degraded", bank_id=inp.bank_id, reason="db_pool_none")
            return HRCheckResult(bank_id=inp.bank_id, degraded=True)

        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) AS queue_depth,
                        COALESCE(
                            AVG(EXTRACT(EPOCH FROM (NOW() - review_queued_at)) / 60.0),
                            0
                        ) AS avg_wait
                    FROM cts.cheque_instruments
                    WHERE bank_id = $1
                      AND status = 'HUMAN_REVIEW'
                    """,
                    inp.bank_id,
                )
            queue_depth = int(row["queue_depth"] or 0)
            avg_wait = float(row["avg_wait"] or 0.0)

            needs_alert = False
            alert_reason = ""

            if queue_depth > inp.max_depth:
                needs_alert = True
                alert_reason = "QUEUE_DEPTH"
            elif avg_wait > inp.max_wait_minutes:
                needs_alert = True
                alert_reason = "WAIT_TIME"

            log.info(
                "check_human_review_for_alert.done",
                bank_id=inp.bank_id,
                queue_depth=queue_depth,
                avg_wait_minutes=round(avg_wait, 1),
                needs_alert=needs_alert,
            )
            return HRCheckResult(
                bank_id=inp.bank_id,
                queue_depth=queue_depth,
                avg_wait_minutes=avg_wait,
                needs_alert=needs_alert,
                alert_severity="WARN",
                alert_reason=alert_reason,
                degraded=False,
            )
        except Exception as exc:
            log.warning("check_human_review_for_alert.error", bank_id=inp.bank_id, error=str(exc))
            return HRCheckResult(bank_id=inp.bank_id, degraded=True)


async def _recipients(config_service: Any, bank_id: str, key: str = "alerts.email_recipients") -> list[str]:
    """Alert recipients from hot-reloadable config (a JSON list or comma-separated). Without a config service (older callers and tests) the former
    per-bank mailbox is kept for email."""
    if config_service is None:
        return [f"ops-alerts@{bank_id}.internal"] if key == "alerts.email_recipients" else []
    try:
        raw = await config_service.get(key)
    except Exception:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw or "").strip()
        try:
            items = json.loads(text) if text.startswith("[") else text.split(",")
        except ValueError:
            items = text.split(",")
    return [str(x).strip() for x in items if str(x).strip()]


_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


async def _whatsapp_recipients(config_service: Any, bank_id: str, priority: str) -> list[str]:
    """Phones to message: only alerts at or above alerts.whatsapp_min_priority (default P0, so recoveries and slow warnings stay on email)."""
    if config_service is None:
        return []
    floor = "P0"
    try:
        floor = str(await config_service.get("alerts.whatsapp_min_priority")).strip().upper() or "P0"
    except Exception:
        pass
    if _PRIORITY_RANK.get(priority, 9) > _PRIORITY_RANK.get(floor, 0):
        return []
    return await _recipients(config_service, bank_id, "alerts.whatsapp_recipients")


@activity.defn
async def dispatch_platform_alert(
    inp: DispatchAlertInput,
    dispatcher=None,
    config_service=None,
    alert_auditor=None,
    delivery_engine=None,
) -> DispatchAlertResult:
    """
    Send an alert via NotificationDispatcher (email), one mail per configured recipient. With an auditor, an intent record is written before each send
    and an outcome record after it; an audit problem never stops or delays the alert.
    P0 alerts bypass the debouncer. Degrades (sent=False) when there is no dispatcher or no recipient is configured; one recipient failing
    never stops the others.
    """
    with tracer.start_as_current_span("activity.dispatch_platform_alert") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if dispatcher is None:
            log.warning("dispatch_platform_alert.degraded", bank_id=inp.bank_id, event_type=inp.event_type, reason="dispatcher_none")
            return DispatchAlertResult(sent=False, degraded=True)
        recipients = await _recipients(config_service, inp.bank_id)
        phones = await _whatsapp_recipients(config_service, inp.bank_id, inp.priority)
        if not recipients and not phones:
            log.warning("dispatch_platform_alert.degraded", bank_id=inp.bank_id, event_type=inp.event_type, reason="no_recipients_configured")
            return DispatchAlertResult(sent=False, degraded=True)

        correlation_id = inp.incident_id or f"adhoc-{uuid.uuid4().hex}"
        context = {"bank_id": inp.bank_id, "event_type": inp.event_type, "severity": inp.severity, "message": inp.message,
                   "component": inp.component, "down_for": inp.down_for, "incident_id": inp.incident_id, "occurred_at": inp.occurred_at or time.time(),
                   "priority": inp.priority}
        if delivery_engine is not None:
            async def resolve_targets(channel: str) -> list[Target]:
                """Who a fallback channel reaches: that channel's configured recipients, whatever their priority floor (a failed delivery is itself serious)."""
                if channel == "email":
                    return [Target("email", r) for r in await _recipients(config_service, inp.bank_id)]
                if channel == "whatsapp":
                    return [Target("whatsapp", r) for r in await _recipients(config_service, inp.bank_id, "alerts.whatsapp_recipients")]
                return []
            submitted = await delivery_engine.submit(
                bank_id=inp.bank_id, incident_id=correlation_id, occasion=inp.occasion or uuid.uuid4().hex,
                targets=[Target("email", r) for r in recipients] + [Target("whatsapp", r) for r in phones],
                template_id=inp.template, context=context, priority=inp.priority, component=inp.component, resolve_targets=resolve_targets)
            log.info("dispatch_platform_alert.submitted", bank_id=inp.bank_id, event_type=inp.event_type, priority=inp.priority,
                     sent=submitted.sent, retrying=submitted.retrying, undelivered=submitted.undelivered)
            return DispatchAlertResult(sent=submitted.sent > 0, queued_for_retry=submitted.retrying)
        delivered = 0
        for channel, targets in (("email", recipients), ("whatsapp", phones)):
            for recipient in targets:
                delivery_id = uuid.uuid4().hex
                intent_ref = None
                if alert_auditor is not None:
                    intent_ref = await alert_auditor.intent(
                        bank_id=inp.bank_id, incident_id=correlation_id, delivery_id=delivery_id, channel=channel, recipient=recipient, level=0,
                        template_id=inp.template, severity=inp.priority, component=inp.component)
                error = ""
                try:
                    await dispatcher.send(NotificationRequest(
                        channel=channel, recipient=recipient, template_id=inp.template, context=context,
                        priority=inp.priority, event_category="PLATFORM_HEALTH",
                    ))
                    delivered += 1
                except Exception as exc:
                    error = str(exc) or type(exc).__name__
                    log.warning("dispatch_platform_alert.error", bank_id=inp.bank_id, event_type=inp.event_type, channel=channel,
                                error=scrub_error(error, 200))
                if alert_auditor is not None:
                    await alert_auditor.outcome(bank_id=inp.bank_id, incident_id=correlation_id, delivery_id=delivery_id, channel=channel,
                                                succeeded=not error, attempt=1, intent_ref=intent_ref, error=error)
        if delivered:
            log.info("dispatch_platform_alert.sent", bank_id=inp.bank_id, event_type=inp.event_type, severity=inp.severity,
                     priority=inp.priority, recipients=delivered)
        return DispatchAlertResult(sent=delivered > 0, degraded=False)


class ProcessOutboxInput(BaseModel):
    bank_id: str


class ProcessOutboxResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    attempted: int = 0
    sent: int = 0
    retrying: int = 0
    undelivered: int = 0
    degraded: bool = False


@activity.defn
async def process_alert_outbox(inp: ProcessOutboxInput, delivery_engine=None, config_service=None) -> ProcessOutboxResult:
    """Retry the deliveries that are due and recover ones whose sender died. Run every monitor tick; never raises."""
    with tracer.start_as_current_span("activity.process_alert_outbox") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if delivery_engine is None:
            return ProcessOutboxResult(degraded=True)

        async def resolve_targets(channel: str) -> list[Target]:
            if channel == "email":
                return [Target("email", r) for r in await _recipients(config_service, inp.bank_id)]
            if channel == "whatsapp":
                return [Target("whatsapp", r) for r in await _recipients(config_service, inp.bank_id, "alerts.whatsapp_recipients")]
            return []
        try:
            res = await delivery_engine.process_due(inp.bank_id, resolve_targets=resolve_targets)
        except Exception as exc:  # noqa: BLE001
            log.warning("process_alert_outbox.error", bank_id=inp.bank_id, error=scrub_error(str(exc), 200))
            return ProcessOutboxResult(degraded=True)
        return ProcessOutboxResult(attempted=res.attempted, sent=res.sent, retrying=res.retrying, undelivered=res.undelivered)


# ---------------------------------------------------------------------------
# Incidents: an alert opens, updates or resolves one
# ---------------------------------------------------------------------------

class IncidentRecordResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    incident_id: str = ""         # empty: no incident (nothing was open to resolve, or the incident store was unavailable)
    created: bool = False
    resolved: bool = False
    degraded: bool = False


@activity.defn
async def record_alert_incident(inp: DispatchAlertInput, db_pool=None, alert_auditor=None, store=None) -> IncidentRecordResult:
    """Open, update or resolve the incident this alert belongs to, and audit it. Never raises: the incident store being down must not stop an alert."""
    with tracer.start_as_current_span("activity.record_alert_incident") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if store is None:
            if db_pool is None:
                log.warning("record_alert_incident.degraded", bank_id=inp.bank_id, reason="db_pool_none")
                return IncidentRecordResult(degraded=True)
            store = IncidentStore(db_pool)
        key = dedup_key_for(inp.event_type, inp.component)
        try:
            if is_resolution(inp.event_type):
                closed = await store.resolve(inp.bank_id, key, SYSTEM_ACTOR)
                if closed is None:
                    return IncidentRecordResult()
                if alert_auditor is not None:
                    await alert_auditor.lifecycle(AuditEventType.ALERT_RESOLVED, bank_id=inp.bank_id, incident_id=closed.incident_id,
                                                  actor=SYSTEM_ACTOR, detail={"component": closed.component, "severity": closed.severity,
                                                                              "duration_seconds": closed.duration_seconds})
                return IncidentRecordResult(incident_id=closed.incident_id, resolved=True)
            opened = await store.open_or_update(bank_id=inp.bank_id, dedup_key=key, alert_id=inp.event_type, component=inp.component,
                                                severity=inp.priority, summary=inp.message)
            if alert_auditor is not None and (opened.created or opened.severity_raised):
                event = AuditEventType.ALERT_RAISED if opened.created else AuditEventType.ALERT_UPDATED
                await alert_auditor.lifecycle(event, bank_id=inp.bank_id, incident_id=opened.incident_id, actor=SYSTEM_ACTOR,
                                              detail={"component": inp.component, "severity": opened.severity, "alert_id": inp.event_type})
            return IncidentRecordResult(incident_id=opened.incident_id, created=opened.created)
        except Exception as exc:  # noqa: BLE001
            log.warning("record_alert_incident.error", bank_id=inp.bank_id, event_type=inp.event_type, error=scrub_error(str(exc), 200))
            return IncidentRecordResult(degraded=True)


class StatusChange(BaseModel):
    component: str
    from_status: str
    to_status: str
    latency_ms: Optional[float] = None
    error: Optional[str] = None


def status_changes(prior: dict, new: dict) -> list[StatusChange]:
    """Components whose status differs from the previous tick (a first reading counts: UNKNOWN to its status)."""
    out: list[StatusChange] = []
    for component, state in new.items():
        before = prior.get(component)
        before = ComponentState.model_validate(before) if isinstance(before, dict) else before
        from_status = before.status if before is not None else "UNKNOWN"
        if from_status != state.status:
            out.append(StatusChange(component=component, from_status=from_status, to_status=state.status,
                                    latency_ms=state.last_latency_ms, error=state.last_error))
    return out


# ---------------------------------------------------------------------------
# Infrastructure probes
# ---------------------------------------------------------------------------

class ProbeComponentsInput(BaseModel):
    bank_id: str
    states: dict[str, ComponentState] = {}


class ProbeComponentsResult(BaseModel):
    states: dict[str, ComponentState] = {}
    events: list[Event] = []
    probes_run: int = 0
    degraded: bool = False


async def _threshold(config_service: Any, key: str, default):
    try:
        return type(default)(await config_service.get(key))
    except Exception:
        return default


@activity.defn
async def probe_components(inp: ProbeComponentsInput, config_service=None, db_pool=None) -> ProbeComponentsResult:
    """Probe every configured dependency once (concurrently), run each result through the state machine, and return the new states plus
    the alert events. Thresholds are hot-reloadable config; a component removed from configuration drops out of the state."""
    with tracer.start_as_current_span("activity.probe_components") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if config_service is None:
            log.warning("probe_components.degraded", bank_id=inp.bank_id, reason="config_service_none")
            return ProbeComponentsResult(degraded=True)
        thresholds = Thresholds(
            down_after_failures=await _threshold(config_service, "platform_health.down_after_failures", 3),
            recover_after_successes=await _threshold(config_service, "platform_health.recover_after_successes", 2),
            slow_after=await _threshold(config_service, "platform_health.slow_after", 3),
            reminder_every_seconds=await _threshold(config_service, "platform_health.reminder_every_seconds", 1800.0),
        )
        specs = await build_specs(config_service)
        results = await asyncio.gather(*[run_probe(spec) for spec in specs])
        now = time.time()
        states: dict[str, ComponentState] = {}
        events: list[Event] = []
        for probe in results:
            prior = inp.states.get(probe.component)
            prior = ComponentState.model_validate(prior) if isinstance(prior, dict) else (prior or ComponentState())
            states[probe.component], new_events = step(prior, probe, now=now, thresholds=thresholds)
            events.extend(new_events)
        if db_pool is not None:                                  # history is best-effort: it never affects probing or alerting
            try:
                store = IncidentStore(db_pool)
                for change in status_changes(inp.states, states):
                    await store.record_state_change(inp.bank_id, change.component, change.from_status, change.to_status,
                                                    latency_ms=change.latency_ms, error=scrub_error(change.error or "", 200) or None, incident_id=None)
            except Exception as exc:  # noqa: BLE001
                log.warning("probe_components.history_failed", bank_id=inp.bank_id, error=scrub_error(str(exc), 200))
        return ProbeComponentsResult(states=states, events=events, probes_run=len(results))


@activity.defn
async def check_vault_redis_coverage_for_alert(
    inp: CheckVaultCoverageInput,
    db_pool=None,
    redis_client=None,
) -> VaultCoverageCheckResult:
    """
    Compare signature embedding count in YugabyteDB vs Redis.
    A Redis cold restart leaves Redis empty while YugabyteDB retains all embeddings.
    Fires a WARN/P1 alert when coverage_pct < inp.min_coverage_pct.
    Degrades gracefully when db_pool or redis_client is None.
    """
    with tracer.start_as_current_span("activity.check_vault_redis_coverage_for_alert") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if db_pool is None or redis_client is None:
            log.warning(
                "check_vault_redis_coverage_for_alert.degraded",
                bank_id=inp.bank_id,
                reason="db_pool_none" if db_pool is None else "redis_client_none",
            )
            return VaultCoverageCheckResult(bank_id=inp.bank_id, degraded=True)

        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(DISTINCT account_hash) AS accounts "
                    "FROM cts.signature_embeddings WHERE bank_id = $1",
                    inp.bank_id,
                )
            yugabyte_accounts = int(row["accounts"] or 0)

            redis_sig_keys = sum(
                1 for _ in redis_client.scan_iter(match=f"sig:{inp.bank_id}:*", count=1000)
            )

            if yugabyte_accounts > 0:
                coverage_pct = min(100.0, redis_sig_keys / yugabyte_accounts * 100)
            else:
                coverage_pct = 100.0  # no accounts in DB → nothing to warm → healthy

            gap_accounts = max(0, yugabyte_accounts - redis_sig_keys)
            needs_alert = coverage_pct < inp.min_coverage_pct

            log.info(
                "check_vault_redis_coverage_for_alert.done",
                bank_id=inp.bank_id,
                yugabyte_accounts=yugabyte_accounts,
                redis_sig_keys=redis_sig_keys,
                coverage_pct=round(coverage_pct, 1),
                gap_accounts=gap_accounts,
                needs_alert=needs_alert,
            )
            return VaultCoverageCheckResult(
                bank_id=inp.bank_id,
                yugabyte_accounts=yugabyte_accounts,
                redis_sig_keys=redis_sig_keys,
                coverage_pct=coverage_pct,
                gap_accounts=gap_accounts,
                needs_alert=needs_alert,
                alert_severity="WARN",
                degraded=False,
            )
        except Exception as exc:
            log.warning(
                "check_vault_redis_coverage_for_alert.error",
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return VaultCoverageCheckResult(bank_id=inp.bank_id, degraded=True)


    # ---------------------------------------------------------------------------
    # Scanner fleet health — branch OFFLINE alerting during clearing hours
    # ---------------------------------------------------------------------------

class CheckScannerFleetInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    offline_threshold_seconds: int = 90       # heartbeat older than this → branch OFFLINE
    clearing_start_hour_utc: int = 3          # 3 AM UTC = ~8:30 AM IST (CTS clearing opens)
    clearing_end_hour_utc: int = 14           # 2 PM UTC = ~7:30 PM IST (CTS clearing closes)
    force_utc_hour: Optional[int] = None      # test-only: override current UTC hour


class ScannerFleetCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str = ""
    offline_branches: list[str] = []
    offline_count: int = 0
    needs_alert: bool = False
    alert_severity: str = "WARN"
    skipped_outside_hours: bool = False
    degraded: bool = False


@activity.defn
async def check_scanner_fleet_for_alert(
    inp: CheckScannerFleetInput,
    db_pool=None,
) -> ScannerFleetCheckResult:
    """
    Query cts.scanner_tokens for branches where last_seen is stale (> offline_threshold_seconds).
    Only fires an alert when the current UTC hour falls within [clearing_start_hour_utc,
    clearing_end_hour_utc) — overnight gaps are expected and never paged.

    Degrades gracefully when db_pool is None.
    """
    with tracer.start_as_current_span("activity.check_scanner_fleet_for_alert") as span:
        span.set_attribute("bank_id", inp.bank_id)
        from datetime import datetime, timezone

        if db_pool is None:
            log.warning("check_scanner_fleet_for_alert.degraded", bank_id=inp.bank_id, reason="db_pool_none")
            return ScannerFleetCheckResult(bank_id=inp.bank_id, degraded=True)

        # Clearing-hours gate — no overnight false alarms
        utc_hour = inp.force_utc_hour if inp.force_utc_hour is not None else datetime.now(timezone.utc).hour
        in_clearing_window = inp.clearing_start_hour_utc <= utc_hour < inp.clearing_end_hour_utc

        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT branch_id "
                    "FROM cts.scanner_tokens "
                    "WHERE bank_id = $1 AND revoked = false "
                    "  AND (last_seen IS NULL OR last_seen < NOW() - ($2 * INTERVAL '1 second'))",
                    inp.bank_id,
                    inp.offline_threshold_seconds,
                )
            offline_branches = [r["branch_id"] for r in rows]
            offline_count = len(offline_branches)

            if not in_clearing_window:
                log.info(
                    "check_scanner_fleet_for_alert.outside_hours",
                    bank_id=inp.bank_id,
                    utc_hour=utc_hour,
                    offline_count=offline_count,
                )
                return ScannerFleetCheckResult(
                    bank_id=inp.bank_id,
                    offline_branches=offline_branches,
                    offline_count=offline_count,
                    needs_alert=False,
                    skipped_outside_hours=True,
                )

            needs_alert = offline_count > 0
            log.info(
                "check_scanner_fleet_for_alert.done",
                bank_id=inp.bank_id,
                offline_count=offline_count,
                needs_alert=needs_alert,
                utc_hour=utc_hour,
            )
            return ScannerFleetCheckResult(
                bank_id=inp.bank_id,
                offline_branches=offline_branches,
                offline_count=offline_count,
                needs_alert=needs_alert,
                alert_severity="WARN",
                skipped_outside_hours=False,
                degraded=False,
            )
        except Exception as exc:
            log.warning("check_scanner_fleet_for_alert.error", bank_id=inp.bank_id, error=str(exc))
            return ScannerFleetCheckResult(bank_id=inp.bank_id, degraded=True)


    # ---------------------------------------------------------------------------
    # Stuck workflow sweep — permanent production guard
    # ---------------------------------------------------------------------------

class StuckWorkflowSweepInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    max_age_minutes: int = 240   # terminate workflows running longer than this (4h default)
    task_queue_prefix: str = "cts-processing"
    dry_run: bool = False        # True = count only, no terminations


class StuckWorkflowSweepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    found: int = 0
    terminated: int = 0
    dry_run: bool = False
    degraded: bool = False


@activity.defn
async def sweep_stuck_workflows(inp: StuckWorkflowSweepInput) -> StuckWorkflowSweepResult:
    """
    Lists RUNNING CTS workflows for this bank that have exceeded max_age_minutes
    and terminates them. Called by PlatformHealthCheckWorkflow every 60s tick.

    Primary defence: execution_timeout on start_workflow (auto-terminates without
    this activity). This sweep is the belt-and-suspenders layer for workflows
    started without a timeout, stuck workers, or edge cases where Temporal's
    own timeout logic is delayed.

    Termination reason is written to the workflow's failure cause, which Temporal
    surfaces in the UI and history — fully auditable without touching Immudb.
    """
    with tracer.start_as_current_span("activity.sweep_stuck_workflows") as span:
        span.set_attribute("bank_id", inp.bank_id)
        from datetime import datetime, timezone, timedelta
        try:
            from temporalio.client import Client, WorkflowExecutionStatus
            client = await Client.connect(
                "localhost:17233",   # resolved from config_service in real dep injection
                namespace="default",
            )
        except Exception as exc:
            log.warning("sweep_stuck_workflows.client_error", bank_id=inp.bank_id, error=str(exc))
            return StuckWorkflowSweepResult(bank_id=inp.bank_id, degraded=True)

        cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=inp.max_age_minutes)
        prefix = f"cts-{inp.bank_id}-"
        found = 0
        terminated = 0

        try:
            query = (
                f'WorkflowType="ChequeProcessingWorkflow" AND '
                f'ExecutionStatus="Running" AND '
                f'TaskQueue="{inp.task_queue_prefix}-{inp.bank_id}"'
            )
            async for wf in client.list_workflows(query):
                if wf.start_time and wf.start_time < cutoff:
                    found += 1
                    if not inp.dry_run:
                        try:
                            handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
                            await handle.terminate(
                                reason=get_message("CTS_ASTRA_AUTO_TERMINATED_EXCEEDED_MIN", max_age_minutes=inp.max_age_minutes)
                            )
                            terminated += 1
                            log.warning(
                                "sweep_stuck_workflows.terminated",
                                bank_id=inp.bank_id,
                                workflow_id=wf.id,
                                age_minutes=round((datetime.now(tz=timezone.utc) - wf.start_time).seconds / 60),
                            )
                        except Exception as term_exc:
                            log.warning(
                                "sweep_stuck_workflows.terminate_failed",
                                workflow_id=wf.id,
                                error=str(term_exc),
                            )
        except Exception as exc:
            log.warning("sweep_stuck_workflows.list_error", bank_id=inp.bank_id, error=str(exc))
            return StuckWorkflowSweepResult(bank_id=inp.bank_id, degraded=True)

        if found > 0:
            log.warning(
                "sweep_stuck_workflows.complete",
                bank_id=inp.bank_id,
                found=found,
                terminated=terminated,
                dry_run=inp.dry_run,
            )
        return StuckWorkflowSweepResult(
            bank_id=inp.bank_id,
            found=found,
            terminated=terminated,
            dry_run=inp.dry_run,
        )
