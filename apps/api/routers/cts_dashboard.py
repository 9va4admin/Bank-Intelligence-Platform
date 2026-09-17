"""
CTS Dashboard router — ops summary and exception reporting.

Routes:
  GET /v1/cts/dashboard/today   — today's clearing summary
  GET /v1/cts/dashboard/trend   — rolling N-day trend
  GET /v1/cts/exceptions        — today's CTS exceptions
"""
import time
from datetime import date, datetime, timezone
from typing import List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from apps.api.routers.cts_deps import get_current_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DashboardTodaySummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: str
    sessions_count: int
    sessions_settled: int
    total_inward: int
    stp_confirmed: int
    stp_returned: int
    manual_confirmed: int
    manual_returned: int
    pending_review: int
    overall_stp_rate_pct: float
    overall_return_rate_pct: float
    total_outward: int
    outward_returned: int


class DashboardTrendRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    inward: int
    stp_rate_pct: float
    return_rate_pct: float


class DashboardTrendResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    days: int
    trend: list[DashboardTrendRow]


class ExceptionItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    instrument_id: str
    exception_type: str
    label: str
    severity: str
    occurred_at: str
    detail: str
    resolved: bool
    margin_seconds: Optional[int] = None


class ExceptionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: str
    items: list[ExceptionItem]
    total: int


_EXCEPTION_LABEL_MAP = {
    "IET_NEAR_BREACH":        "IET Near-Breach (< 30s margin)",
    "IET_BREACH":             "IET Breached",
    "NGCH_REJECT":            "NGCH Filing Rejected / Retried",
    "IQA_FAIL":               "Image Quality Failure",
    "VAULT_MISS":             "Signature Vault Miss",
    "VAULT_STALE":            "Vault Stale",
    "OCR_LOW_CONFIDENCE":     "OCR Low Confidence",
    "SIG_LOW_CONFIDENCE":     "Signature Low Confidence",
    "FRAUD_HIGH_SCORE":       "Fraud Score Above Threshold",
    "ALTERATION_DETECTED":    "Cheque Alteration Detected",
    "WORDS_FIGURES_MISMATCH": "Words / Figures Mismatch",
    "CBS_UNREACHABLE":        "CBS Unreachable — Image-Only Mode",
    "STOP_PAYMENT":           "Stop Payment Triggered",
    "DUPLICATE":              "Duplicate Instrument Detected",
}

_EXCEPTION_SEVERITY_MAP = {
    "IET_NEAR_BREACH":        "CRITICAL",
    "IET_BREACH":             "CRITICAL",
    "NGCH_REJECT":            "CRITICAL",
    "VAULT_STALE":            "CRITICAL",
    "STOP_PAYMENT":           "CRITICAL",
    "ALTERATION_DETECTED":    "HIGH",
    "FRAUD_HIGH_SCORE":       "HIGH",
    "IQA_FAIL":               "HIGH",
    "VAULT_MISS":             "HIGH",
    "OCR_LOW_CONFIDENCE":     "MEDIUM",
    "SIG_LOW_CONFIDENCE":     "MEDIUM",
    "WORDS_FIGURES_MISMATCH": "MEDIUM",
    "CBS_UNREACHABLE":        "MEDIUM",
    "DUPLICATE":              "MEDIUM",
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.get("/dashboard/today", response_model=DashboardTodaySummary)
async def get_dashboard_today(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> DashboardTodaySummary:
    """
    Today's clearing summary: inward AI decisions (STP/return/pending),
    outward scan counts, and clearing session totals.
    Combines cts.agent_decisions + cts.outward_scan_events + cts.clearing_sessions.
    """
    bank_id = ctx.bank_id
    from datetime import date as _date
    today = _date.today().isoformat()

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return DashboardTodaySummary(
            bank_id=bank_id, clearing_date=today,
            sessions_count=0, sessions_settled=0,
            total_inward=0, stp_confirmed=0, stp_returned=0,
            manual_confirmed=0, manual_returned=0, pending_review=0,
            overall_stp_rate_pct=0.0, overall_return_rate_pct=0.0,
            total_outward=0, outward_returned=0,
        )

    try:
        inward_row = await db.fetchrow(
            """
            SELECT
                COUNT(*)::int                                                   AS total_inward,
                COUNT(*) FILTER (WHERE decision = 'STP_CONFIRM')::int          AS stp_confirmed,
                COUNT(*) FILTER (WHERE decision = 'STP_RETURN')::int           AS stp_returned,
                COUNT(*) FILTER (WHERE decision = 'MANUAL_CONFIRM')::int       AS manual_confirmed,
                COUNT(*) FILTER (WHERE decision = 'MANUAL_RETURN')::int        AS manual_returned,
                COUNT(*) FILTER (WHERE decision = 'HUMAN_REVIEW')::int         AS pending_review
            FROM cts.agent_decisions
            WHERE bank_id = $1
              AND processing_started_at::date = $2::date
            """,
            bank_id, today,
        )
        outward_row = await db.fetchrow(
            """
            SELECT
                COUNT(*)::int                                               AS total_outward,
                COUNT(*) FILTER (WHERE outcome = 'CTS_REJECTED')::int      AS outward_returned
            FROM cts.outward_scan_events
            WHERE bank_id = $1
              AND scanned_at::date = $2::date
            """,
            bank_id, today,
        )
        session_row = await db.fetchrow(
            """
            SELECT
                COUNT(*)::int                                                       AS sessions_count,
                COUNT(*) FILTER (WHERE settlement_at IS NOT NULL)::int              AS sessions_settled
            FROM cts.clearing_sessions
            WHERE bank_id = $1 AND session_date = $2::date
            """,
            bank_id, today,
        )
    except Exception as exc:
        log.error("cts.dashboard_today.query_failed", bank_id=bank_id, error=str(exc))
        return DashboardTodaySummary(
            bank_id=bank_id, clearing_date=today,
            sessions_count=0, sessions_settled=0,
            total_inward=0, stp_confirmed=0, stp_returned=0,
            manual_confirmed=0, manual_returned=0, pending_review=0,
            overall_stp_rate_pct=0.0, overall_return_rate_pct=0.0,
            total_outward=0, outward_returned=0,
        )

    total_inward   = int(inward_row["total_inward"]    or 0) if inward_row   else 0
    stp_confirmed  = int(inward_row["stp_confirmed"]   or 0) if inward_row   else 0
    stp_returned   = int(inward_row["stp_returned"]    or 0) if inward_row   else 0
    manual_conf    = int(inward_row["manual_confirmed"] or 0) if inward_row  else 0
    manual_ret     = int(inward_row["manual_returned"]  or 0) if inward_row  else 0
    pending        = int(inward_row["pending_review"]   or 0) if inward_row  else 0
    total_out      = int(outward_row["total_outward"]   or 0) if outward_row else 0
    out_ret        = int(outward_row["outward_returned"] or 0) if outward_row else 0
    ses_count      = int(session_row["sessions_count"]  or 0) if session_row else 0
    ses_settled    = int(session_row["sessions_settled"] or 0) if session_row else 0

    stp_rate_pct    = round(stp_confirmed / total_inward * 100, 1) if total_inward > 0 else 0.0
    return_rate_pct = round((stp_returned + manual_ret) / total_inward * 100, 1) if total_inward > 0 else 0.0

    return DashboardTodaySummary(
        bank_id=bank_id, clearing_date=today,
        sessions_count=ses_count, sessions_settled=ses_settled,
        total_inward=total_inward,
        stp_confirmed=stp_confirmed, stp_returned=stp_returned,
        manual_confirmed=manual_conf, manual_returned=manual_ret,
        pending_review=pending,
        overall_stp_rate_pct=stp_rate_pct,
        overall_return_rate_pct=return_rate_pct,
        total_outward=total_out,
        outward_returned=out_ret,
    )


@router_v1.get("/dashboard/trend", response_model=DashboardTrendResponse)
async def get_dashboard_trend(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    days: int = Query(7, ge=1, le=30),
) -> DashboardTrendResponse:
    """
    Rolling N-day trend for the ops dashboard sparklines.
    Queries cts.agent_decisions grouped by processing date.
    """
    bank_id = ctx.bank_id

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return DashboardTrendResponse(bank_id=bank_id, days=days, trend=[])

    try:
        rows = await db.fetch(
            """
            SELECT
                TO_CHAR(processing_started_at AT TIME ZONE 'Asia/Kolkata', 'Mon DD') AS date,
                COUNT(*)::int                                                          AS inward,
                ROUND(
                    COUNT(*) FILTER (WHERE decision = 'STP_CONFIRM')::numeric
                    / NULLIF(COUNT(*), 0) * 100, 1
                )::float AS stp_rate_pct,
                ROUND(
                    (COUNT(*) FILTER (WHERE decision IN ('STP_RETURN', 'MANUAL_RETURN')))::numeric
                    / NULLIF(COUNT(*), 0) * 100, 1
                )::float AS return_rate_pct
            FROM cts.agent_decisions
            WHERE bank_id = $1
              AND processing_started_at >= NOW() - ($2 * INTERVAL '1 day')
            GROUP BY DATE(processing_started_at AT TIME ZONE 'Asia/Kolkata'),
                     TO_CHAR(processing_started_at AT TIME ZONE 'Asia/Kolkata', 'Mon DD')
            ORDER BY DATE(processing_started_at AT TIME ZONE 'Asia/Kolkata')
            """,
            bank_id, days,
        )
    except Exception as exc:
        log.error("cts.dashboard_trend.query_failed", bank_id=bank_id, error=str(exc))
        return DashboardTrendResponse(bank_id=bank_id, days=days, trend=[])

    trend = [
        DashboardTrendRow(
            date=r["date"],
            inward=r["inward"],
            stp_rate_pct=float(r["stp_rate_pct"] or 0.0),
            return_rate_pct=float(r["return_rate_pct"] or 0.0),
        )
        for r in rows
    ]
    return DashboardTrendResponse(bank_id=bank_id, days=days, trend=trend)


@router_v1.get("/exceptions", response_model=ExceptionsResponse)
async def get_exceptions(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    severity: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> ExceptionsResponse:
    """
    Returns today's CTS exceptions derived from cts.agent_decisions where
    decision_outcome IN ('HUMAN_REVIEW', 'RETURN') or exception events are
    logged in cts.workflow_exceptions.
    Falls back to empty list if no DB or no exceptions table.
    """
    bank_id = ctx.bank_id
    today = date.today().isoformat()
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return ExceptionsResponse(bank_id=bank_id, clearing_date=today, items=[], total=0)

    try:
        sev_clause = "AND ex.severity = $3" if severity else ""
        params: list = [bank_id, limit]
        if severity:
            params.append(severity)
        rows = await db.fetch(
            f"""
            SELECT ex.exception_id, ex.instrument_id, ex.exception_type,
                   ex.severity, ex.occurred_at::text,
                   ex.detail, ex.resolved, ex.margin_seconds
            FROM cts.workflow_exceptions ex
            WHERE ex.bank_id = $1
              AND ex.occurred_at::date = CURRENT_DATE
              {sev_clause}
            ORDER BY
              CASE ex.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END,
              ex.occurred_at DESC
            LIMIT $2
            """,
            *params,
        )
    except Exception:
        # Table may not exist yet — fallback to agent_decisions-derived exceptions
        try:
            rows = await db.fetch(
                """
                SELECT
                    'EX-' || instrument_id AS exception_id,
                    instrument_id,
                    CASE
                        WHEN LOWER(raw_json::text) LIKE '%vault_miss%'   THEN 'VAULT_MISS'
                        WHEN LOWER(raw_json::text) LIKE '%iet%'          THEN 'IET_NEAR_BREACH'
                        WHEN LOWER(raw_json::text) LIKE '%alteration%'   THEN 'ALTERATION_DETECTED'
                        WHEN decision_outcome = 'RETURN'                  THEN 'SIG_LOW_CONFIDENCE'
                        ELSE 'OCR_LOW_CONFIDENCE'
                    END AS exception_type,
                    'HIGH' AS severity,
                    decided_at::text AS occurred_at,
                    'See agent decision for full context' AS detail,
                    (decision_outcome IN ('STP_CONFIRM','STP_RETURN','CONFIRMED','RETURNED')) AS resolved,
                    NULL::int AS margin_seconds
                FROM cts.agent_decisions
                WHERE bank_id = $1
                  AND decided_at::date = CURRENT_DATE
                  AND decision_outcome IN ('HUMAN_REVIEW', 'RETURN', 'RETURNED', 'STP_RETURN')
                ORDER BY decided_at DESC
                LIMIT $2
                """,
                bank_id,
                limit,
            )
        except Exception as exc2:
            log.warning("cts.exceptions.query_failed", bank_id=bank_id, error=str(exc2))
            return ExceptionsResponse(bank_id=bank_id, clearing_date=today, items=[], total=0)

    items = [
        ExceptionItem(
            id=r["exception_id"],
            instrument_id=r["instrument_id"],
            exception_type=r["exception_type"],
            label=_EXCEPTION_LABEL_MAP.get(r["exception_type"], r["exception_type"]),
            severity=_EXCEPTION_SEVERITY_MAP.get(r["exception_type"], r["severity"]),
            occurred_at=r["occurred_at"] or datetime.now(timezone.utc).isoformat(),
            detail=r["detail"] or "",
            resolved=bool(r["resolved"]),
            margin_seconds=r["margin_seconds"],
        )
        for r in rows
    ]
    return ExceptionsResponse(bank_id=bank_id, clearing_date=today, items=items, total=len(items))
