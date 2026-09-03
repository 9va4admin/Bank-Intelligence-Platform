"""
CTS Ops supplementary endpoints — secondary monitoring and reporting panels.

Covers the 14 endpoints that were previously unbuilt:
  SMB:     /smb/ops-summary, /smb/settlement, /smb/return-events
  Inward:  /inward/drawee-stats, /inward/human-review-queue
  Admin:   /admin/ngch-status, /admin/kafka-stats
  RPC:     /rpc/cross-centre-alerts
  Outward: /outward/audit-events
  Branch:  /branch/session, /branch/sessions, /branch/eeh-health
  Agency:  /agency/inward-relay-stats, /agency/push-sessions

Patterns followed throughout:
  - RBAC via require_user_context dependency
  - DB: request.app.state.db_pool_cts — always null-checked, graceful empty default
  - Kafka: request.app.state.kafka_admin — always null-checked
  - No SELECT * on any table containing PII
  - Explicit column lists; bank_id in every WHERE clause
  - PII masked: account → ****{last4}, amounts → range bucket
  - structlog (never print)
  - Immudb audit write is NOT required for read-only GET endpoints
"""
import structlog
from datetime import date, datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()
router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS Ops v1"])


async def _ctx(ctx: UserContext = Depends(require_user_context)) -> UserContext:
    return ctx


# ─── Shared helpers ──────────────────────────────────────────────────────────

def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _mask_account(last4: Optional[str]) -> str:
    return f"****{last4}" if last4 else "****"


# ─── SMB Ops Summary ─────────────────────────────────────────────────────────

class SMBOpsToday(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int
    stp_pass: int
    stp_return: int
    human_review: int


class SMBOpsTrendPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    clearing_date: str
    total: int


class SMBOpsSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    today: SMBOpsToday
    trend: list[SMBOpsTrendPoint]
    degraded: bool


@router_v1.get("/smb/ops-summary", response_model=SMBOpsSummaryResponse)
async def smb_ops_summary(
    request: Request,
    smb_id: Optional[str] = Query(None),
    ctx: UserContext = Depends(_ctx),
) -> SMBOpsSummaryResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = SMBOpsSummaryResponse(
        today=SMBOpsToday(total=0, stp_pass=0, stp_return=0, human_review=0),
        trend=[],
        degraded=True,
    )
    if db is None:
        return empty
    try:
        today = _today_utc()
        if smb_id:
            row = await db.fetchrow(
                """
                SELECT
                    COALESCE(SUM(total_received), 0)  AS total,
                    COALESCE(SUM(stp_pass), 0)        AS stp_pass,
                    COALESCE(SUM(stp_return), 0)      AS stp_return,
                    COALESCE(SUM(human_review), 0)    AS human_review
                FROM cts.sub_member_batch_ledgers
                WHERE bank_id = $1
                  AND sub_member_id = $2
                  AND session_date = $3
                """,
                bank_id, smb_id, today,
            )
            trend_rows = await db.fetch(
                """
                SELECT
                    session_date::text                AS clearing_date,
                    COALESCE(SUM(total_received), 0)  AS total
                FROM cts.sub_member_batch_ledgers
                WHERE bank_id = $1
                  AND sub_member_id = $2
                  AND session_date >= ($3 - INTERVAL '6 days')
                GROUP BY session_date
                ORDER BY session_date ASC
                """,
                bank_id, smb_id, today,
            )
        else:
            row = await db.fetchrow(
                """
                SELECT
                    COALESCE(SUM(total_received), 0)  AS total,
                    COALESCE(SUM(stp_pass), 0)        AS stp_pass,
                    COALESCE(SUM(stp_return), 0)      AS stp_return,
                    COALESCE(SUM(human_review), 0)    AS human_review
                FROM cts.sub_member_batch_ledgers
                WHERE bank_id = $1
                  AND session_date = $2
                """,
                bank_id, today,
            )
            trend_rows = await db.fetch(
                """
                SELECT
                    session_date::text                AS clearing_date,
                    COALESCE(SUM(total_received), 0)  AS total
                FROM cts.sub_member_batch_ledgers
                WHERE bank_id = $1
                  AND session_date >= ($2 - INTERVAL '6 days')
                GROUP BY session_date
                ORDER BY session_date ASC
                """,
                bank_id, today,
            )
        today_data = SMBOpsToday(
            total=int(row["total"]),
            stp_pass=int(row["stp_pass"]),
            stp_return=int(row["stp_return"]),
            human_review=int(row["human_review"]),
        )
        trend = [
            SMBOpsTrendPoint(clearing_date=r["clearing_date"], total=int(r["total"]))
            for r in trend_rows
        ]
        return SMBOpsSummaryResponse(today=today_data, trend=trend, degraded=False)
    except Exception as exc:
        log.error("cts.smb_ops_summary.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── SMB Settlement ──────────────────────────────────────────────────────────

class SMBSettlementLeg(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    presented_count: int
    returned_count: int
    net_instruments: int


class SMBSettlementResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    clearing_date: str
    legs: list[SMBSettlementLeg]
    degraded: bool


@router_v1.get("/smb/settlement", response_model=SMBSettlementResponse)
async def smb_settlement(
    request: Request,
    ctx: UserContext = Depends(_ctx),
) -> SMBSettlementResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    today = _today_utc()
    empty = SMBSettlementResponse(clearing_date=str(today), legs=[], degraded=True)
    if db is None:
        return empty
    try:
        rows = await db.fetch(
            """
            SELECT
                sub_member_id,
                COALESCE(SUM(total_received), 0)  AS presented_count,
                COALESCE(SUM(stp_return), 0)      AS returned_count
            FROM cts.sub_member_batch_ledgers
            WHERE bank_id = $1
              AND session_date = $2
            GROUP BY sub_member_id
            ORDER BY sub_member_id ASC
            """,
            bank_id, today,
        )
        legs = [
            SMBSettlementLeg(
                sub_member_id=r["sub_member_id"],
                presented_count=int(r["presented_count"]),
                returned_count=int(r["returned_count"]),
                net_instruments=int(r["presented_count"]) - int(r["returned_count"]),
            )
            for r in rows
        ]
        return SMBSettlementResponse(clearing_date=str(today), legs=legs, degraded=False)
    except Exception as exc:
        log.error("cts.smb_settlement.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── SMB Return Events ───────────────────────────────────────────────────────

class SMBReturnEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    account_display: str
    decision: str
    decision_reason: str
    returned_at: str


class SMBReturnEventsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[SMBReturnEvent]
    total: int
    degraded: bool


@router_v1.get("/smb/return-events", response_model=SMBReturnEventsResponse)
async def smb_return_events(
    request: Request,
    limit: int = Query(default=50, le=100),
    ctx: UserContext = Depends(_ctx),
) -> SMBReturnEventsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = SMBReturnEventsResponse(items=[], total=0, degraded=True)
    if db is None:
        return empty
    try:
        rows = await db.fetch(
            """
            SELECT
                ad.instrument_id,
                ci.account_last4,
                ad.decision,
                ad.decision_reason,
                ad.created_at
            FROM cts.agent_decisions ad
            JOIN cts.cheque_instruments ci
              ON ci.instrument_id = ad.instrument_id
             AND ci.bank_id = ad.bank_id
            WHERE ad.bank_id = $1
              AND ad.decision IN ('STP_RETURN', 'MANUAL_RETURN', 'AUTO_RETURN')
            ORDER BY ad.created_at DESC
            LIMIT $2
            """,
            bank_id, limit,
        )
        count_row = await db.fetchrow(
            """
            SELECT COUNT(*) AS n
            FROM cts.agent_decisions
            WHERE bank_id = $1
              AND decision IN ('STP_RETURN', 'MANUAL_RETURN', 'AUTO_RETURN')
            """,
            bank_id,
        )
        items = [
            SMBReturnEvent(
                instrument_id=r["instrument_id"],
                account_display=_mask_account(r["account_last4"]),
                decision=r["decision"],
                decision_reason=r["decision_reason"] or "—",
                returned_at=r["created_at"].isoformat() if r["created_at"] else "",
            )
            for r in rows
        ]
        return SMBReturnEventsResponse(
            items=items,
            total=int(count_row["n"]) if count_row else 0,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.smb_return_events.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Inward Drawee Stats ──────────────────────────────────────────────────────

class DraweeBranch(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    name: str
    total: int
    returned: int
    value_cr: float


class DraweeStatsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    branches: list[DraweeBranch]
    return_reasons: dict[str, int]
    presenting_banks: list[dict]
    degraded: bool


@router_v1.get("/inward/drawee-stats", response_model=DraweeStatsResponse)
async def inward_drawee_stats(
    request: Request,
    session: Optional[str] = Query(None),
    ctx: UserContext = Depends(_ctx),
) -> DraweeStatsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = DraweeStatsResponse(branches=[], return_reasons={}, presenting_banks=[], degraded=True)
    if db is None:
        return empty
    try:
        today = _today_utc()
        branch_rows = await db.fetch(
            """
            SELECT
                b.branch_id,
                b.branch_name,
                COUNT(ad.instrument_id)                                   AS total,
                COUNT(ad.instrument_id)
                  FILTER (WHERE ad.decision IN ('STP_RETURN','MANUAL_RETURN','AUTO_RETURN')) AS returned
            FROM cts.agent_decisions ad
            JOIN cts.cheque_instruments ci
              ON ci.instrument_id = ad.instrument_id
             AND ci.bank_id = ad.bank_id
            LEFT JOIN cts.branches b
              ON b.bank_id = ad.bank_id
            WHERE ad.bank_id = $1
              AND ad.created_at >= $2::date
              AND ad.created_at < ($2::date + INTERVAL '1 day')
            GROUP BY b.branch_id, b.branch_name
            ORDER BY total DESC
            LIMIT 20
            """,
            bank_id, today,
        )
        reason_rows = await db.fetch(
            """
            SELECT
                COALESCE(decision_reason, 'UNKNOWN') AS reason,
                COUNT(*)                              AS n
            FROM cts.agent_decisions
            WHERE bank_id = $1
              AND decision IN ('STP_RETURN','MANUAL_RETURN','AUTO_RETURN')
              AND created_at >= $2::date
              AND created_at < ($2::date + INTERVAL '1 day')
            GROUP BY decision_reason
            ORDER BY n DESC
            LIMIT 20
            """,
            bank_id, today,
        )
        micr_rows = await db.fetch(
            """
            SELECT
                SUBSTRING(ci.micr_code, 1, 9)         AS presenting_code,
                COUNT(ad.instrument_id)                AS instruments,
                COUNT(ad.instrument_id)
                  FILTER (WHERE ad.decision IN ('STP_RETURN','MANUAL_RETURN','AUTO_RETURN'))
                                                       AS returned
            FROM cts.agent_decisions ad
            JOIN cts.cheque_instruments ci
              ON ci.instrument_id = ad.instrument_id
             AND ci.bank_id = ad.bank_id
            WHERE ad.bank_id = $1
              AND ad.created_at >= $2::date
              AND ad.created_at < ($2::date + INTERVAL '1 day')
              AND ci.micr_code IS NOT NULL
            GROUP BY SUBSTRING(ci.micr_code, 1, 9)
            ORDER BY instruments DESC
            LIMIT 20
            """,
            bank_id, today,
        )
        branches = [
            DraweeBranch(
                id=r["branch_id"] or "—",
                name=r["branch_name"] or "—",
                total=int(r["total"]),
                returned=int(r["returned"]),
                value_cr=0.0,
            )
            for r in branch_rows
        ]
        return_reasons = {r["reason"]: int(r["n"]) for r in reason_rows}
        presenting_banks = [
            {
                "bank": r["presenting_code"],
                "instruments": int(r["instruments"]),
                "returned": int(r["returned"]),
            }
            for r in micr_rows
        ]
        return DraweeStatsResponse(
            branches=branches,
            return_reasons=return_reasons,
            presenting_banks=presenting_banks,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.inward_drawee_stats.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Inward Human Review Queue ────────────────────────────────────────────────

class HumanReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    account_display: str
    decision_reason: str
    queued_at: str


class HumanReviewQueueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[HumanReviewItem]
    total: int
    degraded: bool


@router_v1.get("/inward/human-review-queue", response_model=HumanReviewQueueResponse)
async def inward_human_review_queue(
    request: Request,
    limit: int = Query(default=50, le=100),
    ctx: UserContext = Depends(_ctx),
) -> HumanReviewQueueResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = HumanReviewQueueResponse(items=[], total=0, degraded=True)
    if db is None:
        return empty
    try:
        rows = await db.fetch(
            """
            SELECT
                ad.instrument_id,
                ci.account_last4,
                ad.decision_reason,
                ad.created_at
            FROM cts.agent_decisions ad
            JOIN cts.cheque_instruments ci
              ON ci.instrument_id = ad.instrument_id
             AND ci.bank_id = ad.bank_id
            WHERE ad.bank_id = $1
              AND ad.decision = 'HUMAN_REVIEW'
            ORDER BY ad.created_at ASC
            LIMIT $2
            """,
            bank_id, limit,
        )
        count_row = await db.fetchrow(
            "SELECT COUNT(*) AS n FROM cts.agent_decisions WHERE bank_id = $1 AND decision = 'HUMAN_REVIEW'",
            bank_id,
        )
        items = [
            HumanReviewItem(
                instrument_id=r["instrument_id"],
                account_display=_mask_account(r["account_last4"]),
                decision_reason=r["decision_reason"] or "—",
                queued_at=r["created_at"].isoformat() if r["created_at"] else "",
            )
            for r in rows
        ]
        return HumanReviewQueueResponse(
            items=items,
            total=int(count_row["n"]) if count_row else 0,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.human_review_queue.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── NGCH Status ─────────────────────────────────────────────────────────────

class NGCHStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    last_submission_at: Optional[str]
    last_status: Optional[str]
    pending_count: int
    submitted_today: int
    degraded: bool


@router_v1.get("/admin/ngch-status", response_model=NGCHStatusResponse)
async def ngch_status(
    request: Request,
    ctx: UserContext = Depends(_ctx),
) -> NGCHStatusResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = NGCHStatusResponse(
        last_submission_at=None,
        last_status=None,
        pending_count=0,
        submitted_today=0,
        degraded=True,
    )
    if db is None:
        return empty
    try:
        today = _today_utc()
        last_row = await db.fetchrow(
            """
            SELECT status, submitted_at
            FROM cts.ngch_submissions
            WHERE bank_id = $1
            ORDER BY submitted_at DESC NULLS LAST
            LIMIT 1
            """,
            bank_id,
        )
        today_row = await db.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'PENDING')   AS pending_count,
                COUNT(*) FILTER (WHERE submitted_at::date = $2) AS submitted_today
            FROM cts.ngch_submissions
            WHERE bank_id = $1
            """,
            bank_id, today,
        )
        return NGCHStatusResponse(
            last_submission_at=last_row["submitted_at"].isoformat() if last_row and last_row["submitted_at"] else None,
            last_status=last_row["status"] if last_row else None,
            pending_count=int(today_row["pending_count"]) if today_row else 0,
            submitted_today=int(today_row["submitted_today"]) if today_row else 0,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.ngch_status.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Kafka Stats ──────────────────────────────────────────────────────────────

class KafkaGroupStat(BaseModel):
    model_config = ConfigDict(frozen=True)
    group_id: str
    topic_prefix: str
    total_lag: int


class KafkaStatsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    connected: bool
    groups: list[KafkaGroupStat]
    total_lag: int
    degraded: bool


@router_v1.get("/admin/kafka-stats", response_model=KafkaStatsResponse)
async def kafka_stats(
    request: Request,
    ctx: UserContext = Depends(_ctx),
) -> KafkaStatsResponse:
    bank_id = ctx.bank_id
    kafka_admin: Any = getattr(request.app.state, "kafka_admin", None)
    empty = KafkaStatsResponse(connected=False, groups=[], total_lag=0, degraded=True)
    if kafka_admin is None:
        return empty
    try:
        groups_raw = await kafka_admin.list_consumer_groups()
        result_groups: list[KafkaGroupStat] = []
        total_lag = 0
        for gid, _ in (groups_raw if isinstance(groups_raw, list) else []):
            if not isinstance(gid, str):
                continue
            if not gid.startswith("cg-cts-"):
                continue
            try:
                offsets = await kafka_admin.list_consumer_group_offsets(gid)
                lag = sum(
                    max(0, (v.offset if hasattr(v, "offset") else 0))
                    for v in (offsets.values() if hasattr(offsets, "values") else [])
                )
                prefix = gid.replace(f"-{bank_id}", "").replace("cg-", "")
                result_groups.append(KafkaGroupStat(
                    group_id=gid,
                    topic_prefix=prefix,
                    total_lag=lag,
                ))
                total_lag += lag
            except Exception:
                pass
        return KafkaStatsResponse(
            connected=True,
            groups=result_groups,
            total_lag=total_lag,
            degraded=False,
        )
    except Exception as exc:
        log.warning("cts.kafka_stats.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Cross-Centre Alerts ──────────────────────────────────────────────────────

class CrossCentreAlert(BaseModel):
    model_config = ConfigDict(frozen=True)
    alert_id: str
    rpc_id: str
    description: str
    severity: str
    detected_at: str


class CrossCentreAlertsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[CrossCentreAlert]
    total: int
    degraded: bool


@router_v1.get("/rpc/cross-centre-alerts", response_model=CrossCentreAlertsResponse)
async def cross_centre_alerts(
    request: Request,
    limit: int = Query(default=50, le=100),
    ctx: UserContext = Depends(_ctx),
) -> CrossCentreAlertsResponse:
    # cts.rpc_alerts table not yet created — migration pending with RPC module build.
    # Return degraded until the table and its Temporal writer activity exist.
    return CrossCentreAlertsResponse(items=[], total=0, degraded=True)


# ─── Outward Audit Events ─────────────────────────────────────────────────────
# Reads from cts.outward_scan_events — schema defined by 20260803_add_outward_scan_events.py.
# Columns: event_id (UUID), bank_id, branch_id, session_id, scan_id, instrument_id,
#          micr_suffix, payee_display, amount_range, outcome, lot_id, mismatch_id,
#          mismatch_fields, reject_reason, scanned_at.

class OutwardAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    branch_id: str
    outcome: str
    scan_id: str
    scanned_at: str


class OutwardAuditEventsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[OutwardAuditEvent]
    total: int
    degraded: bool


@router_v1.get("/outward/audit-events", response_model=OutwardAuditEventsResponse)
async def outward_audit_events(
    request: Request,
    limit: int = Query(default=50, le=100),
    ctx: UserContext = Depends(_ctx),
) -> OutwardAuditEventsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = OutwardAuditEventsResponse(items=[], total=0, degraded=True)
    if db is None:
        return empty
    try:
        rows = await db.fetch(
            """
            SELECT
                event_id::text,
                COALESCE(branch_id, '—') AS branch_id,
                outcome,
                scan_id,
                scanned_at
            FROM cts.outward_scan_events
            WHERE bank_id = $1
            ORDER BY scanned_at DESC
            LIMIT $2
            """,
            bank_id, limit,
        )
        count_row = await db.fetchrow(
            "SELECT COUNT(*) AS n FROM cts.outward_scan_events WHERE bank_id = $1",
            bank_id,
        )
        items = [
            OutwardAuditEvent(
                event_id=r["event_id"],
                branch_id=r["branch_id"],
                outcome=r["outcome"],
                scan_id=r["scan_id"],
                scanned_at=r["scanned_at"].isoformat() if r["scanned_at"] else "",
            )
            for r in rows
        ]
        return OutwardAuditEventsResponse(
            items=items,
            total=int(count_row["n"]) if count_row else 0,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.outward_audit_events.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Branch Session (current) ─────────────────────────────────────────────────

class BranchSessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: Optional[str]
    branch_id: Optional[str]
    status: Optional[str]
    hub_type: Optional[str]
    clearing_date: Optional[str]
    opened_at: Optional[str]
    total_uploaded: int
    total_accepted: int
    total_rejected: int
    degraded: bool


@router_v1.get("/branch/session", response_model=BranchSessionResponse)
async def branch_current_session(
    request: Request,
    branch_id: Optional[str] = Query(None),
    ctx: UserContext = Depends(_ctx),
) -> BranchSessionResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = BranchSessionResponse(
        session_id=None, branch_id=None, status=None,
        hub_type=None, clearing_date=None, opened_at=None,
        total_uploaded=0, total_accepted=0, total_rejected=0,
        degraded=True,
    )
    if db is None:
        return empty
    try:
        today = _today_utc()
        if branch_id:
            row = await db.fetchrow(
                """
                SELECT
                    session_id, branch_id, status, hub_type,
                    clearing_date::text AS clearing_date,
                    opened_at,
                    total_uploaded, total_accepted, total_rejected
                FROM cts.eeh_sessions
                WHERE bank_id = $1
                  AND branch_id = $2
                  AND clearing_date = $3
                ORDER BY opened_at DESC
                LIMIT 1
                """,
                bank_id, branch_id, today,
            )
        else:
            row = await db.fetchrow(
                """
                SELECT
                    session_id, branch_id, status, hub_type,
                    clearing_date::text AS clearing_date,
                    opened_at,
                    total_uploaded, total_accepted, total_rejected
                FROM cts.eeh_sessions
                WHERE bank_id = $1
                  AND clearing_date = $2
                ORDER BY opened_at DESC
                LIMIT 1
                """,
                bank_id, today,
            )
        if row is None:
            return BranchSessionResponse(
                session_id=None, branch_id=None, status="NO_SESSION",
                hub_type=None, clearing_date=str(today), opened_at=None,
                total_uploaded=0, total_accepted=0, total_rejected=0,
                degraded=False,
            )
        return BranchSessionResponse(
            session_id=row["session_id"],
            branch_id=row["branch_id"],
            status=row["status"],
            hub_type=row["hub_type"],
            clearing_date=row["clearing_date"],
            opened_at=row["opened_at"].isoformat() if row["opened_at"] else None,
            total_uploaded=int(row["total_uploaded"]),
            total_accepted=int(row["total_accepted"]),
            total_rejected=int(row["total_rejected"]),
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.branch_session.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Branch Session History ───────────────────────────────────────────────────

class BranchSessionItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    branch_id: str
    clearing_date: str
    status: str
    hub_type: str
    total_uploaded: int
    total_accepted: int
    total_rejected: int
    opened_at: str


class BranchSessionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[BranchSessionItem]
    total: int
    degraded: bool


@router_v1.get("/branch/sessions", response_model=BranchSessionsResponse)
async def branch_sessions(
    request: Request,
    limit: int = Query(default=30, le=100),
    branch_id: Optional[str] = Query(None),
    ctx: UserContext = Depends(_ctx),
) -> BranchSessionsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = BranchSessionsResponse(items=[], total=0, degraded=True)
    if db is None:
        return empty
    try:
        if branch_id:
            rows = await db.fetch(
                """
                SELECT
                    session_id, branch_id, clearing_date::text AS clearing_date,
                    status, hub_type,
                    total_uploaded, total_accepted, total_rejected,
                    opened_at
                FROM cts.eeh_sessions
                WHERE bank_id = $1
                  AND branch_id = $2
                ORDER BY opened_at DESC
                LIMIT $3
                """,
                bank_id, branch_id, limit,
            )
            count_row = await db.fetchrow(
                "SELECT COUNT(*) AS n FROM cts.eeh_sessions WHERE bank_id = $1 AND branch_id = $2",
                bank_id, branch_id,
            )
        else:
            rows = await db.fetch(
                """
                SELECT
                    session_id, branch_id, clearing_date::text AS clearing_date,
                    status, hub_type,
                    total_uploaded, total_accepted, total_rejected,
                    opened_at
                FROM cts.eeh_sessions
                WHERE bank_id = $1
                ORDER BY opened_at DESC
                LIMIT $2
                """,
                bank_id, limit,
            )
            count_row = await db.fetchrow(
                "SELECT COUNT(*) AS n FROM cts.eeh_sessions WHERE bank_id = $1",
                bank_id,
            )
        items = [
            BranchSessionItem(
                session_id=r["session_id"],
                branch_id=r["branch_id"],
                clearing_date=r["clearing_date"],
                status=r["status"],
                hub_type=r["hub_type"],
                total_uploaded=int(r["total_uploaded"]),
                total_accepted=int(r["total_accepted"]),
                total_rejected=int(r["total_rejected"]),
                opened_at=r["opened_at"].isoformat() if r["opened_at"] else "",
            )
            for r in rows
        ]
        return BranchSessionsResponse(
            items=items,
            total=int(count_row["n"]) if count_row else 0,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.branch_sessions.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Branch EEH Health ────────────────────────────────────────────────────────
# Reads from cts.scanner_registrations — schema defined by 20260811_scanner_registrations.py.
# Columns: registration_id (PK), bank_id, branch_id, branch_ifsc, scanner_config_id,
#          sdk_version, registration_token_hash, status, last_heartbeat_at,
#          last_scan_submitted_at, heartbeat_interval_seconds, scans_today,
#          errors_today, last_error, registered_at, registered_by, is_active.
# `health` is NOT stored — derived from status + last_heartbeat_at staleness.

def _derive_health(status: str, last_heartbeat_at: Optional[object], interval_s: int) -> str:
    if status == "REVOKED":
        return "REVOKED"
    if status == "PENDING":
        return "PENDING"
    if last_heartbeat_at is None:
        return "UNKNOWN"
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    stale_after = _dt.timedelta(seconds=max(interval_s * 3, 300))
    if hasattr(last_heartbeat_at, "tzinfo") and last_heartbeat_at.tzinfo is None:
        last_heartbeat_at = last_heartbeat_at.replace(tzinfo=_dt.timezone.utc)
    age = now - last_heartbeat_at
    if age > stale_after:
        return "STALE"
    return "OK" if status == "ACTIVE" else status


class EEHHealthScanner(BaseModel):
    model_config = ConfigDict(frozen=True)
    registration_id: str
    branch_id: str
    is_active: bool
    health: str
    status: str
    scans_today: int
    errors_today: int
    last_heartbeat_at: Optional[str]


class EEHHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scanners: list[EEHHealthScanner]
    active_count: int
    total_count: int
    degraded: bool


@router_v1.get("/branch/eeh-health", response_model=EEHHealthResponse)
async def branch_eeh_health(
    request: Request,
    branch_id: Optional[str] = Query(None),
    ctx: UserContext = Depends(_ctx),
) -> EEHHealthResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = EEHHealthResponse(scanners=[], active_count=0, total_count=0, degraded=True)
    if db is None:
        return empty
    try:
        if branch_id:
            rows = await db.fetch(
                """
                SELECT
                    registration_id, branch_id, status, is_active,
                    last_heartbeat_at, heartbeat_interval_seconds,
                    scans_today, errors_today
                FROM cts.scanner_registrations
                WHERE bank_id = $1
                  AND branch_id = $2
                ORDER BY registration_id ASC
                """,
                bank_id, branch_id,
            )
        else:
            rows = await db.fetch(
                """
                SELECT
                    registration_id, branch_id, status, is_active,
                    last_heartbeat_at, heartbeat_interval_seconds,
                    scans_today, errors_today
                FROM cts.scanner_registrations
                WHERE bank_id = $1
                ORDER BY branch_id ASC, registration_id ASC
                """,
                bank_id,
            )
        scanners = [
            EEHHealthScanner(
                registration_id=r["registration_id"],
                branch_id=r["branch_id"],
                is_active=bool(r["is_active"]),
                status=r["status"],
                health=_derive_health(
                    r["status"],
                    r["last_heartbeat_at"],
                    int(r["heartbeat_interval_seconds"]),
                ),
                scans_today=int(r["scans_today"]),
                errors_today=int(r["errors_today"]),
                last_heartbeat_at=r["last_heartbeat_at"].isoformat() if r["last_heartbeat_at"] else None,
            )
            for r in rows
        ]
        return EEHHealthResponse(
            scanners=scanners,
            active_count=sum(1 for s in scanners if s.is_active),
            total_count=len(scanners),
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.eeh_health.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Agency Inward Relay Stats ────────────────────────────────────────────────

class AgencyRelayStatsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    clearing_date: str
    total_instruments: int
    submitted: int
    pending: int
    reconciled: int
    degraded: bool


@router_v1.get("/agency/inward-relay-stats", response_model=AgencyRelayStatsResponse)
async def agency_inward_relay_stats(
    request: Request,
    ctx: UserContext = Depends(_ctx),
) -> AgencyRelayStatsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    today = _today_utc()
    empty = AgencyRelayStatsResponse(
        clearing_date=str(today),
        total_instruments=0, submitted=0, pending=0, reconciled=0,
        degraded=True,
    )
    if db is None:
        return empty
    try:
        row = await db.fetchrow(
            """
            SELECT
                COALESCE(SUM(total_instruments), 0)                              AS total_instruments,
                COALESCE(SUM(total_instruments)
                  FILTER (WHERE status IN ('SUBMITTED','RECONCILED')), 0)         AS submitted,
                COALESCE(SUM(total_instruments)
                  FILTER (WHERE status IN ('OPEN','SEALED')), 0)                  AS pending,
                COALESCE(SUM(total_instruments)
                  FILTER (WHERE status = 'RECONCILED'), 0)                        AS reconciled
            FROM cts.clearing_sessions
            WHERE bank_id = $1
              AND clearing_date = $2
            """,
            bank_id, today,
        )
        return AgencyRelayStatsResponse(
            clearing_date=str(today),
            total_instruments=int(row["total_instruments"]) if row else 0,
            submitted=int(row["submitted"]) if row else 0,
            pending=int(row["pending"]) if row else 0,
            reconciled=int(row["reconciled"]) if row else 0,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.agency_relay_stats.failed", bank_id=bank_id, error=str(exc))
        return empty


# ─── Agency Push Sessions ─────────────────────────────────────────────────────

class AgencyPushSession(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    smb_id: str
    file_type: str
    outcome: str
    records_received: int
    records_processed: int
    received_at: str


class AgencyPushSessionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[AgencyPushSession]
    total: int
    degraded: bool


@router_v1.get("/agency/push-sessions", response_model=AgencyPushSessionsResponse)
async def agency_push_sessions(
    request: Request,
    limit: int = Query(default=50, le=100),
    ctx: UserContext = Depends(_ctx),
) -> AgencyPushSessionsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    empty = AgencyPushSessionsResponse(items=[], total=0, degraded=True)
    if db is None:
        return empty
    try:
        rows = await db.fetch(
            """
            SELECT
                id::text,
                smb_id,
                file_type,
                outcome,
                COALESCE(records_received, 0)  AS records_received,
                COALESCE(records_processed, 0) AS records_processed,
                received_at
            FROM cts.smb_push_sessions
            WHERE agency_id = $1
            ORDER BY received_at DESC
            LIMIT $2
            """,
            bank_id, limit,
        )
        count_row = await db.fetchrow(
            "SELECT COUNT(*) AS n FROM cts.smb_push_sessions WHERE agency_id = $1",
            bank_id,
        )
        items = [
            AgencyPushSession(
                id=r["id"],
                smb_id=r["smb_id"],
                file_type=r["file_type"],
                outcome=r["outcome"],
                records_received=int(r["records_received"]),
                records_processed=int(r["records_processed"]),
                received_at=r["received_at"].isoformat() if r["received_at"] else "",
            )
            for r in rows
        ]
        return AgencyPushSessionsResponse(
            items=items,
            total=int(count_row["n"]) if count_row else 0,
            degraded=False,
        )
    except Exception as exc:
        log.error("cts.agency_push_sessions.failed", bank_id=bank_id, error=str(exc))
        return empty
