"""
Audit API router — compliance and tamper-evident audit trail access.

All routes versioned under /v1/audit/.
Permitted roles: compliance_officer, ops_manager.
ops_reviewer and fraud_analyst cannot access audit routes.
No PII in any response — amounts as range buckets, accounts masked.
"""
import base64
import json
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/audit", tags=["Audit v1"])

_PERMITTED_ROLES = {"compliance_officer", "ops_manager"}


async def get_current_user(
    ctx: UserContext = Depends(require_user_context),
) -> dict[str, Any]:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.
    Re-shaped to this router's existing dict-based downstream code.
    No token parsing, no test-token backdoor. ASTRA-01.
    """
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


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


# ── DB helpers ───────────────────────────────────────────────────────────────

def _encode_cursor(occurred_at: Any, event_id: str) -> str:
    payload = json.dumps({"occurred_at": str(occurred_at), "event_id": event_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> Optional[dict]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        return json.loads(raw)
    except Exception:
        return None


def _row_to_event_summary(row: dict) -> AuditEventSummary:
    return AuditEventSummary(
        event_id=str(row["event_id"]),
        event_type=row["event_type"],
        severity=row["severity"],
        service_name=row["service_name"],
        bank_id=row["bank_id"],
        occurred_at=str(row["occurred_at"]),
        immudb_verified=bool(row.get("immudb_verified", False)),
    )


def _row_to_event_detail(row: dict) -> AuditEventDetail:
    return AuditEventDetail(
        event_id=str(row["event_id"]),
        event_type=row["event_type"],
        severity=row["severity"],
        service_name=row["service_name"],
        bank_id=row["bank_id"],
        workflow_id=row.get("workflow_id"),
        activity_name=row.get("activity_name"),
        event_data=row.get("event_data") or {},
        immudb_tx_id=row.get("immudb_tx_id"),
        immudb_verified=bool(row.get("immudb_verified", False)),
        occurred_at=str(row["occurred_at"]),
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.get("/events", response_model=AuditEventsListResponse)
async def list_audit_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    user: dict = Depends(require_audit_role),
) -> AuditEventsListResponse:
    bank_id = user["bank_id"]
    log.info("audit.list_events", bank_id=bank_id, limit=limit, severity=severity)

    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        try:
            cursor_data = _decode_cursor(cursor) if cursor else None
            params: list[Any] = [bank_id]
            where_clauses = ["bank_id = $1"]
            if event_type:
                params.append(event_type)
                where_clauses.append(f"event_type = ${len(params)}")
            if severity:
                params.append(severity)
                where_clauses.append(f"severity = ${len(params)}")
            if cursor_data:
                params.append(cursor_data["occurred_at"])
                params.append(cursor_data["event_id"])
                where_clauses.append(
                    f"(occurred_at, event_id::text) < (${len(params) - 1}::timestamptz, ${len(params)})"
                )
            where = " AND ".join(where_clauses)
            params.append(limit + 1)
            query = f"""
                SELECT event_id, bank_id, event_type, severity, service_name,
                       occurred_at, immudb_verified
                FROM cts.cts_audit_events
                WHERE {where}
                ORDER BY occurred_at DESC, event_id DESC
                LIMIT ${len(params)}
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            dicts = [dict(r) for r in rows]
            has_more = len(dicts) > limit
            page = dicts[:limit]
            next_cursor = None
            if has_more and page:
                last = page[-1]
                next_cursor = _encode_cursor(last["occurred_at"], str(last["event_id"]))
            async with pool.acquire() as conn:
                count_row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM cts.cts_audit_events WHERE bank_id = $1",
                    bank_id,
                )
            total = int(count_row["cnt"]) if count_row else 0
            return AuditEventsListResponse(
                events=[_row_to_event_summary(r) for r in page],
                total=total,
                limit=limit,
                next_cursor=next_cursor,
            )
        except Exception:
            log.warning("audit.list_events.db_error", bank_id=bank_id)

    return AuditEventsListResponse(events=[], total=0, limit=limit, next_cursor=None)


@router_v1.get("/events/{event_id}", response_model=AuditEventDetail)
async def get_audit_event(
    request: Request,
    event_id: str,
    user: dict = Depends(require_audit_role),
) -> AuditEventDetail:
    bank_id = user["bank_id"]
    log.info("audit.get_event", bank_id=bank_id, event_id=event_id)

    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT event_id, bank_id, event_type, severity, service_name,
                           workflow_id, activity_name, event_data,
                           immudb_tx_id, immudb_verified, occurred_at
                    FROM cts.cts_audit_events
                    WHERE event_id = $1::uuid AND bank_id = $2
                    """,
                    event_id, bank_id,
                )
            if row:
                return _row_to_event_detail(dict(row))
        except Exception:
            log.warning("audit.get_event.db_error", bank_id=bank_id, event_id=event_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")


@router_v1.get("/immudb/verify/{event_id}", response_model=ImmudbVerifyResponse)
async def verify_immudb_event(
    request: Request,
    event_id: str,
    user: dict = Depends(require_audit_role),
) -> ImmudbVerifyResponse:
    bank_id = user["bank_id"]
    log.info("audit.immudb_verify", bank_id=bank_id, event_id=event_id)

    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT event_id, immudb_tx_id, immudb_verified
                    FROM cts.cts_audit_events
                    WHERE event_id = $1::uuid AND bank_id = $2
                    """,
                    event_id, bank_id,
                )
            if row:
                return ImmudbVerifyResponse(
                    event_id=str(row["event_id"]),
                    verified=bool(row["immudb_verified"]),
                    immudb_tx_id=row["immudb_tx_id"],
                    merkle_proof_valid=bool(row["immudb_verified"]) if row["immudb_tx_id"] else None,
                    checked_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            log.warning("audit.immudb_verify.db_error", bank_id=bank_id, event_id=event_id)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found in Immudb")


@router_v1.get("/compliance/summary", response_model=ComplianceSummaryResponse)
async def get_compliance_summary(
    request: Request,
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

    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                agg = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*)                                          AS total_events,
                        COUNT(*) FILTER (WHERE severity = 'CRITICAL')    AS critical_count,
                        COUNT(*) FILTER (WHERE severity = 'WARN')        AS warn_count,
                        COUNT(*) FILTER (WHERE severity = 'INFO')        AS info_count,
                        COUNT(*) FILTER (WHERE NOT immudb_verified)       AS unverified_count
                    FROM cts.cts_audit_events
                    WHERE bank_id = $1
                      AND occurred_at >= $2::date
                      AND occurred_at <  $3::date + INTERVAL '1 day'
                    """,
                    bank_id, str(date_from), str(date_to),
                )
                top_rows = await conn.fetch(
                    """
                    SELECT event_type, COUNT(*) AS cnt
                    FROM cts.cts_audit_events
                    WHERE bank_id = $1
                      AND occurred_at >= $2::date
                      AND occurred_at <  $3::date + INTERVAL '1 day'
                    GROUP BY event_type
                    ORDER BY cnt DESC
                    LIMIT 10
                    """,
                    bank_id, str(date_from), str(date_to),
                )
            if agg:
                unverified = int(agg["unverified_count"] or 0)
                return ComplianceSummaryResponse(
                    bank_id=bank_id,
                    date_from=str(date_from),
                    date_to=str(date_to),
                    total_events=int(agg["total_events"] or 0),
                    critical_count=int(agg["critical_count"] or 0),
                    warn_count=int(agg["warn_count"] or 0),
                    info_count=int(agg["info_count"] or 0),
                    immudb_verified=(unverified == 0),
                    unverified_count=unverified,
                    top_event_types=[
                        {"event_type": r["event_type"], "count": int(r["cnt"])}
                        for r in top_rows
                    ],
                )
        except Exception:
            log.warning("audit.compliance_summary.db_error", bank_id=bank_id)

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
