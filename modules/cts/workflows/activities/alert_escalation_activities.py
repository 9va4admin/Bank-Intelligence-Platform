"""Activities for the alert escalation workflow (docs/design/alerting-1b-plan.md): plan the escalation, and run one step (or reminder) through the delivery engine.

Both never raise for ordinary trouble (a database or engine that is down): they say so in their result and the workflow decides. Settings (Layer 3):
alerting.escalation_max_reminders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from pydantic import BaseModel
from temporalio import activity

from shared.alerting.audience import deliverable_targets
from shared.alerting.audit import SYSTEM_ACTOR, scrub_error
from shared.alerting.incidents import IncidentStore
from shared.audit.audit_event import AuditEventType
from shared.messages import get_message
from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)

DEFAULT_MAX_REMINDERS = 48
ESCALATION_TEMPLATE = "PLATFORM_HEALTH_ALERT"


class PlanInput(BaseModel):
    bank_id: str
    incident_id: str


class PlanStep(BaseModel):
    level: int
    after_minutes: int


class EscalationPlan(BaseModel):
    state: str = "OPEN"                    # OPEN | STOPPED (not open any more) | UNAVAILABLE (no database)
    steps: list[PlanStep] = []
    repeat_minutes: Optional[int] = None
    max_reminders: int = DEFAULT_MAX_REMINDERS


class EscalationStepInput(BaseModel):
    bank_id: str
    incident_id: str
    level: int
    kind: Literal["ESCALATE", "REMIND"] = "ESCALATE"
    sequence: int = 0                      # which reminder this is (so each reminder is its own notification)


class EscalationStepResult(BaseModel):
    stopped: bool = False                  # the incident is no longer open
    notified: int = 0
    degraded: bool = False


async def _int_setting(config_service: Any, key: str, default: int) -> int:
    try:
        return int(await config_service.get(key))
    except Exception:
        return default


def _services(db_pool: Any, config_service: Any, bank_id: str, store: Any, routing: Any):
    if store is None:
        store = IncidentStore(db_pool)
    if routing is None:
        from shared.alerting.factory import build_routing_service
        routing = build_routing_service(config_service, bank_id, db_pool)
    return store, routing


@activity.defn
async def plan_escalation(inp: PlanInput, db_pool=None, config_service=None, store=None, routing=None) -> EscalationPlan:
    with tracer.start_as_current_span("activity.plan_escalation") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if store is None and db_pool is None:
            return EscalationPlan(state="UNAVAILABLE")
        store, routing = _services(db_pool, config_service, inp.bank_id, store, routing)
        incident = await store.get(inp.bank_id, inp.incident_id)
        if incident is None or incident.get("state") != "OPEN":
            return EscalationPlan(state="STOPPED")
        routed = await routing.route_incident(incident, datetime.now(timezone.utc))
        steps = [PlanStep(level=s.level, after_minutes=s.after_minutes) for s in routed.routing.steps if s.level >= 1]
        return EscalationPlan(state="OPEN", steps=steps, repeat_minutes=routed.routing.repeat_minutes,
                              max_reminders=await _int_setting(config_service, "alerting.escalation_max_reminders", DEFAULT_MAX_REMINDERS))


@activity.defn
async def run_escalation_step(inp: EscalationStepInput, db_pool=None, config_service=None, delivery_engine=None, alert_auditor=None, store=None,
                              routing=None) -> EscalationStepResult:
    with tracer.start_as_current_span("activity.run_escalation_step") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if delivery_engine is None or (store is None and db_pool is None):
            return EscalationStepResult(degraded=True)
        try:
            store, routing = _services(db_pool, config_service, inp.bank_id, store, routing)
            incident = await store.get(inp.bank_id, inp.incident_id)
            if incident is None or incident.get("state") != "OPEN":
                return EscalationStepResult(stopped=True)
            now = datetime.now(timezone.utc)
            routed = await routing.route_incident(incident, now)
            wanted = [s for s in routed.routing.steps if (s.level == inp.level if inp.kind == "ESCALATE" else s.level <= inp.level)]
            targets, warnings = await deliverable_targets([t for s in wanted for t in s.targets], pool=db_pool, config_service=config_service, bank_id=inp.bank_id)
            warnings = list(routed.routing.warnings) + [w for w in warnings if w not in routed.routing.warnings]
            if targets:
                opened = incident.get("opened_at")
                context = {"bank_id": inp.bank_id, "event_type": f"ESCALATION_L{inp.level}", "severity": incident["severity"], "priority": incident["severity"],
                           "component": incident.get("component", ""),
                           "message": get_message("ALERT_ESCALATION_MESSAGE", level=inp.level, summary=str(incident.get("summary", ""))),
                           "incident_id": inp.incident_id, "occurred_at": opened.timestamp() if opened else now.timestamp()}

                async def no_fallback(_channel: str) -> list:
                    return []
                await delivery_engine.submit(bank_id=inp.bank_id, incident_id=inp.incident_id, occasion=f"esc{inp.level}" if inp.kind == "ESCALATE" else f"rem{inp.sequence}",
                                             targets=targets, template_id=ESCALATION_TEMPLATE, context=context, priority=incident["severity"],
                                             component=incident.get("component", ""), resolve_targets=no_fallback, level=inp.level)
            if inp.kind == "ESCALATE":
                await store.set_escalation_level(inp.bank_id, inp.incident_id, inp.level)
            if alert_auditor is not None:
                await alert_auditor.lifecycle(AuditEventType.ALERT_ESCALATED, bank_id=inp.bank_id, incident_id=inp.incident_id, actor=SYSTEM_ACTOR,
                                              detail={"level": inp.level, "kind": inp.kind, "notified": len(targets), "warnings": warnings})
            return EscalationStepResult(notified=len(targets))
        except Exception as exc:  # noqa: BLE001
            log.warning("run_escalation_step.error", bank_id=inp.bank_id, incident_id=inp.incident_id, error=scrub_error(str(exc), 200))
            return EscalationStepResult(degraded=True)
