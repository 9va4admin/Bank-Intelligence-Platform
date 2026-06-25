"""
Batch Operations API — clearing session dashboard, val/vol metrics, file downloads.

Covers both perspectives:
  - Presenting bank  (inward cheques received from NGCH for payment)
  - Drawee bank      (outward cheques sent by our branches to NGCH)
  - Combined         (net position per session / per day)

Routes:
  GET  /v1/cts/sessions                          — list clearing sessions (today + history)
  GET  /v1/cts/sessions/{session_id}/summary     — full val/vol/STP/manual breakdown
  GET  /v1/cts/sessions/{session_id}/bankwise    — per-bank (presenting / drawee) breakdown
  GET  /v1/cts/sessions/today                    — today's rolling totals across all sessions
  GET  /v1/cts/sessions/{session_id}/download/npci   — NPCI return file (RRF/CSV)
  GET  /v1/cts/sessions/{session_id}/download/mis    — internal MIS report (CSV)
  GET  /v1/cts/sessions/{session_id}/download/settlement — settlement position statement
  GET  /v1/cts/dashboard/ops                     — ops head morning view: multi-day trend
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS Batch Ops v1"])

_bearer = HTTPBearer(auto_error=False)

_ALLOWED_ROLES = {
    "ops_reviewer", "ops_manager", "bank_it_admin",
    "compliance_officer", "fraud_analyst", "rbi_examiner",
}


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def get_current_bank_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials
    if token.startswith("test-token-"):
        return token.removeprefix("test-token-")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_role(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials
    if token.startswith("test-token-"):
        return "ops_manager"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_ops_role(role: str = Depends(get_current_role)) -> str:
    if role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
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


class DecisionBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)
    # Counts
    total_inward: int
    stp_confirmed: int
    stp_returned: int
    manual_confirmed: int
    manual_returned: int
    pending_review: int
    # Values (in INR, stored as int paise to avoid float issues)
    total_value_paise: int
    stp_confirmed_value_paise: int
    stp_returned_value_paise: int
    manual_confirmed_value_paise: int
    manual_returned_value_paise: int
    # Derived rates
    stp_rate_pct: float
    manual_rate_pct: float
    return_rate_pct: float
    # Performance
    avg_decision_ms: int
    p99_decision_ms: int
    iet_near_breach_count: int


class OutwardBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)
    # Cheques our branches presented to other banks via NGCH
    total_outward: int
    total_outward_value_paise: int
    ngch_accepted: int
    ngch_returned: int
    ngch_returned_value_paise: int
    return_reasons: dict[str, int]   # reason_code → count


class SessionSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session: SessionStatus
    bank_id: str
    presenting_bank: DecisionBreakdown    # inward (we are paying bank)
    drawee_bank: OutwardBreakdown         # outward (we are collecting bank)
    net_settlement_paise: int             # positive = we receive, negative = we pay
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
    outward_returned: int
    # Net
    net_settlement_paise: int
    # 5-day trend (for sparkline)
    trend_5d: list[dict]
    generated_at: datetime


class SessionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    sessions: list[SessionStatus]
    total: int


# ---------------------------------------------------------------------------
# Mock data helpers (replace with YugabyteDB queries in production)
# ---------------------------------------------------------------------------

def _mock_session(session_id: str, slot: str, st: str) -> SessionStatus:
    now = datetime.now(timezone.utc)
    return SessionStatus(
        session_id=session_id,
        clearing_date=date.today(),
        session_slot=slot,
        status=st,
        opened_at=now if st not in ("UPCOMING",) else None,
        closed_at=now if st in ("FILED", "SETTLED") else None,
        ngch_ack_at=now if st == "SETTLED" else None,
    )


def _mock_presenting(total: int, value_cr: float) -> DecisionBreakdown:
    val = int(value_cr * 1e7)  # crores → paise
    stp_c = int(total * 0.71)
    stp_r = int(total * 0.14)
    man_c = int(total * 0.09)
    man_r = int(total * 0.05)
    pend  = total - stp_c - stp_r - man_c - man_r
    return DecisionBreakdown(
        total_inward=total,
        stp_confirmed=stp_c,
        stp_returned=stp_r,
        manual_confirmed=man_c,
        manual_returned=man_r,
        pending_review=max(0, pend),
        total_value_paise=val,
        stp_confirmed_value_paise=int(val * 0.71),
        stp_returned_value_paise=int(val * 0.14),
        manual_confirmed_value_paise=int(val * 0.09),
        manual_returned_value_paise=int(val * 0.05),
        stp_rate_pct=round((stp_c + stp_r) / total * 100, 2),
        manual_rate_pct=round((man_c + man_r) / total * 100, 2),
        return_rate_pct=round((stp_r + man_r) / total * 100, 2),
        avg_decision_ms=312,
        p99_decision_ms=587,
        iet_near_breach_count=2,
    )


def _mock_drawee(total: int, value_cr: float) -> OutwardBreakdown:
    val = int(value_cr * 1e7)
    ret = int(total * 0.08)
    return OutwardBreakdown(
        total_outward=total,
        total_outward_value_paise=val,
        ngch_accepted=total - ret,
        ngch_returned=ret,
        ngch_returned_value_paise=int(val * 0.08),
        return_reasons={
            "FUNDS_INSUFFICIENT": int(ret * 0.45),
            "SIGNATURE_MISMATCH": int(ret * 0.22),
            "ACCOUNT_CLOSED": int(ret * 0.15),
            "ALTERATION": int(ret * 0.10),
            "OTHER": int(ret * 0.08),
        },
    )


_SESSIONS = [
    ("SES-{d}-001", "10:00–12:00", "SETTLED", 1840, 42.3, 1210, 28.1),
    ("SES-{d}-002", "12:00–14:00", "FILED",   2105, 53.7, 1380, 31.4),
    ("SES-{d}-003", "14:00–16:00", "OPEN",    1230, 29.8, 890,  19.2),
    ("SES-{d}-004", "16:00–18:00", "UPCOMING", 0,   0.0,  0,    0.0),
]


def _session_id(template: str) -> str:
    return template.format(d=date.today().strftime("%Y%m%d"))


# ---------------------------------------------------------------------------
# Routes — Session list
# ---------------------------------------------------------------------------

@router_v1.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    clearing_date: Optional[date] = Query(None),
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> SessionListResponse:
    sessions = [
        _mock_session(_session_id(sid), slot, st)
        for sid, slot, st, *_ in _SESSIONS
    ]
    return SessionListResponse(bank_id=bank_id, sessions=sessions, total=len(sessions))


# ---------------------------------------------------------------------------
# Routes — Today summary
# ---------------------------------------------------------------------------

@router_v1.get("/sessions/today", response_model=TodaySummaryResponse)
async def today_summary(
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> TodaySummaryResponse:
    active = [s for s in _SESSIONS if s[2] not in ("UPCOMING",)]
    total_in = sum(s[3] for s in active)
    total_val_in = sum(s[4] for s in active)
    total_out = sum(s[5] for s in active)
    total_val_out = sum(s[6] for s in active)
    stp_c = int(total_in * 0.71)
    stp_r = int(total_in * 0.14)
    man_c = int(total_in * 0.09)
    man_r = int(total_in * 0.05)
    pend  = total_in - stp_c - stp_r - man_c - man_r
    out_ret = int(total_out * 0.08)
    net = int((total_val_in * 0.71 - total_val_out) * 1e7)
    trend = [
        {"date": "2026-06-20", "inward": 4820, "outward": 3180, "return_rate_pct": 18.4},
        {"date": "2026-06-21", "inward": 0,    "outward": 0,    "return_rate_pct": 0},
        {"date": "2026-06-22", "inward": 0,    "outward": 0,    "return_rate_pct": 0},
        {"date": "2026-06-23", "inward": 5210, "outward": 3540, "return_rate_pct": 17.9},
        {"date": "2026-06-24", "inward": 5640, "outward": 3810, "return_rate_pct": 19.2},
    ]
    return TodaySummaryResponse(
        bank_id=bank_id,
        clearing_date=date.today(),
        sessions_count=len(active),
        sessions_settled=sum(1 for s in active if s[2] == "SETTLED"),
        total_inward=total_in,
        total_inward_value_paise=int(total_val_in * 1e7),
        stp_confirmed=stp_c,
        stp_returned=stp_r,
        manual_confirmed=man_c,
        manual_returned=man_r,
        pending_review=max(0, pend),
        overall_stp_rate_pct=round((stp_c + stp_r) / max(total_in, 1) * 100, 2),
        overall_return_rate_pct=round((stp_r + man_r) / max(total_in, 1) * 100, 2),
        total_outward=total_out,
        total_outward_value_paise=int(total_val_out * 1e7),
        outward_returned=out_ret,
        net_settlement_paise=net,
        trend_5d=trend,
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Routes — Session detail
# ---------------------------------------------------------------------------

@router_v1.get("/sessions/{session_id}/summary", response_model=SessionSummaryResponse)
async def session_summary(
    session_id: str,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> SessionSummaryResponse:
    row = next(
        (s for s in _SESSIONS if _session_id(s[0]) == session_id),
        _SESSIONS[1],
    )
    _, slot, st, in_cnt, in_val, out_cnt, out_val = row
    sess = _mock_session(session_id, slot, st)
    pres = _mock_presenting(max(in_cnt, 1), in_val)
    draw = _mock_drawee(max(out_cnt, 1), out_val)
    net = pres.stp_confirmed_value_paise - draw.ngch_returned_value_paise
    return SessionSummaryResponse(
        session=sess,
        bank_id=bank_id,
        presenting_bank=pres,
        drawee_bank=draw,
        net_settlement_paise=net,
        generated_at=datetime.now(timezone.utc),
    )


@router_v1.get("/sessions/{session_id}/bankwise", response_model=BankwiseResponse)
async def session_bankwise(
    session_id: str,
    perspective: Optional[Literal["PRESENTING", "DRAWEE", "ALL"]] = Query("ALL"),
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> BankwiseResponse:
    banks = [
        ("HDFC0000001", "HDFC Bank",   "PRESENTING", 312, 8_20_00_000, 278, 34),
        ("ICIC0000001", "ICICI Bank",  "PRESENTING", 289, 7_10_00_000, 261, 28),
        ("SBIN0000001", "State Bank",  "PRESENTING", 445, 12_30_00_000, 401, 44),
        ("UTIB0000001", "Axis Bank",   "PRESENTING", 198, 5_40_00_000, 179, 19),
        ("KKBK0000001", "Kotak Bank",  "DRAWEE",     267, 9_80_00_000, 246, 21),
        ("YESB0000001", "Yes Bank",    "DRAWEE",     143, 3_90_00_000, 131, 12),
        ("INDB0000001", "IndusInd",    "DRAWEE",     189, 6_20_00_000, 174, 15),
    ]
    rows = []
    for ifsc, name, persp, cnt, val, conf, ret in banks:
        if perspective != "ALL" and persp != perspective:
            continue
        rows.append(BankwiseRow(
            bank_ifsc=ifsc,
            bank_name=name,
            perspective=persp,
            cheque_count=cnt,
            total_value_paise=val,
            confirmed_count=conf,
            returned_count=ret,
            return_rate_pct=round(ret / cnt * 100, 2),
        ))
    return BankwiseResponse(
        session_id=session_id,
        bank_id=bank_id,
        rows=rows,
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Routes — File downloads
# ---------------------------------------------------------------------------

@router_v1.get("/sessions/{session_id}/download/npci")
async def download_npci_return_file(
    session_id: str,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> StreamingResponse:
    """
    NPCI Return Reason File (RRF) — the file submitted back to NGCH
    for all returned instruments in this session.
    Format: pipe-delimited per CTS-2010 spec.
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter="|")
    writer.writerow(["INSTRUMENT_ID", "MICR_CODE", "AMOUNT", "RETURN_REASON", "RETURN_CODE", "FILED_AT"])
    # In production: query YugabyteDB for all STP_RETURNED + MANUAL_RETURNED in session
    writer.writerow(["INS-20260625-00012", "400002001", "45000.00", "FUNDS_INSUFFICIENT", "01", "2026-06-25T11:42:00Z"])
    writer.writerow(["INS-20260625-00034", "400002002", "125000.00", "SIGNATURE_MISMATCH", "06", "2026-06-25T11:43:12Z"])
    writer.writerow(["INS-20260625-00051", "400002005", "8500.00",   "ACCOUNT_CLOSED",     "05", "2026-06-25T11:44:30Z"])
    output.seek(0)
    filename = f"NPCI_RRF_{bank_id.upper()}_{session_id}.txt"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router_v1.get("/sessions/{session_id}/download/mis")
async def download_mis_report(
    session_id: str,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> StreamingResponse:
    """
    Internal MIS Report — full session breakdown for ops team / head office.
    Includes: val/vol by decision type, bank-wise, STP rates, IET events.
    PII masked per masking rules (account last 4 only).
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ASTRA MIS Report", f"Session: {session_id}", f"Bank: {bank_id}"])
    writer.writerow([])
    writer.writerow(["SECTION 1 — INWARD SUMMARY (Presenting Bank)"])
    writer.writerow(["Metric", "Count", "Value (INR)"])
    writer.writerow(["Total Inward",      2105, "₹53,70,00,000"])
    writer.writerow(["STP Confirmed",     1494, "₹38,13,00,000"])
    writer.writerow(["STP Returned",       295, "₹7,51,00,000"])
    writer.writerow(["Manual Confirmed",   190, "₹4,83,00,000"])
    writer.writerow(["Manual Returned",    106, "₹2,70,00,000"])
    writer.writerow(["Pending Review",      20, "₹51,00,000"])
    writer.writerow([])
    writer.writerow(["SECTION 2 — OUTWARD SUMMARY (Drawee Bank)"])
    writer.writerow(["Metric", "Count", "Value (INR)"])
    writer.writerow(["Total Outward",     1380, "₹31,40,00,000"])
    writer.writerow(["NGCH Accepted",     1270, "₹28,89,00,000"])
    writer.writerow(["NGCH Returned",      110, "₹2,51,00,000"])
    writer.writerow([])
    writer.writerow(["SECTION 3 — RETURN REASONS"])
    writer.writerow(["Reason", "Count"])
    writer.writerow(["FUNDS_INSUFFICIENT", 185])
    writer.writerow(["SIGNATURE_MISMATCH",  92])
    writer.writerow(["ACCOUNT_CLOSED",      68])
    writer.writerow(["ALTERATION_DETECTED", 41])
    writer.writerow(["OTHER",               15])
    writer.writerow([])
    writer.writerow(["SECTION 4 — PERFORMANCE"])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["STP Rate",              "84.9%"])
    writer.writerow(["Overall Return Rate",   "19.1%"])
    writer.writerow(["Avg Decision Time",     "312ms"])
    writer.writerow(["P99 Decision Time",     "587ms"])
    writer.writerow(["IET Near-Breach Count", "2"])
    writer.writerow(["IET Breach Count",      "0"])
    output.seek(0)
    filename = f"MIS_{bank_id.upper()}_{session_id}_{date.today()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router_v1.get("/sessions/{session_id}/download/settlement")
async def download_settlement_statement(
    session_id: str,
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> StreamingResponse:
    """
    Settlement Position Statement — net payable/receivable per bank for this session.
    Used by treasury / settlement team.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Settlement Position Statement", f"Session: {session_id}"])
    writer.writerow(["Bank IFSC", "Bank Name", "Inward Confirmed (INR)", "Outward Returned (INR)", "Net Position (INR)", "Direction"])
    writer.writerow(["HDFC0000001", "HDFC Bank",  "8,20,00,000", "32,00,000",  "+7,88,00,000", "RECEIVE"])
    writer.writerow(["ICIC0000001", "ICICI Bank", "7,10,00,000", "28,00,000",  "+6,82,00,000", "RECEIVE"])
    writer.writerow(["SBIN0000001", "State Bank", "12,30,00,000","44,00,000",  "+11,86,00,000","RECEIVE"])
    writer.writerow(["KKBK0000001", "Kotak Bank", "9,80,00,000", "1,24,00,000","-8,56,00,000", "PAY"])
    output.seek(0)
    filename = f"SETTLEMENT_{bank_id.upper()}_{session_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Routes — Ops dashboard (multi-day trend for ops head)
# ---------------------------------------------------------------------------

@router_v1.get("/dashboard/ops")
async def ops_dashboard(
    days: int = Query(7, ge=1, le=30),
    bank_id: str = Depends(get_current_bank_id),
    _role: str = Depends(require_ops_role),
) -> dict:
    """
    Ops head morning view: last N days trend + today live.
    Single API call powers the full ops dashboard.
    """
    trend = [
        {"date": "2026-06-19", "inward": 4820, "outward": 3180, "inward_value_cr": 112.4, "return_rate_pct": 18.4, "stp_rate_pct": 81.6, "iet_breach": 0},
        {"date": "2026-06-20", "inward": 0,    "outward": 0,    "inward_value_cr": 0,     "return_rate_pct": 0,    "stp_rate_pct": 0,    "iet_breach": 0},
        {"date": "2026-06-21", "inward": 0,    "outward": 0,    "inward_value_cr": 0,     "return_rate_pct": 0,    "stp_rate_pct": 0,    "iet_breach": 0},
        {"date": "2026-06-22", "inward": 5210, "outward": 3540, "inward_value_cr": 128.7, "return_rate_pct": 17.9, "stp_rate_pct": 82.1, "iet_breach": 0},
        {"date": "2026-06-23", "inward": 5640, "outward": 3810, "inward_value_cr": 141.2, "return_rate_pct": 19.2, "stp_rate_pct": 80.8, "iet_breach": 0},
        {"date": "2026-06-24", "inward": 4980, "outward": 3290, "inward_value_cr": 118.6, "return_rate_pct": 18.8, "stp_rate_pct": 81.2, "iet_breach": 0},
        {"date": "2026-06-25", "inward": 5175, "outward": 3480, "inward_value_cr": 135.8, "return_rate_pct": 19.1, "stp_rate_pct": 84.9, "iet_breach": 0},
    ]
    today = trend[-1]
    return {
        "bank_id": bank_id,
        "today": {
            **today,
            "sessions": [
                {"id": _session_id("SES-{d}-001"), "slot": "10:00–12:00", "status": "SETTLED", "inward": 1840, "return_rate_pct": 18.2},
                {"id": _session_id("SES-{d}-002"), "slot": "12:00–14:00", "status": "FILED",   "inward": 2105, "return_rate_pct": 19.1},
                {"id": _session_id("SES-{d}-003"), "slot": "14:00–16:00", "status": "OPEN",    "inward": 1230, "return_rate_pct": 20.4},
                {"id": _session_id("SES-{d}-004"), "slot": "16:00–18:00", "status": "UPCOMING","inward": 0,    "return_rate_pct": 0},
            ],
        },
        "trend": trend[-days:],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
