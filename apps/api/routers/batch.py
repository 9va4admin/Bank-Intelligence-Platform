"""
Batch Operations API — clearing session dashboard, val/vol metrics, file downloads.

Covers both perspectives:
  - Presenting bank  (inward cheques received from NGCH for payment)
  - Drawee bank      (outward cheques sent by our branches to NGCH)
  - Combined         (net position per session / per day)

Routes backed by real data:
  GET  /v1/cts/sessions                          — clearing sessions from cts.clearing_sessions
  GET  /v1/cts/sessions/today                    — today's totals from cheque_instruments / agent_decisions / human_review_items

  GET  /v1/cts/sessions/{session_id}/summary, /bankwise, /download/{npci,mis,settlement}, GET /v1/cts/dashboard/ops
Instruments carry no clearing-session tag, so a session's figures are those of its clearing date; session id TODAY means today.
  GET  /v1/cts/sessions/{session_id}/download/npci   — NPCI return file (RRF/CSV)
  GET  /v1/cts/sessions/{session_id}/download/mis    — internal MIS report (CSV)
  GET  /v1/cts/sessions/{session_id}/download/settlement — settlement position statement
  GET  /v1/cts/dashboard/ops                     — ops head morning view: multi-day trend
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

import csv
import io
import uuid
from datetime import timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.messages import get_message
from shared.auth.rbac import UserContext
from shared.storage.image_fetch import fetch_image_bytes as fetch_object_bytes

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


class DecisionBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)
    total_inward: int
    stp_confirmed: int
    stp_returned: int
    manual_confirmed: int
    manual_returned: int
    pending_review: int
    total_value_paise: int
    stp_confirmed_value_paise: int
    stp_returned_value_paise: int
    manual_confirmed_value_paise: int
    manual_returned_value_paise: int
    stp_rate_pct: float
    manual_rate_pct: float
    return_rate_pct: float
    avg_decision_ms: int
    p99_decision_ms: int
    iet_near_breach_count: int


class OutwardBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)
    total_outward: int
    total_outward_value_paise: int
    ngch_accepted: int
    ngch_returned: int
    ngch_returned_value_paise: int
    return_reasons: dict[str, int]   # reason_code -> count


class SessionSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session: SessionStatus
    bank_id: str
    presenting_bank: DecisionBreakdown    # inward (we are the paying bank)
    drawee_bank: OutwardBreakdown         # outward (we are the collecting bank)
    net_settlement_paise: Optional[int] = None   # known only after reconciliation
    generated_at: datetime


class BankwiseRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_ifsc: str
    bank_name: str
    perspective: Literal["PRESENTING", "DRAWEE"]
    cheque_count: int
    total_value_paise: int
    confirmed_count: int
    returned_count: int
    return_rate_pct: float


class BankwiseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    bank_id: str
    rows: list[BankwiseRow]
    generated_at: datetime



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
# Session detail. Instruments carry no clearing-session tag, so a session's figures are those of its clearing DATE
# (a day with several sessions shows the day's figures on each). Session "TODAY" means today across all sessions.
# ---------------------------------------------------------------------------

# The IET watchdog fires 30 s before the deadline; that is structural (Layer 1), not a bank setting.
_IET_WATCHDOG_SECONDS = 30
_INWARD_JOIN = "ci.instrument_id = {a}.instrument_id AND ci.bank_id = {a}.bank_id"


def _session_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error_code": "CTS_SESSION_NOT_FOUND", "message": get_message("API_BATCH_SESSION_NOT_FOUND")},
    )


async def _load_session(conn: Any, bank_id: str, session_id: str) -> tuple[Optional[dict], date]:
    """(session row, clearing date). 'TODAY' has no row. A malformed or foreign id is a 404, never a 500."""
    if session_id.upper() == "TODAY":
        return None, date.today()
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise _session_not_found()
    rows = await conn.fetch(
        """
        /* q:session */
        SELECT session_id, session_date, session_type, status, created_at,
               presentation_open_at, presentation_close_at, settlement_at
          FROM cts.clearing_sessions
         WHERE session_id = $1::uuid AND bank_id = $2
        """,
        session_id, bank_id,
    )
    if not rows:
        raise _session_not_found()
    row = dict(rows[0])
    return row, row["session_date"]


async def _inward_breakdown(conn: Any, bank_id: str, day: date) -> DecisionBreakdown:
    join = _INWARD_JOIN
    decisions = await conn.fetch(
        f"""
        /* q:inward_decisions */
        SELECT ad.decision, COUNT(*) AS n, COALESCE(SUM(ci.amount_paise), 0) AS paise
          FROM cts.agent_decisions ad
          JOIN cts.cheque_instruments ci ON {join.format(a='ad')}
         WHERE ad.bank_id = $1 AND ci.direction = 'INWARD' AND ci.received_at::date = $2::date
         GROUP BY ad.decision
        """,
        bank_id, day,
    )
    reviews = await conn.fetch(
        f"""
        /* q:inward_reviews */
        SELECT hr.status, hr.reviewer_decision, COUNT(*) AS n, COALESCE(SUM(ci.amount_paise), 0) AS paise
          FROM cts.human_review_items hr
          JOIN cts.cheque_instruments ci ON {join.format(a='hr')}
         WHERE hr.bank_id = $1 AND ci.direction = 'INWARD' AND ci.received_at::date = $2::date
         GROUP BY hr.status, hr.reviewer_decision
        """,
        bank_id, day,
    )
    totals = await conn.fetch(
        """
        /* q:inward_totals */
        SELECT COUNT(*) AS n, COALESCE(SUM(amount_paise), 0) AS paise,
               COUNT(*) FILTER (WHERE iet_breached) AS breached
          FROM cts.cheque_instruments
         WHERE bank_id = $1 AND direction = 'INWARD' AND received_at::date = $2::date
        """,
        bank_id, day,
    )
    perf = await conn.fetch(
        f"""
        /* q:inward_perf */
        SELECT COALESCE(AVG(ad.processing_duration_ms), 0)::int AS avg_ms,
               COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY ad.processing_duration_ms), 0)::int AS p99_ms,
               COUNT(*) FILTER (WHERE ad.iet_margin_seconds IS NOT NULL AND ad.iet_margin_seconds < $3) AS near
          FROM cts.agent_decisions ad
          JOIN cts.cheque_instruments ci ON {join.format(a='ad')}
         WHERE ad.bank_id = $1 AND ci.direction = 'INWARD' AND ci.received_at::date = $2::date
        """,
        bank_id, day, _IET_WATCHDOG_SECONDS,
    )
    dec = {r["decision"]: (int(r["n"]), int(r["paise"])) for r in decisions}
    stp_c, stp_c_v = dec.get("STP_CONFIRM", (0, 0))
    stp_r, stp_r_v = dec.get("STP_RETURN", (0, 0))

    def _manual(kind: str) -> tuple[int, int]:
        hit = [r for r in reviews if r["status"] == "DECIDED" and r["reviewer_decision"] == kind]
        return sum(int(r["n"]) for r in hit), sum(int(r["paise"]) for r in hit)

    man_c, man_c_v = _manual("CONFIRM")
    man_r, man_r_v = _manual("RETURN")
    pending = sum(int(r["n"]) for r in reviews if r["status"] == "PENDING")
    t = totals[0] if totals else {"n": 0, "paise": 0, "breached": 0}
    p = perf[0] if perf else {"avg_ms": 0, "p99_ms": 0, "near": 0}
    total = int(t["n"])
    return DecisionBreakdown(
        total_inward=total,
        stp_confirmed=stp_c, stp_returned=stp_r, manual_confirmed=man_c, manual_returned=man_r, pending_review=pending,
        total_value_paise=int(t["paise"]),
        stp_confirmed_value_paise=stp_c_v, stp_returned_value_paise=stp_r_v,
        manual_confirmed_value_paise=man_c_v, manual_returned_value_paise=man_r_v,
        stp_rate_pct=_pct(stp_c + stp_r, total), manual_rate_pct=_pct(man_c + man_r, total),
        return_rate_pct=_pct(stp_r + man_r, total),
        avg_decision_ms=int(p["avg_ms"]), p99_decision_ms=int(p["p99_ms"]), iet_near_breach_count=int(p["near"]),
    )


async def _outward_breakdown(conn: Any, bank_id: str, day: date) -> OutwardBreakdown:
    totals = await conn.fetch(
        """
        /* q:outward_totals */
        SELECT COUNT(*) AS n, COALESCE(SUM(amount_paise), 0) AS paise
          FROM cts.cheque_instruments
         WHERE bank_id = $1 AND direction = 'OUTWARD' AND received_at::date = $2::date
        """,
        bank_id, day,
    )
    returns = await conn.fetch(
        """
        /* q:outward_returns */
        SELECT return_reason_code, COUNT(*) AS n, COALESCE(SUM(original_amount_paise), 0) AS paise
          FROM cts.return_items
         WHERE bank_id = $1 AND outward_item_id IS NOT NULL AND created_at::date = $2::date
         GROUP BY return_reason_code
        """,
        bank_id, day,
    )
    t = totals[0] if totals else {"n": 0, "paise": 0}
    returned = sum(int(r["n"]) for r in returns)
    return OutwardBreakdown(
        total_outward=int(t["n"]), total_outward_value_paise=int(t["paise"]),
        ngch_accepted=int(t["n"]) - returned, ngch_returned=returned,
        ngch_returned_value_paise=sum(int(r["paise"]) for r in returns),
        return_reasons={str(r["return_reason_code"]): int(r["n"]) for r in returns},
    )


async def _net_settlement(conn: Any, bank_id: str, session_id: str) -> Optional[int]:
    """Known only once the session has been reconciled; None until then."""
    if session_id.upper() == "TODAY":
        return None
    rows = await conn.fetch(
        """
        /* q:settlement */
        SELECT net_position_paise FROM cts.settlement_positions
         WHERE bank_id = $1 AND session_id = $2::uuid
        """,
        bank_id, session_id,
    )
    return int(rows[0]["net_position_paise"]) if rows else None


async def _bankwise_rows(conn: Any, bank_id: str, day: date) -> list[dict]:
    inward = await conn.fetch(
        """
        /* q:bankwise_inward */
        SELECT COALESCE(ci.presenting_ifsc, '') AS ifsc, COUNT(*) AS n, COALESCE(SUM(ci.amount_paise), 0) AS paise,
               COUNT(*) FILTER (WHERE ad.decision = 'STP_CONFIRM' OR hr.reviewer_decision = 'CONFIRM') AS confirmed,
               COUNT(*) FILTER (WHERE ad.decision = 'STP_RETURN' OR hr.reviewer_decision = 'RETURN') AS returned,
               COALESCE(SUM(ci.amount_paise) FILTER (WHERE ad.decision = 'STP_CONFIRM' OR hr.reviewer_decision = 'CONFIRM'), 0) AS confirmed_paise
          FROM cts.cheque_instruments ci
          LEFT JOIN cts.agent_decisions ad ON ad.instrument_id = ci.instrument_id AND ad.bank_id = ci.bank_id
          LEFT JOIN cts.human_review_items hr ON hr.instrument_id = ci.instrument_id AND hr.bank_id = ci.bank_id
         WHERE ci.bank_id = $1 AND ci.direction = 'INWARD' AND ci.received_at::date = $2::date
         GROUP BY COALESCE(ci.presenting_ifsc, '')
         ORDER BY paise DESC
        """,
        bank_id, day,
    )
    outward = await conn.fetch(
        """
        /* q:bankwise_outward */
        SELECT COALESCE(ci.drawee_ifsc, '') AS ifsc, COUNT(*) AS n, COALESCE(SUM(ci.amount_paise), 0) AS paise,
               COUNT(*) FILTER (WHERE ri.return_id IS NULL) AS confirmed,
               COUNT(*) FILTER (WHERE ri.return_id IS NOT NULL) AS returned,
               COALESCE(SUM(ci.amount_paise) FILTER (WHERE ri.return_id IS NOT NULL), 0) AS returned_paise
          FROM cts.cheque_instruments ci
          LEFT JOIN cts.return_items ri ON ri.bank_id = ci.bank_id AND ri.cheque_number = ci.cheque_number AND ri.micr_code = ci.micr_code
         WHERE ci.bank_id = $1 AND ci.direction = 'OUTWARD' AND ci.received_at::date = $2::date
         GROUP BY COALESCE(ci.drawee_ifsc, '')
         ORDER BY paise DESC
        """,
        bank_id, day,
    )
    out = [{**dict(r), "perspective": "PRESENTING", "confirmed_paise": int(r["confirmed_paise"]), "returned_paise": 0} for r in inward]
    out += [{**dict(r), "perspective": "DRAWEE", "confirmed_paise": int(r["paise"]) - int(r["returned_paise"]),
             "returned_paise": int(r["returned_paise"])} for r in outward]
    return out


def _bank_label(ifsc: str) -> str:
    """No bank directory exists in the platform; the four-letter IFSC prefix identifies the bank."""
    return ifsc[:4] if ifsc else "UNKNOWN"


@router_v1.get("/sessions/{session_id}/summary", response_model=SessionSummaryResponse)
async def session_summary(
    session_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> SessionSummaryResponse:
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            row, day = await _load_session(conn, bank_id, session_id)
            if row is None:                      # 'TODAY' has no session row to describe
                raise _session_not_found()
            presenting = await _inward_breakdown(conn, bank_id, day)
            drawee = await _outward_breakdown(conn, bank_id, day)
            net = await _net_settlement(conn, bank_id, session_id)
    except HTTPException:
        raise
    except Exception:
        log.exception("batch.session_summary.db_error", bank_id=bank_id)
        raise _db_unavailable()
    return SessionSummaryResponse(
        session=_row_to_session_status(row), bank_id=bank_id, presenting_bank=presenting, drawee_bank=drawee,
        net_settlement_paise=net, generated_at=datetime.now(timezone.utc),
    )


@router_v1.get("/sessions/{session_id}/bankwise", response_model=BankwiseResponse)
async def session_bankwise(
    session_id: str,
    request: Request,
    perspective: Optional[Literal["PRESENTING", "DRAWEE", "ALL"]] = Query("ALL"),
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> BankwiseResponse:
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            _row, day = await _load_session(conn, bank_id, session_id)
            raw = await _bankwise_rows(conn, bank_id, day)
    except HTTPException:
        raise
    except Exception:
        log.exception("batch.bankwise.db_error", bank_id=bank_id)
        raise _db_unavailable()
    rows = [
        BankwiseRow(
            bank_ifsc=r["ifsc"], bank_name=_bank_label(r["ifsc"]), perspective=r["perspective"],
            cheque_count=int(r["n"]), total_value_paise=int(r["paise"]),
            confirmed_count=int(r["confirmed"]), returned_count=int(r["returned"]),
            return_rate_pct=_pct(int(r["returned"]), int(r["n"])),
        )
        for r in raw if perspective in (None, "ALL") or r["perspective"] == perspective
    ]
    return BankwiseResponse(session_id=session_id, bank_id=bank_id, rows=rows, generated_at=datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# File downloads
# ---------------------------------------------------------------------------

def _csv_response(rows: list[list], filename: str) -> Response:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def _rupees(paise: int) -> str:
    return f"{paise / 100:.2f}"


@router_v1.get("/sessions/{session_id}/download/npci")
async def download_npci_return_file(
    session_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> Response:
    """The Return Reason File reconciliation generated for this session, exactly as stored (not re-derived)."""
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            if session_id.upper() == "TODAY":
                rows = await conn.fetch(
                    """
                    /* q:rrf */
                    SELECT rrf_path, exception_count FROM cts.rrf_sessions
                     WHERE bank_id = $1 AND clearing_date = $2::date ORDER BY created_at DESC LIMIT 1
                    """,
                    bank_id, date.today(),
                )
            else:
                rows = await conn.fetch(
                    """
                    /* q:rrf */
                    SELECT rrf_path, exception_count FROM cts.rrf_sessions
                     WHERE bank_id = $1 AND session_id = $2 LIMIT 1
                    """,
                    bank_id, session_id,
                )
    except Exception:
        log.exception("batch.download_npci.db_error", bank_id=bank_id)
        raise _db_unavailable()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "CTS_RRF_NOT_FOUND", "message": get_message("API_BATCH_RRF_NOT_FOUND")},
        )
    try:
        content = await fetch_object_bytes(f"s3://astra-cts/{rows[0]['rrf_path']}")
    except Exception:
        log.exception("batch.download_npci.storage_error", bank_id=bank_id)
        raise _db_unavailable()
    return Response(content=content, media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename=NPCI_RRF_{bank_id.upper()}_{session_id}.xml"})


@router_v1.get("/sessions/{session_id}/download/mis")
async def download_mis_report(
    session_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> Response:
    """Internal MIS report: the same figures as the summary endpoint. Aggregates only, no account data."""
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            _row, day = await _load_session(conn, bank_id, session_id)
            p = await _inward_breakdown(conn, bank_id, day)
            w = await _outward_breakdown(conn, bank_id, day)
    except HTTPException:
        raise
    except Exception:
        log.exception("batch.download_mis.db_error", bank_id=bank_id)
        raise _db_unavailable()
    rows: list[list] = [
        [get_message("API_ASTRA_MIS_REPORT"), get_message("API_SESSION", session_id=session_id), get_message("API_BANK", bank_id=bank_id), get_message("API_CLEARING_DATE", day=day)], [],
        [get_message("API_SECTION_1_INWARD_SUMMARY_PRESENTING_2")], ["Metric", "Count", get_message("API_VALUE_INR")],
        [get_message("UI_COMMON_TOTAL_INWARD"), p.total_inward, _rupees(p.total_value_paise)],
        [get_message("UI_COMMON_STP_CONFIRMED"), p.stp_confirmed, _rupees(p.stp_confirmed_value_paise)],
        [get_message("UI_COMMON_STP_RETURNED"), p.stp_returned, _rupees(p.stp_returned_value_paise)],
        [get_message("UI_COMMON_MANUAL_CONFIRMED"), p.manual_confirmed, _rupees(p.manual_confirmed_value_paise)],
        [get_message("UI_OPSDASHBOARDBODY_MANUAL_RETURNED"), p.manual_returned, _rupees(p.manual_returned_value_paise)],
        [get_message("UI_OPSDASHBOARDBODY_PENDING_REVIEW"), p.pending_review, ""], [],
        [get_message("API_SECTION_2_OUTWARD_SUMMARY_DRAWEE_2")], ["Metric", "Count", get_message("API_VALUE_INR")],
        [get_message("UI_OPSDASHBOARDBODY_TOTAL_OUTWARD"), w.total_outward, _rupees(w.total_outward_value_paise)],
        [get_message("UI_DRAWEEVIEW_NGCH_ACCEPTED"), w.ngch_accepted, ""],
        [get_message("UI_DRAWEEVIEW_NGCH_RETURNED"), w.ngch_returned, _rupees(w.ngch_returned_value_paise)], [],
        [get_message("API_SECTION_3_RETURN_REASONS_2")], [get_message("API_REASON_CODE"), "Count"],
        *[[code, n] for code, n in sorted(w.return_reasons.items())], [],
        [get_message("API_SECTION_4_PERFORMANCE_2")], ["Metric", "Value"],
        [get_message("UI_COMMON_STP_RATE"), f"{p.stp_rate_pct}%"], [get_message("UI_COMMON_RETURN_RATE"), f"{p.return_rate_pct}%"],
        [get_message("API_AVG_DECISION_TIME_MS"), p.avg_decision_ms], [get_message("API_P99_DECISION_TIME_MS"), p.p99_decision_ms],
        [get_message("API_IET_NEAR_BREACH_COUNT"), p.iet_near_breach_count],
    ]
    return _csv_response(rows, f"MIS_{bank_id.upper()}_{session_id}_{date.today()}.csv")


@router_v1.get("/sessions/{session_id}/download/settlement")
async def download_settlement_statement(
    session_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> Response:
    """Position by counterparty: receivable (our outward cheques not returned) less payable (inward we confirmed).
    Indicative only: the binding net position is NPCI's, recorded on reconciliation."""
    pool = _pool(request)
    try:
        async with pool.acquire() as conn:
            _row, day = await _load_session(conn, bank_id, session_id)
            raw = await _bankwise_rows(conn, bank_id, day)
    except HTTPException:
        raise
    except Exception:
        log.exception("batch.download_settlement.db_error", bank_id=bank_id)
        raise _db_unavailable()
    by_bank: dict[str, dict] = {}
    for r in raw:
        b = by_bank.setdefault(r["ifsc"], {"payable": 0, "receivable": 0})
        if r["perspective"] == "PRESENTING":
            b["payable"] += int(r["confirmed_paise"])
        else:
            b["receivable"] += int(r["confirmed_paise"])
    rows: list[list] = [
        [get_message("API_SETTLEMENT_POSITION_STATEMENT_INDICA"), get_message("API_SESSION", session_id=session_id), get_message("API_CLEARING_DATE", day=day)],
        [get_message("UI_SCANNER_BANK_IFSC"), "Bank", get_message("API_INWARD_CONFIRMED_PAYABLE_INR"), get_message("API_OUTWARD_NOT_RETURNED_RECEIVABLE_INR"), get_message("API_NET_POSITION_INR"), "Direction"],
    ]
    for ifsc, b in sorted(by_bank.items()):
        net = b["receivable"] - b["payable"]
        rows.append([ifsc, _bank_label(ifsc), _rupees(b["payable"]), _rupees(b["receivable"]), _rupees(net),
                     "RECEIVE" if net > 0 else "PAY" if net < 0 else "NIL"])
    return _csv_response(rows, f"SETTLEMENT_{bank_id.upper()}_{session_id}.csv")


# ---------------------------------------------------------------------------
# Ops dashboard
# ---------------------------------------------------------------------------

class OpsSession(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    slot: str
    status: str


class OpsDayRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    inward: int
    outward: int
    inward_value_cr: float
    return_rate_pct: float
    stp_rate_pct: float
    iet_breach: int


class OpsTodayRow(OpsDayRow):
    sessions: list[OpsSession]


class OpsDashboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    today: OpsTodayRow
    trend: list[OpsDayRow]
    generated_at: datetime


@router_v1.get("/dashboard/ops", response_model=OpsDashboardResponse)
async def ops_dashboard(
    request: Request,
    days: int = Query(7, ge=1, le=30),
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> OpsDashboardResponse:
    """Ops head morning view: last N days plus today's sessions."""
    pool = _pool(request)
    today = date.today()
    try:
        async with pool.acquire() as conn:
            inst = await conn.fetch(
                """
                /* q:ops_instruments */
                SELECT received_at::date AS day,
                       COUNT(*) FILTER (WHERE direction = 'INWARD')  AS inward,
                       COUNT(*) FILTER (WHERE direction = 'OUTWARD') AS outward,
                       COALESCE(SUM(amount_paise) FILTER (WHERE direction = 'INWARD'), 0) AS inward_paise,
                       COUNT(*) FILTER (WHERE iet_breached) AS breached
                  FROM cts.cheque_instruments
                 WHERE bank_id = $1 AND received_at::date > ($2::date - $3::int)
                 GROUP BY 1
                """,
                bank_id, today, days,
            )
            decisions = await conn.fetch(
                """
                /* q:ops_decisions */
                SELECT ci.received_at::date AS day, COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE ad.decision = 'STP_CONFIRM') AS stp_confirmed,
                       COUNT(*) FILTER (WHERE ad.decision IN ('STP_RETURN', 'AUTO_RETURN')) AS returned
                  FROM cts.agent_decisions ad
                  JOIN cts.cheque_instruments ci ON ci.instrument_id = ad.instrument_id AND ci.bank_id = ad.bank_id
                 WHERE ad.bank_id = $1 AND ci.direction = 'INWARD' AND ci.received_at::date > ($2::date - $3::int)
                 GROUP BY 1
                """,
                bank_id, today, days,
            )
            sessions = await conn.fetch(
                """
                /* q:ops_sessions */
                SELECT session_id, session_date, session_type, status, created_at,
                       presentation_open_at, presentation_close_at, settlement_at
                  FROM cts.clearing_sessions
                 WHERE bank_id = $1 AND session_date = $2::date
                 ORDER BY session_type
                """,
                bank_id, today,
            )
    except Exception:
        log.exception("batch.ops_dashboard.db_error", bank_id=bank_id)
        raise _db_unavailable()

    i_by = {r["day"]: r for r in inst}
    d_by = {r["day"]: r for r in decisions}

    def _day(d: date) -> OpsDayRow:
        i, k = i_by.get(d), d_by.get(d)
        total = int(k["total"]) if k else 0
        return OpsDayRow(
            date=d.isoformat(),
            inward=int(i["inward"]) if i else 0, outward=int(i["outward"]) if i else 0,
            inward_value_cr=round(int(i["inward_paise"]) / 1e9, 2) if i else 0.0,   # 1 crore = 1e9 paise
            return_rate_pct=_pct(int(k["returned"]), total) if k else 0.0,
            stp_rate_pct=_pct(int(k["stp_confirmed"]), total) if k else 0.0,
            iet_breach=int(i["breached"]) if i else 0,
        )

    trend = [_day(today - timedelta(days=n)) for n in range(days - 1, -1, -1)]
    statuses = [_row_to_session_status(dict(r)) for r in sessions]
    return OpsDashboardResponse(
        bank_id=bank_id,
        today=OpsTodayRow(
            **_day(today).model_dump(),
            sessions=[OpsSession(id=str(r["session_id"]), slot=s.session_slot, status=s.status)
                      for r, s in zip(sessions, statuses)],
        ),
        trend=trend, generated_at=datetime.now(timezone.utc),
    )
