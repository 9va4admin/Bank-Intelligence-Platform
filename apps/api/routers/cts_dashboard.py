"""
CTS Dashboard router — ops summary and exception reporting.

Routes:
  GET /v1/cts/dashboard/today   — today's clearing summary
  GET /v1/cts/dashboard/trend   — rolling N-day trend
  GET /v1/cts/exceptions        — today's CTS exceptions
"""
import time
from datetime import date, datetime, timezone
from typing import Any, List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from apps.api.schemas.types import IsoTimestamp, OptIsoTimestamp

from apps.api.routers.batch import _db_unavailable, _inward_breakdown, _outward_breakdown
from apps.api.routers.cts_deps import get_current_user_context
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DashboardTodaySummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: IsoTimestamp
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
    occurred_at: IsoTimestamp
    detail: str
    resolved: bool
    margin_seconds: Optional[int] = None


class ExceptionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: IsoTimestamp
    items: list[ExceptionItem]
    total: int


_EXCEPTION_LABEL_MAP = {
    "IET_NEAR_BREACH":        get_message("UI_EXCEPTIONS_IET_NEAR_BREACH_30S_MARGIN"),
    "IET_BREACH":             get_message("API_IET_BREACHED"),
    "NGCH_REJECT":            get_message("UI_EXCEPTIONS_NGCH_FILING_REJECTED_RETRIED"),
    "IQA_FAIL":               get_message("UI_EXCEPTIONS_IMAGE_QUALITY_FAILURE"),
    "VAULT_MISS":             get_message("API_SIGNATURE_VAULT_MISS"),
    "VAULT_STALE":            get_message("API_VAULT_STALE"),
    "OCR_LOW_CONFIDENCE":     get_message("API_OCR_LOW_CONFIDENCE"),
    "SIG_LOW_CONFIDENCE":     get_message("API_SIGNATURE_LOW_CONFIDENCE"),
    "FRAUD_HIGH_SCORE":       get_message("UI_EXCEPTIONS_FRAUD_SCORE_ABOVE_THRESHOLD"),
    "ALTERATION_DETECTED":    get_message("API_CHEQUE_ALTERATION_DETECTED"),
    "WORDS_FIGURES_MISMATCH": get_message("API_WORDS_FIGURES_MISMATCH"),
    "CBS_UNREACHABLE":        get_message("API_CBS_UNREACHABLE_IMAGE_ONLY_MODE"),
    "STOP_PAYMENT":           get_message("API_STOP_PAYMENT_TRIGGERED"),
    "DUPLICATE":              get_message("API_DUPLICATE_INSTRUMENT_DETECTED"),
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

def _pool(request: Request) -> Any:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise _db_unavailable()
    return pool


@router_v1.get("/dashboard/today", response_model=DashboardTodaySummary)
async def get_dashboard_today(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> DashboardTodaySummary:
    """
    Today's clearing summary. Inward figures are the same ones the batch session summary reports
    (system decisions from cts.agent_decisions, human decisions from cts.human_review_items, both
    joined to INWARD instruments); a database failure is a 503, never a page of zeros.
    """
    bank_id = ctx.bank_id
    today = date.today()
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            inward = await _inward_breakdown(conn, bank_id, today)
            outward = await _outward_breakdown(conn, bank_id, today)
            sessions = await conn.fetch(
                "SELECT status FROM cts.clearing_sessions WHERE bank_id = $1 AND session_date = $2::date",
                bank_id, today,
            )
    except Exception:
        log.exception("cts.dashboard_today.query_failed", bank_id=bank_id)
        raise _db_unavailable()

    return DashboardTodaySummary(
        bank_id=bank_id, clearing_date=today.isoformat(),
        sessions_count=len(sessions), sessions_settled=sum(1 for r in sessions if r["status"] == "SETTLED"),
        total_inward=inward.total_inward,
        stp_confirmed=inward.stp_confirmed, stp_returned=inward.stp_returned,
        manual_confirmed=inward.manual_confirmed, manual_returned=inward.manual_returned,
        pending_review=inward.pending_review,
        overall_stp_rate_pct=inward.stp_rate_pct,
        overall_return_rate_pct=inward.return_rate_pct,
        total_outward=outward.total_outward,
        outward_returned=outward.ngch_returned,
    )


@router_v1.get("/dashboard/trend", response_model=DashboardTrendResponse)
async def get_dashboard_trend(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    days: int = Query(7, ge=1, le=30),
) -> DashboardTrendResponse:
    """Rolling N-day inward trend: system STP rate and return rate (system + reviewer) per day."""
    bank_id = ctx.bank_id
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                /* q:trend */
                WITH d AS (
                    SELECT (ci.received_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
                           ad.decision, hr.reviewer_decision
                      FROM cts.cheque_instruments ci
                      LEFT JOIN cts.agent_decisions ad
                             ON ad.instrument_id = ci.instrument_id AND ad.bank_id = ci.bank_id
                      LEFT JOIN cts.human_review_items hr
                             ON hr.instrument_id = ci.instrument_id AND hr.bank_id = ci.bank_id AND hr.status = 'DECIDED'
                     WHERE ci.bank_id = $1 AND ci.direction = 'INWARD'
                       AND ci.received_at >= NOW() - ($2 * INTERVAL '1 day')
                )
                SELECT TO_CHAR(day, 'Mon DD') AS date,
                       COUNT(*)::int AS inward,
                       ROUND(COUNT(*) FILTER (WHERE decision = 'STP_CONFIRM')::numeric
                             / NULLIF(COUNT(*), 0) * 100, 1)::float AS stp_rate_pct,
                       ROUND(COUNT(*) FILTER (WHERE decision = 'STP_RETURN' OR reviewer_decision = 'RETURN')::numeric
                             / NULLIF(COUNT(*), 0) * 100, 1)::float AS return_rate_pct
                  FROM d
                 GROUP BY day
                 ORDER BY day
                """,
                bank_id, days,
            )
    except Exception:
        log.exception("cts.dashboard_trend.query_failed", bank_id=bank_id)
        raise _db_unavailable()

    return DashboardTrendResponse(bank_id=bank_id, days=days, trend=[
        DashboardTrendRow(
            date=r["date"], inward=r["inward"],
            stp_rate_pct=float(r["stp_rate_pct"] or 0.0), return_rate_pct=float(r["return_rate_pct"] or 0.0),
        )
        for r in rows
    ])


@router_v1.get("/exceptions", response_model=ExceptionsResponse)
async def get_exceptions(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    severity: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> ExceptionsResponse:
    """
    Today's inward cheques that needed a person or ran degraded, from cts.agent_decisions: the
    exception type is the recorded decision_reason, resolved means a reviewer has decided it.
    (There is no separate exceptions table.)
    """
    bank_id = ctx.bank_id
    today = date.today().isoformat()
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                /* q:exceptions */
                SELECT 'EX-' || ad.instrument_id::text AS exception_id,
                       ad.instrument_id::text AS instrument_id,
                       COALESCE(ad.decision_reason, ad.decision) AS exception_type,
                       'MEDIUM' AS severity,
                       ad.created_at::text AS occurred_at,
                       COALESCE(ad.decision_reason, ad.decision) AS detail,
                       EXISTS (SELECT 1 FROM cts.human_review_items hr
                                WHERE hr.instrument_id = ad.instrument_id AND hr.bank_id = ad.bank_id
                                  AND hr.status = 'DECIDED') AS resolved,
                       ad.iet_margin_seconds AS margin_seconds
                  FROM cts.agent_decisions ad
                 WHERE ad.bank_id = $1 AND ad.created_at::date = CURRENT_DATE
                   AND (ad.decision = 'HUMAN_REVIEW' OR ad.degraded_mode)
                 ORDER BY ad.created_at DESC
                 LIMIT $2
                """,
                bank_id, limit,
            )
    except Exception:
        log.exception("cts.exceptions.query_failed", bank_id=bank_id)
        raise _db_unavailable()

    items = [
        ExceptionItem(
            id=r["exception_id"], instrument_id=r["instrument_id"], exception_type=r["exception_type"],
            label=_EXCEPTION_LABEL_MAP.get(r["exception_type"], r["exception_type"]),
            severity=_EXCEPTION_SEVERITY_MAP.get(r["exception_type"], r["severity"]),
            occurred_at=r["occurred_at"], detail=r["detail"] or "",
            resolved=bool(r["resolved"]), margin_seconds=r["margin_seconds"],
        )
        for r in rows
    ]
    if severity:
        items = [i for i in items if i.severity == severity]
    return ExceptionsResponse(bank_id=bank_id, clearing_date=today, items=items, total=len(items))
