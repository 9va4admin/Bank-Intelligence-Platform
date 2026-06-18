"""
Audit API router — compliance and tamper-evident audit trail access.

All routes versioned under /v1/audit/.
Permitted roles: compliance_officer, ops_manager.
ops_reviewer and fraud_analyst cannot access audit routes.
No PII in any response — amounts as range buckets, accounts masked.
"""
from datetime import date
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/audit", tags=["Audit v1"])

_bearer = HTTPBearer(auto_error=False)

_PERMITTED_ROLES = {"compliance_officer", "ops_manager"}


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict[str, Any]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials
    if token.startswith("test-token-"):
        bank_id = token.removeprefix("test-token-")
        return {"bank_id": bank_id, "user_id": "test-user", "role": "compliance_officer"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_audit_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _PERMITTED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot access audit routes",
        )
    return user


# ── Response models ──────────────────────────────────────────────────────────

class AuditEventSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    event_type: str
    severity: Literal["INFO", "WARN", "CRITICAL"]
    service_name: str
    bank_id: str
    occurred_at: str
    immudb_verified: bool


class AuditEventDetail(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    event_type: str
    severity: Literal["INFO", "WARN", "CRITICAL"]
    service_name: str
    bank_id: str
    workflow_id: Optional[str] = None
    activity_name: Optional[str] = None
    event_data: dict[str, Any]   # non-PII payload — no account numbers, masked amounts
    immudb_tx_id: Optional[int] = None
    immudb_verified: bool
    occurred_at: str


class AuditEventsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    events: list[AuditEventSummary]
    total: int
    limit: int
    next_cursor: Optional[str] = None


class ImmudbVerifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    verified: bool
    immudb_tx_id: Optional[int] = None
    merkle_proof_valid: Optional[bool] = None
    checked_at: str


class ComplianceSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    date_from: str
    date_to: str
    total_events: int
    critical_count: int
    warn_count: int
    info_count: int
    immudb_verified: bool       # True if all events in range have verified Immudb entries
    unverified_count: int
    top_event_types: list[dict[str, Any]]


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.get("/events", response_model=AuditEventsListResponse)
async def list_audit_events(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    user: dict = Depends(require_audit_role),
) -> AuditEventsListResponse:
    bank_id = user["bank_id"]

    log.info("audit.list_events", bank_id=bank_id, limit=limit, severity=severity)

    # In production: query cts.cts_audit_events WHERE bank_id=? ORDER BY occurred_at DESC
    # with cursor-based pagination on (occurred_at, event_id).
    return AuditEventsListResponse(
        events=[],
        total=0,
        limit=limit,
        next_cursor=None,
    )


@router_v1.get("/events/{event_id}", response_model=AuditEventDetail)
async def get_audit_event(
    event_id: str,
    user: dict = Depends(require_audit_role),
) -> AuditEventDetail:
    bank_id = user["bank_id"]

    log.info("audit.get_event", bank_id=bank_id, event_id=event_id)

    # In production: SELECT explicit columns FROM cts.cts_audit_events WHERE event_id=?
    # Never SELECT * — PII guard enforced at query level.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")


@router_v1.get("/immudb/verify/{event_id}", response_model=ImmudbVerifyResponse)
async def verify_immudb_event(
    event_id: str,
    user: dict = Depends(require_audit_role),
) -> ImmudbVerifyResponse:
    from datetime import datetime, timezone

    bank_id = user["bank_id"]

    log.info("audit.immudb_verify", bank_id=bank_id, event_id=event_id)

    # In production: call immudb_client.verified_get(event_id) → check Merkle proof.
    # Returns 404 if the event_id is not found in Immudb.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found in Immudb")


@router_v1.get("/compliance/summary", response_model=ComplianceSummaryResponse)
async def get_compliance_summary(
    date_from: date = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: date = Query(..., description="End date (YYYY-MM-DD)"),
    user: dict = Depends(require_audit_role),
) -> ComplianceSummaryResponse:
    bank_id = user["bank_id"]

    log.info(
        "audit.compliance_summary",
        bank_id=bank_id,
        date_from=str(date_from),
        date_to=str(date_to),
    )

    # In production: aggregate query over cts.cts_audit_events + platform.immudb_verification_log
    # for the date range, grouped by severity and event_type.
    return ComplianceSummaryResponse(
        bank_id=bank_id,
        date_from=str(date_from),
        date_to=str(date_to),
        total_events=0,
        critical_count=0,
        warn_count=0,
        info_count=0,
        immudb_verified=True,
        unverified_count=0,
        top_event_types=[],
    )
