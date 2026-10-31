"""
Batch Operations API — clearing session dashboard, val/vol metrics, file downloads.

Covers both perspectives:
  - Presenting bank  (inward cheques received from NGCH for payment)
  - Drawee bank      (outward cheques sent by our branches to NGCH)
  - Combined         (net position per session / per day)

Routes backed by real data:
  GET  /v1/cts/sessions                          — clearing sessions from cts.clearing_sessions
  GET  /v1/cts/sessions/today                    — today's totals from cheque_instruments / agent_decisions / human_review_items

Routes not yet built on real data (answer 501 CTS_BATCH_NOT_IMPLEMENTED, never invented numbers):
  GET  /v1/cts/sessions/{session_id}/summary
  GET  /v1/cts/sessions/{session_id}/bankwise
  GET  /v1/cts/sessions/{session_id}/download/npci   — NPCI return file (RRF/CSV)
  GET  /v1/cts/sessions/{session_id}/download/mis    — internal MIS report (CSV)
  GET  /v1/cts/sessions/{session_id}/download/settlement — settlement position statement
  GET  /v1/cts/dashboard/ops                     — ops head morning view: multi-day trend
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.messages import get_message
from shared.auth.rbac import UserContext
from shared.messages import get_message

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS Batch Ops v1"])

_ALLOWED_ROLES = {
    "ops_reviewer", "ops_manager", "bank_it_admin",
    "compliance_officer", "fraud_analyst", "rbi_examiner",
}


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def get_current_bank_id(
    ctx: UserContext = Depends(require_user_context),
) -> str:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.
    No token parsing, no test-token backdoor. ASTRA-01.
    """
    return ctx.bank_id


async def get_current_role(
    ctx: UserContext = Depends(require_user_context),
) -> str:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.
    No token parsing, no test-token backdoor. ASTRA-01.
    """
    return ctx.role.value


def require_ops_role(role: str = Depends(get_current_role)) -> str:
    if role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message("AUTH_INSUFFICIENT_ROLE"))
    return role


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SessionStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    clearing_date: date
    session_slot: str          # "10:00–12:00"
    status: Literal["UPCOMING", "OPEN", "PROCESSING", "FILED", "SETTLED", "FAILED"]
    opened_at: Optional[datetime]
    closed_at: Optional[datetime]
    ngch_ack_at: Optional[datetime]


class TodaySummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: date
    sessions_count: int
    sessions_settled: int
    # Presenting bank totals
    total_inward: int
    total_inward_value_paise: int
    stp_confirmed: int
    stp_returned: int
    manual_confirmed: int
    manual_returned: int
    pending_review: int
    overall_stp_rate_pct: float
    overall_return_rate_pct: float
    # Drawee bank totals
    total_outward: int
    total_outward_value_paise: int
    outward_returned: Optional[int] = None   # needs the return-file reconciliation; not derived here
    # Net settlement is known only after reconciliation
    net_settlement_paise: Optional[int] = None
    # 5-day trend (for sparkline)
    trend_5d: list[dict]
    generated_at: datetime


class SessionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    sessions: list[SessionStatus]
    total: int


# ---------------------------------------------------------------------------
# DB -> API mapping (cts.clearing_sessions as the migrations create it)
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, str] = {
    "PENDING":         "OPEN",
    "SUBMITTED":       "FILED",
    "SUBMITTED_TO_SB": "FILED",
    "EMPTY_SESSION":   "FILED",      # closed with nothing to settle
    "RECONCILED":      "SETTLED",
    "EXCEPTION":       "FAILED",
}

_SLOT_MAP: dict[str, str] = {
    "MORNING":   "10:00–12:00",
    "AFTERNOON": "12:00–14:00",
    "EVENING":   "14:00–16:00",
}


def _row_to_session_status(row: dict) -> SessionStatus:
    return SessionStatus(
        session_id=str(row["session_id"]),
        clearing_date=row["session_date"],
        session_slot=_SLOT_MAP.get(row.get("session_type"), str(row.get("session_type") or "")),
        status=_STATUS_MAP.get(row.get("status"), "OPEN"),
        opened_at=row.get("presentation_open_at") or row.get("created_at"),
        closed_at=row.get("presentation_close_at"),
        ngch_ack_at=row.get("settlement_at"),
    )


def _db_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error_code": "CTS_BATCH_DB_UNAVAILABLE", "message": get_message("API_BATCH_DB_UNAVAILABLE")},
    )


def _not_implemented() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={"error_code": "CTS_BATCH_NOT_IMPLEMENTED", "message": get_message("API_BATCH_NOT_IMPLEMENTED")},
    )


def _pool(request: Request) -> Any:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise _db_unavailable()
    return pool


# ---------------------------------------------------------------------------
# Routes - session list
# ---------------------------------------------------------------------------

@router_v1.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    clearing_date: Optional[date] = Query(None),
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> SessionListResponse:
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, session_date, session_type, status, created_at,
                       presentation_open_at, presentation_close_at, settlement_at
                  FROM cts.clearing_sessions
                 WHERE bank_id = $1 AND ($2::date IS NULL OR session_date = $2::date)
                 ORDER BY session_date DESC, session_type
                 LIMIT 50
                """,
                bank_id, clearing_date,
            )
        sessions = [_row_to_session_status(dict(r)) for r in rows]
    except Exception:
        log.exception("batch.list_sessions.db_error", bank_id=bank_id)
        raise _db_unavailable()
    return SessionListResponse(bank_id=bank_id, sessions=sessions, total=len(sessions))


# ---------------------------------------------------------------------------
# Routes - today summary
# ---------------------------------------------------------------------------

def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


@router_v1.get("/sessions/today", response_model=TodaySummaryResponse)
async def today_summary(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> TodaySummaryResponse:
    pool = _pool(request)
    today = date.today()
    try:
        async with pool.acquire() as conn:
            sessions = await conn.fetch(
                "SELECT status FROM cts.clearing_sessions WHERE bank_id = $1 AND session_date = $2::date",
                bank_id, today,
            )
            volumes = await conn.fetch(
                """
                SELECT direction, COUNT(*) AS n, COALESCE(SUM(amount_paise), 0) AS paise
                  FROM cts.cheque_instruments
                 WHERE bank_id = $1 AND received_at::date = $2::date
                 GROUP BY direction
                """,
                bank_id, today,
            )
            decisions = await conn.fetch(
                """
                SELECT decision, COUNT(*) AS n
                  FROM cts.agent_decisions
                 WHERE bank_id = $1 AND created_at::date = $2::date
                 GROUP BY decision
                """,
                bank_id, today,
            )
            reviews = await conn.fetch(
                """
                SELECT status, reviewer_decision, COUNT(*) AS n
                  FROM cts.human_review_items
                 WHERE bank_id = $1 AND (status = 'PENDING' OR reviewed_at::date = $2::date)
                 GROUP BY status, reviewer_decision
                """,
                bank_id, today,
            )
            trend = await conn.fetch(
                """
                SELECT received_at::date AS day,
                       COUNT(*) FILTER (WHERE direction = 'INWARD')  AS inward,
                       COUNT(*) FILTER (WHERE direction = 'OUTWARD') AS outward
                  FROM cts.cheque_instruments
                 WHERE bank_id = $1 AND received_at::date > ($2::date - 5)
                 GROUP BY 1
                 ORDER BY 1
                """,
                bank_id, today,
            )
    except Exception:
        log.exception("batch.today_summary.db_error", bank_id=bank_id)
        raise _db_unavailable()

    vol = {r["direction"]: r for r in volumes}
    total_in, in_paise = (vol["INWARD"]["n"], vol["INWARD"]["paise"]) if "INWARD" in vol else (0, 0)
    total_out, out_paise = (vol["OUTWARD"]["n"], vol["OUTWARD"]["paise"]) if "OUTWARD" in vol else (0, 0)
    dec = {r["decision"]: r["n"] for r in decisions}
    stp_c, stp_r = dec.get("STP_CONFIRM", 0), dec.get("STP_RETURN", 0)
    man_c = sum(r["n"] for r in reviews if r["status"] == "DECIDED" and r["reviewer_decision"] == "CONFIRM")
    man_r = sum(r["n"] for r in reviews if r["status"] == "DECIDED" and r["reviewer_decision"] == "RETURN")
    pending = sum(r["n"] for r in reviews if r["status"] == "PENDING")

    return TodaySummaryResponse(
        bank_id=bank_id,
        clearing_date=today,
        sessions_count=len(sessions),
        sessions_settled=sum(1 for r in sessions if r["status"] == "RECONCILED"),
        total_inward=total_in,
        total_inward_value_paise=in_paise,
        stp_confirmed=stp_c,
        stp_returned=stp_r,
        manual_confirmed=man_c,
        manual_returned=man_r,
        pending_review=pending,
        overall_stp_rate_pct=_pct(stp_c + stp_r, total_in),
        overall_return_rate_pct=_pct(stp_r + man_r, total_in),
        total_outward=total_out,
        total_outward_value_paise=out_paise,
        outward_returned=0,
        net_settlement_paise=None,
        trend_5d=[{"date": r["day"].isoformat(), "inward": r["inward"], "outward": r["outward"]} for r in trend],
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Not yet built on real data. These used to return invented numbers (a made-up NPCI return file among them); they now
# say so instead. Build each from cts.cheque_instruments / agent_decisions / the RRF tables before enabling it.
# ---------------------------------------------------------------------------

@router_v1.get("/sessions/{session_id}/summary")
async def session_summary(session_id: str, _bank_id: str = Depends(get_current_bank_id),
                          _role: str = Depends(require_ops_role)) -> None:
    raise _not_implemented()


@router_v1.get("/sessions/{session_id}/bankwise")
async def session_bankwise(session_id: str, _bank_id: str = Depends(get_current_bank_id),
                           _role: str = Depends(require_ops_role)) -> None:
    raise _not_implemented()


@router_v1.get("/sessions/{session_id}/download/npci")
async def download_npci_return_file(session_id: str, _bank_id: str = Depends(get_current_bank_id),
                                    _role: str = Depends(require_ops_role)) -> None:
    raise _not_implemented()


@router_v1.get("/sessions/{session_id}/download/mis")
async def download_mis_report(session_id: str, _bank_id: str = Depends(get_current_bank_id),
                              _role: str = Depends(require_ops_role)) -> None:
    raise _not_implemented()


@router_v1.get("/sessions/{session_id}/download/settlement")
async def download_settlement_statement(session_id: str, _bank_id: str = Depends(get_current_bank_id),
                                        _role: str = Depends(require_ops_role)) -> None:
    raise _not_implemented()


@router_v1.get("/dashboard/ops")
async def ops_dashboard(days: int = Query(7, ge=1, le=30), _bank_id: str = Depends(get_current_bank_id),
                        _role: str = Depends(require_ops_role)) -> None:
    raise _not_implemented()
