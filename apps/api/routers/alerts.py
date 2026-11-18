"""
Alerts API: incidents, their deliveries, the delivery log, and acknowledge (docs/design/alerting-blueprint.md, sections 9 and 17).

All routes versioned under /v1/ops/alerts/. Read: ops_manager, bank_it_admin, compliance_officer. Acknowledge: ops_manager, bank_it_admin.
Recipients are shown masked only; the clear address is never returned. Every query is scoped to the caller's bank.
"""
from datetime import datetime
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.alerting.delivery import DeliveryStore
from shared.alerting.incidents import MAX_LIST, IncidentStore
from shared.audit.audit_event import AuditEventType
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/ops/alerts", tags=["Alerts v1"])

_READ_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer"})
_ACK_ROLES = frozenset({"ops_manager", "bank_it_admin"})

Severity = Literal["P0", "P1", "P2", "P3"]
IncidentState = Literal["OPEN", "ACKED", "RESOLVED"]
DeliveryStatus = Literal["PENDING", "SENDING", "SENT", "FAILED", "UNDELIVERED", "SKIPPED"]
Channel = Literal["email", "whatsapp", "bell", "sms", "webhook", "syslog"]


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    """The central auth chokepoint (session cookie, CSRF, bank scope), re-shaped for this router."""
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def require_read_role(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in _READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message("ALERT_API_ROLE_CANNOT_READ"))
    return user


def require_ack_role(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in _ACK_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message("ALERT_API_ROLE_CANNOT_ACK"))
    return user


# ── Models ───────────────────────────────────────────────────────────────────

class IncidentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    incident_id: str
    alert_id: str
    component: str = ""
    severity: Severity
    state: IncidentState
    scope_level: str = "BANK"
    summary: str
    opened_at: datetime
    acked_at: Optional[datetime] = None
    acked_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    notification_count: int = 0


class IncidentDetailRecord(IncidentSummary):
    category: str = ""
    pu_id: Optional[str] = None
    smb_id: Optional[str] = None
    impact: str = ""
    root_cause_category: Optional[str] = None
    resolved_by: Optional[str] = None
    last_notified_at: Optional[datetime] = None
    escalation_level: int = 0


class DeliverySummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    delivery_id: str
    incident_id: Optional[str] = None
    escalation_level: int = 0
    channel: str
    recipient_ref: str                        # masked; the address itself is never returned
    template_id: Optional[str] = None
    status: DeliveryStatus
    attempt: int = 0
    next_attempt_at: Optional[datetime] = None
    provider_class: Optional[str] = None
    error: Optional[str] = None
    fallback_of: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class IncidentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    incidents: list[IncidentSummary] = []
    next_cursor: Optional[str] = None


class DeliveryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    deliveries: list[DeliverySummary] = []
    next_cursor: Optional[str] = None


class IncidentDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    incident: IncidentDetailRecord
    deliveries: list[DeliverySummary] = []


class AcknowledgeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    incident_id: str
    state: IncidentState
    acknowledged_by: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pool(request: Request) -> Any:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    return pool


def _bad_cursor() -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=get_message("ALERT_API_BAD_CURSOR"))


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    request: Request,
    limit: int = Query(50, ge=1, le=MAX_LIST),
    cursor: Optional[str] = None,
    state: Optional[IncidentState] = None,
    severity: Optional[Severity] = None,
    component: Optional[str] = Query(None, max_length=80),
    user: dict = Depends(require_read_role),
) -> IncidentListResponse:
    try:
        page = await IncidentStore(_pool(request)).list_incidents(user["bank_id"], limit=limit, cursor=cursor, state=state, severity=severity,
                                                                    component=component)
    except ValueError:
        raise _bad_cursor()
    return IncidentListResponse(incidents=[IncidentSummary(**row) for row in page.items], next_cursor=page.next_cursor)


@router_v1.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(request: Request, incident_id: str, user: dict = Depends(require_read_role)) -> IncidentDetailResponse:
    pool = _pool(request)
    record = await IncidentStore(pool).get(user["bank_id"], incident_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_NOT_FOUND"))
    deliveries = await DeliveryStore(pool).list_deliveries(user["bank_id"], limit=MAX_LIST, incident_id=incident_id)
    return IncidentDetailResponse(incident=IncidentDetailRecord(**record), deliveries=[DeliverySummary(**row) for row in reversed(deliveries.items)])


@router_v1.get("/deliveries", response_model=DeliveryListResponse)
async def list_deliveries(
    request: Request,
    limit: int = Query(50, ge=1, le=MAX_LIST),
    cursor: Optional[str] = None,
    delivery_status: Optional[DeliveryStatus] = Query(None, alias="status"),
    channel: Optional[Channel] = None,
    incident_id: Optional[str] = Query(None, max_length=80),
    user: dict = Depends(require_read_role),
) -> DeliveryListResponse:
    try:
        page = await DeliveryStore(_pool(request)).list_deliveries(user["bank_id"], limit=limit, cursor=cursor, status=delivery_status,
                                                                    channel=channel, incident_id=incident_id)
    except ValueError:
        raise _bad_cursor()
    return DeliveryListResponse(deliveries=[DeliverySummary(**row) for row in page.items], next_cursor=page.next_cursor)


@router_v1.post("/incidents/{incident_id}/acknowledge", response_model=AcknowledgeResponse)
async def acknowledge_incident(request: Request, incident_id: str, user: dict = Depends(require_ack_role)) -> AcknowledgeResponse:
    store = IncidentStore(_pool(request))
    bank_id, who = user["bank_id"], user["user_id"]
    if not await store.acknowledge(bank_id, incident_id, who):
        if await store.get(bank_id, incident_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_NOT_FOUND"))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=get_message("ALERT_API_ALREADY_ACKNOWLEDGED"))
    auditor = getattr(request.app.state, "alert_auditor", None)
    if auditor is not None:
        await auditor.lifecycle(AuditEventType.ALERT_ACKNOWLEDGED, bank_id=bank_id, incident_id=incident_id, actor=who, detail={})
    log.info("alerts.acknowledged", bank_id=bank_id, incident_id=incident_id)
    return AcknowledgeResponse(incident_id=incident_id, state="ACKED", acknowledged_by=who)
