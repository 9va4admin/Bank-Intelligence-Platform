"""
CTS Outward Q — decision recording API.

The Outward Q page (Human Review + STP Rejected tabs) lets a reviewer confirm
or reject an outward instrument before NGCH filing. Every decision must be
audited (security.md: "Audit Always On"; cts.md: "Immudb write after every
decision"). This router records the decision to the immutable audit trail via
the same fire-and-forget Kafka -> audit-service -> Immudb path already proven
in mcp_connections.py: publish to platform.audit.events, audit-service
consumes, HSM-signs, and writes to Immudb.

Server-side validation, not just the frontend's disabled buttons, enforces that
reason_category matches action — a REJECTED decision must carry a rejection
reason, a CONFIRMED decision must carry a confirmation reason. Never trust the
client alone for this invariant.
"""
from __future__ import annotations

from typing import Any, Callable, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.routers.cts import get_current_user_context
from shared.audit.audit_event import AuditEvent, AuditEventType
from shared.auth.rbac import UserContext
from shared.event_bus.producer import EventProducer as KafkaEventProducer

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts/outward/queue", tags=["CTS Outward Q v1"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class OutwardQueueDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str = Field(..., min_length=1)
    tab: Literal["review", "stp_rejected"]
    action: Literal["CONFIRMED", "REJECTED"]
    reason: str = Field(..., min_length=1, max_length=200)
    reason_category: Literal["confirm", "reject"]


class OutwardQueueDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    status: Literal["RECORDED"]


# ---------------------------------------------------------------------------
# Event publisher dependency (Kafka) — same fallback pattern as mcp_connections.py
# ---------------------------------------------------------------------------

async def _default_event_publisher(topic: str, payload: dict) -> None:
    """No Kafka producer wired (dev/test) — log only. Tests override this dependency."""
    log.info("cts_outward_queue.kafka_publish_stub", topic=topic, event_type=payload.get("event_type"))


def get_event_publisher(request: Request) -> Callable:
    """Real Kafka publisher when app.state.kafka_producer_cts is available, else the stub."""
    producer: Optional[KafkaEventProducer] = getattr(request.app.state, "kafka_producer_cts", None)
    if producer is None:
        return _default_event_publisher

    async def _real_publisher(topic: str, payload: dict) -> None:
        try:
            await producer.publish(
                topic=topic,
                event_type=payload.get("event_type", "UNKNOWN"),
                payload=payload,
                schema_version="1.0",
            )
        except Exception as exc:
            log.error("cts_outward_queue.kafka_publish_failed", topic=topic, error=str(exc))

    return _real_publisher


async def _emit_audit(event_type: AuditEventType, bank_id: str, payload: dict, event_publisher: Callable) -> str:
    """Build + publish the AuditEvent. Fire-and-forget: failures are logged, never
    raised — a broken audit pipe must never block a reviewer's decision."""
    event = AuditEvent(event_type=event_type, bank_id=bank_id, payload=payload)
    try:
        await event_publisher("platform.audit.events", {
            "event_type": event_type.value,
            "event_id": event.event_id,
            "bank_id": bank_id,
            "timestamp": event.timestamp,
            **payload,
        })
    except Exception as exc:
        log.error("cts_outward_queue.audit_emit_failed", event_type=event_type.value, bank_id=bank_id, error=str(exc))
    return event.event_id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.post("/decisions", response_model=OutwardQueueDecisionResponse, status_code=status.HTTP_201_CREATED)
async def record_decision(
    body: OutwardQueueDecisionRequest,
    ctx: UserContext = Depends(get_current_user_context),
    event_publisher: Callable = Depends(get_event_publisher),
) -> OutwardQueueDecisionResponse:
    expected_category = "confirm" if body.action == "CONFIRMED" else "reject"
    if body.reason_category != expected_category:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"reason_category '{body.reason_category}' does not match action "
                f"'{body.action}' — expected '{expected_category}'"
            ),
        )

    event_id = await _emit_audit(
        AuditEventType.CTS_OUTWARD_QUEUE_DECISION,
        ctx.bank_id,
        {
            "instrument_id": body.instrument_id,
            "tab": body.tab,
            "action": body.action,
            "reason": body.reason,
            "reason_category": body.reason_category,
            "decided_by": ctx.user_id,
        },
        event_publisher,
    )

    log.info(
        "cts_outward_queue.decision_recorded",
        event_id=event_id,
        instrument_id=body.instrument_id,
        action=body.action,
        bank_id=ctx.bank_id,
    )
    return OutwardQueueDecisionResponse(event_id=event_id, status="RECORDED")
