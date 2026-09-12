"""
CTS SMB router — Sub-Member Bank management and reporting.

Routes:
  GET  /v1/cts/smb                          — list sub-members (SB only)
  POST /v1/cts/smb                          — register sub-member (SB only)
  GET  /v1/cts/smb/{id}/ledger             — session ledger for one SMB
  GET  /v1/cts/smb/{id}/forwarding-log     — forwarding log for one SMB
  POST /v1/cts/smb/{id}/vault-sync         — trigger vault sync for one SMB (SB only)
  GET  /v1/cts/smb/ledgers                 — all-SMB ledger roll-up (SB only)
  GET  /v1/cts/smb/forwarding-log          — SB consolidated forwarding log (SB only)
  GET  /v1/cts/smb/reports                 — per-SMB performance aggregates (SB only)
"""
import time as _time
from datetime import date, datetime, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.routers.cts_deps import (
    get_current_user_context,
    _SMB_REPORTS_MAX_ROWS,
)
from shared.auth.rbac import BankType, UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

# Roles permitted to call GET /smb/ledgers
_SMB_LEDGERS_ROLES = {"ops_manager", "bank_it_admin", "compliance_officer"}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SMBRegistration(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    bank_name: str
    sponsor_bank_id: str
    micr_prefix: str
    ifsc_prefix: str
    return_rate_threshold: float = 0.15
    soft_hold_threshold: float = 0.25


class SMBRegistrationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    status: Literal["REGISTERED"]
    message: str


class SMBListItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    bank_name: str
    micr_prefix: str
    ifsc_prefix: str
    is_active: bool
    return_rate_threshold: float
    soft_hold_threshold: float
    vault_sync_status: str
    last_vault_sync_at: Optional[float] = None
    signature_count: int = 0
    pps_entry_count: int = 0


class SMBListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_members: list[SMBListItem]
    total: int
    sponsor_bank_id: str


class SMBSessionLedger(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    bank_name: str
    session_date: str
    clearing_session: str
    total_received: int
    stp_pass: int
    stp_return: int
    eyeball: int
    fraud_hold: int
    iet_emergency: int
    return_rate_pct: float
    stp_rate_pct: float
    soft_hold_active: bool
    risk_event_emitted: bool


class SMBLedgerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    ledgers: list[SMBSessionLedger]
    session_date: str
    bank_id: str


class SMBForwardingLogItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    forwarding_id: str
    instrument_id: str
    sub_member_id: str
    micr_prefix_matched: str
    forwarding_status: str
    iet_deadline_utc: str
    received_at: str
    forwarded_at: Optional[str] = None
    completed_at: Optional[str] = None
    terminal_decision: Optional[str] = None


class SMBForwardingLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[SMBForwardingLogItem]
    total: int
    sub_member_id: str


class SMBVaultSyncTriggerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    workflow_id: str
    status: Literal["TRIGGERED"]
    message: str


class SMBLedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    bank_name: str
    total_received: int
    stp_pass: int
    stp_return: int
    eyeball: int
    fraud_hold: int
    iet_emergency: int
    soft_hold_active: bool
    tier2_notification_sent: bool
    return_rate_pct: float
    shield_status: str


class SMBAllLedgersResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    session_date: str
    ledgers: list[SMBLedgerEntry]


class SBForwardingLogItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    forwarding_id: str
    instrument_id: str
    sub_member_id: str
    bank_name: str
    micr_prefix_matched: str
    forwarding_status: str
    terminal_decision: Optional[str] = None
    iet_deadline_utc: str
    received_at: str
    forwarded_at: Optional[str] = None
    completed_at: Optional[str] = None
    iet_seconds_remaining: Optional[int] = None
    failure_reason: Optional[str] = None


class SBForwardingLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[SBForwardingLogItem]
    total: int


class SMBReportRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    sub_member_id: str
    bank_name: str
    bank_ifsc: str
    date: str
    total_presented: int
    stp_confirmed: int
    stp_returned: int
    human_review: int
    return_rate_pct: float
    avg_decision_ms: Optional[int] = None
    iet_breach_count: int


class SMBReportsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    period_start: str
    period_end: str
    rows: list[SMBReportRow]
    total: int


# ---------------------------------------------------------------------------
# Internal helpers (shared by single-SMB and all-SMB endpoints)
# ---------------------------------------------------------------------------

async def _smb_list(bank_id: str, active_only: bool, db) -> SMBListResponse:
    rows = await db.fetch(
        """
        SELECT s.sub_member_id, s.bank_name, s.micr_prefix, s.ifsc_prefix,
               s.is_active, s.return_rate_threshold, s.soft_hold_threshold,
               COALESCE(v.last_sync_status, 'NEVER_SYNCED') AS vault_sync_status,
               EXTRACT(EPOCH FROM v.last_vault_sync_at)::float AS last_vault_sync_at,
               COALESCE(v.signature_count, 0) AS signature_count,
               COALESCE(v.pps_entry_count, 0) AS pps_entry_count
        FROM cts.sub_member_banks s
        LEFT JOIN cts.smb_vault_config v USING (bank_id, sub_member_id)
        WHERE s.bank_id = $1
          AND ($2 = FALSE OR s.is_active = TRUE)
        ORDER BY s.bank_name
        """,
        bank_id, active_only,
    )
    items = [
        SMBListItem(
            sub_member_id=r["sub_member_id"],
            bank_name=r["bank_name"],
            micr_prefix=r["micr_prefix"],
            ifsc_prefix=r["ifsc_prefix"],
            is_active=r["is_active"],
            return_rate_threshold=float(r["return_rate_threshold"]),
            soft_hold_threshold=float(r["soft_hold_threshold"]),
            vault_sync_status=r["vault_sync_status"],
            last_vault_sync_at=r["last_vault_sync_at"],
            signature_count=r["signature_count"],
            pps_entry_count=r["pps_entry_count"],
        )
        for r in rows
    ]
    return SMBListResponse(sub_members=items, total=len(items), sponsor_bank_id=bank_id)


async def _smb_ledger(bank_id: str, sub_member_id: str, date_str: str, db) -> SMBLedgerResponse:
    rows = await db.fetch(
        """
        SELECT l.sub_member_id, s.bank_name,
               l.session_date::text, l.clearing_session,
               l.total_received, l.stp_pass, l.stp_return, l.eyeball,
               l.fraud_hold, l.iet_emergency,
               l.soft_hold_active, l.risk_event_emitted
        FROM cts.sub_member_batch_ledgers l
        JOIN cts.sub_member_banks s USING (bank_id, sub_member_id)
        WHERE l.bank_id = $1 AND l.sub_member_id = $2 AND l.session_date = $3::date
        ORDER BY l.clearing_session
        """,
        bank_id, sub_member_id, date_str,
    )
    ledgers = []
    for r in rows:
        total = r["total_received"] or 1
        return_rate = round((r["stp_return"] / total) * 100, 2)
        stp_rate    = round((r["stp_pass"]   / total) * 100, 2)
        ledgers.append(SMBSessionLedger(
            sub_member_id=r["sub_member_id"],
            bank_name=r["bank_name"],
            session_date=r["session_date"],
            clearing_session=r["clearing_session"],
            total_received=r["total_received"],
            stp_pass=r["stp_pass"],
            stp_return=r["stp_return"],
            eyeball=r["eyeball"],
            fraud_hold=r["fraud_hold"],
            iet_emergency=r["iet_emergency"],
            return_rate_pct=return_rate,
            stp_rate_pct=stp_rate,
            soft_hold_active=r["soft_hold_active"],
            risk_event_emitted=r["risk_event_emitted"],
        ))
    return SMBLedgerResponse(ledgers=ledgers, session_date=date_str, bank_id=bank_id)


async def _smb_forwarding_log(bank_id: str, sub_member_id: str, limit: int, db) -> SMBForwardingLogResponse:
    rows = await db.fetch(
        """
        SELECT forwarding_id::text, instrument_id, sub_member_id,
               micr_prefix_matched, forwarding_status,
               iet_deadline_utc::text, received_at::text,
               forwarded_at::text, completed_at::text, terminal_decision
        FROM cts.smb_forwarding_log
        WHERE bank_id = $1 AND sub_member_id = $2
        ORDER BY received_at DESC
        LIMIT $3
        """,
        bank_id, sub_member_id, limit,
    )
    items = [
        SMBForwardingLogItem(
            forwarding_id=r["forwarding_id"],
            instrument_id=r["instrument_id"],
            sub_member_id=r["sub_member_id"],
            micr_prefix_matched=r["micr_prefix_matched"],
            forwarding_status=r["forwarding_status"],
            iet_deadline_utc=r["iet_deadline_utc"],
            received_at=r["received_at"],
            forwarded_at=r["forwarded_at"],
            completed_at=r["completed_at"],
            terminal_decision=r["terminal_decision"],
        )
        for r in rows
    ]
    return SMBForwardingLogResponse(items=items, total=len(items), sub_member_id=sub_member_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.get("/smb", response_model=SMBListResponse)
async def list_sub_members(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    active_only: bool = True,
) -> SMBListResponse:
    """List all Sub-Member Banks registered under this Sponsor Bank. SB-only."""
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB management is an SB-only operation")
    bank_id = ctx.bank_id
    log.info("smb.list", bank_id=bank_id, active_only=active_only)
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return SMBListResponse(sub_members=[], total=0, sponsor_bank_id=bank_id)
    try:
        return await _smb_list(bank_id, active_only, db)
    except Exception as exc:
        log.error("smb.list.query_failed", bank_id=bank_id, error=str(exc))
        return SMBListResponse(sub_members=[], total=0, sponsor_bank_id=bank_id)


@router_v1.post("/smb", response_model=SMBRegistrationResponse, status_code=status.HTTP_201_CREATED)
async def register_sub_member(
    request: Request,
    body: SMBRegistration,
    ctx: UserContext = Depends(get_current_user_context),
) -> SMBRegistrationResponse:
    """Register a new Sub-Member Bank. SB-only."""
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB registration is an SB-only operation")
    bank_id = ctx.bank_id
    if body.return_rate_threshold >= body.soft_hold_threshold:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="soft_hold_threshold must be greater than return_rate_threshold",
        )
    log.info("smb.register", bank_id=bank_id, sub_member_id=body.sub_member_id, micr_prefix=body.micr_prefix)
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is not None:
        try:
            async with db.acquire() as conn:
                _empty_enc = b""
                await conn.execute(
                    """
                    INSERT INTO cts.sub_member_banks
                        (sub_member_id, bank_id, bank_name, sponsor_bank_id, micr_prefix,
                         ifsc_prefix, branch_manager_email_enc, ops_head_email_enc,
                         gm_email_enc, return_rate_threshold, soft_hold_threshold)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (sub_member_id) DO NOTHING
                    """,
                    body.sub_member_id, bank_id, body.bank_name, body.sponsor_bank_id,
                    body.micr_prefix, body.ifsc_prefix,
                    _empty_enc, _empty_enc, _empty_enc,
                    body.return_rate_threshold, body.soft_hold_threshold,
                )
                await conn.execute(
                    """
                    INSERT INTO cts.micr_prefix_routing
                        (bank_id, micr_prefix, sub_member_id, effective_from, created_by)
                    VALUES ($1,$2,$3,$4,$5)
                    ON CONFLICT DO NOTHING
                    """,
                    bank_id, body.micr_prefix, body.sub_member_id,
                    date.today(), ctx.user_id,
                )
        except Exception as exc:
            log.error("smb.register.db_failed", bank_id=bank_id, error=str(exc))
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable") from exc
    return SMBRegistrationResponse(
        sub_member_id=body.sub_member_id,
        status="REGISTERED",
        message=(
            f"Sub-Member Bank '{body.sub_member_id}' registered under sponsor '{bank_id}'. "
            f"MICR prefix '{body.micr_prefix}' active from today. "
            f"Vault sync required before first clearing session."
        ),
    )


@router_v1.get("/smb/{sub_member_id}/ledger", response_model=SMBLedgerResponse)
async def get_smb_session_ledger(
    sub_member_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    session_date: Optional[str] = None,
) -> SMBLedgerResponse:
    """Return batch ledger for a Sub-Member Bank."""
    if ctx.bank_type == BankType.SMB and ctx.bank_id != sub_member_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB users can only view their own ledger")
    bank_id = ctx.bank_id
    import datetime as _dt
    date_str = session_date or _dt.date.today().isoformat()
    log.info("smb.ledger", bank_id=bank_id, sub_member_id=sub_member_id, date=date_str)
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return SMBLedgerResponse(ledgers=[], session_date=date_str, bank_id=bank_id)
    try:
        return await _smb_ledger(bank_id, sub_member_id, date_str, db)
    except Exception as exc:
        log.error("smb.ledger.query_failed", bank_id=bank_id, error=str(exc))
        return SMBLedgerResponse(ledgers=[], session_date=date_str, bank_id=bank_id)


@router_v1.get("/smb/{sub_member_id}/forwarding-log", response_model=SMBForwardingLogResponse)
async def get_smb_forwarding_log(
    sub_member_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = 50,
) -> SMBForwardingLogResponse:
    """Return recent forwarding log entries for a Sub-Member Bank."""
    if ctx.bank_type == BankType.SMB and ctx.bank_id != sub_member_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB users can only view their own forwarding log")
    if limit > 100:
        limit = 100
    bank_id = ctx.bank_id
    log.info("smb.forwarding_log", bank_id=bank_id, sub_member_id=sub_member_id, limit=limit)
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return SMBForwardingLogResponse(items=[], total=0, sub_member_id=sub_member_id)
    try:
        return await _smb_forwarding_log(bank_id, sub_member_id, limit, db)
    except Exception as exc:
        log.error("smb.forwarding_log.query_failed", bank_id=bank_id, error=str(exc))
        return SMBForwardingLogResponse(items=[], total=0, sub_member_id=sub_member_id)


@router_v1.post(
    "/smb/{sub_member_id}/vault-sync",
    response_model=SMBVaultSyncTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_smb_vault_sync(
    sub_member_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> SMBVaultSyncTriggerResponse:
    """Trigger VaultSyncWorkflow scoped to a specific Sub-Member Bank. SB-only."""
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vault sync trigger is an SB-only operation")
    bank_id = ctx.bank_id
    ts = int(_time.time())
    workflow_id = f"cts-smb-vaultsync-{bank_id}-{sub_member_id}-{ts}"

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from modules.cts.workflows.vault_sync_workflow import VaultSyncWorkflow, VaultSyncInput
            from shared.config.config_service import config_service
            pepper = await config_service.get_secret("pii_hash_pepper")
            await temporal_client.start_workflow(
                VaultSyncWorkflow.run,
                VaultSyncInput(
                    bank_id=bank_id,
                    pepper=pepper,
                    triggered_by="MANUAL_SMB",
                    sub_member_id=sub_member_id,
                ),
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
            )
        except Exception as exc:
            log.error(
                "smb.vault_sync_trigger_error",
                bank_id=bank_id,
                sub_member_id=sub_member_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to trigger SMB vault sync workflow",
            ) from exc

    log.info("smb.vault_sync_triggered", bank_id=bank_id, sub_member_id=sub_member_id, workflow_id=workflow_id)
    return SMBVaultSyncTriggerResponse(
        sub_member_id=sub_member_id,
        workflow_id=workflow_id,
        status="TRIGGERED",
        message=(
            f"Vault sync started for Sub-Member '{sub_member_id}'. "
            f"Signature specimens and PPS entries will be loaded into vault namespace "
            f"sig:{sub_member_id}:* within ~60 seconds."
        ),
    )


@router_v1.get("/smb/ledgers", response_model=SMBAllLedgersResponse)
async def get_all_smb_ledgers(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    session_date: Optional[str] = None,
) -> SMBAllLedgersResponse:
    """Returns batch ledger for ALL sub-members under this SB bank. SB-only, restricted roles."""
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SB-only endpoint")
    if ctx.role.value not in _SMB_LEDGERS_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    bank_id = ctx.bank_id
    date_str = session_date or date.today().isoformat()

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return SMBAllLedgersResponse(bank_id=bank_id, session_date=date_str, ledgers=[])

    try:
        rows = await db.fetch(
            """
            SELECT l.sub_member_id, b.bank_name,
                   l.total_received, l.stp_pass, l.stp_return,
                   l.eyeball, l.fraud_hold, l.iet_emergency,
                   l.soft_hold_active, l.tier2_notification_sent
            FROM cts.sub_member_batch_ledgers l
            JOIN cts.sub_member_banks b
              ON b.sub_member_id = l.sub_member_id AND b.bank_id = l.bank_id
            WHERE l.bank_id = $1 AND l.session_date = $2::date
            ORDER BY l.total_received DESC
            """,
            bank_id, date_str,
        )
    except Exception as exc:
        log.error("cts.smb_ledgers.query_failed", bank_id=bank_id, error=str(exc))
        return SMBAllLedgersResponse(bank_id=bank_id, session_date=date_str, ledgers=[])

    def _shield(r) -> str:
        total = r["total_received"] or 1
        rate = (r["stp_return"] / total) * 100
        if r["soft_hold_active"]:
            return "SOFT_HOLD"
        if rate > 30:
            return "HIGH_RETURN"
        return "SAFE"

    ledgers = [
        SMBLedgerEntry(
            sub_member_id=r["sub_member_id"],
            bank_name=r["bank_name"],
            total_received=r["total_received"],
            stp_pass=r["stp_pass"],
            stp_return=r["stp_return"],
            eyeball=r["eyeball"],
            fraud_hold=r["fraud_hold"],
            iet_emergency=r["iet_emergency"],
            soft_hold_active=r["soft_hold_active"],
            tier2_notification_sent=r["tier2_notification_sent"],
            return_rate_pct=round((r["stp_return"] / max(r["total_received"], 1)) * 100, 2),
            shield_status=_shield(r),
        )
        for r in rows
    ]
    return SMBAllLedgersResponse(bank_id=bank_id, session_date=date_str, ledgers=ledgers)


@router_v1.get("/smb/forwarding-log", response_model=SBForwardingLogResponse)
async def get_smb_forwarding_log_all(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    status_filter: Optional[str] = Query(None, alias="status_filter"),
    limit: int = Query(200, ge=1, le=500),
) -> SBForwardingLogResponse:
    """Returns forwarding log entries for ALL sub-members under this SB for today. SB-only."""
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SB-only endpoint")

    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return SBForwardingLogResponse(bank_id=bank_id, items=[], total=0)

    try:
        status_clause = "AND f.forwarding_status = $3" if status_filter else ""
        params = [bank_id, limit]
        if status_filter:
            params.append(status_filter)
        rows = await db.fetch(
            f"""
            SELECT f.forwarding_id, f.instrument_id, f.sub_member_id,
                   b.bank_name, f.micr_prefix_matched,
                   f.forwarding_status, f.terminal_decision,
                   f.iet_deadline_utc::text AS iet_deadline_utc,
                   f.received_at::text AS received_at,
                   f.forwarded_at::text AS forwarded_at,
                   f.completed_at::text AS completed_at,
                   EXTRACT(EPOCH FROM (f.iet_deadline_utc - NOW()))::int AS iet_seconds_remaining,
                   f.failure_reason
            FROM cts.smb_forwarding_log f
            JOIN cts.sub_member_banks b USING (bank_id, sub_member_id)
            WHERE f.bank_id = $1
              AND f.received_at >= NOW() - INTERVAL '24 hours'
              {status_clause}
            ORDER BY f.received_at DESC
            LIMIT $2
            """,
            *params,
        )
    except Exception as exc:
        log.error("cts.smb_forwarding_log_all.query_failed", bank_id=bank_id, error=str(exc))
        return SBForwardingLogResponse(bank_id=bank_id, items=[], total=0)

    items = [
        SBForwardingLogItem(
            forwarding_id=r["forwarding_id"],
            instrument_id=r["instrument_id"],
            sub_member_id=r["sub_member_id"],
            bank_name=r["bank_name"],
            micr_prefix_matched=r["micr_prefix_matched"] or "",
            forwarding_status=r["forwarding_status"],
            terminal_decision=r["terminal_decision"],
            iet_deadline_utc=r["iet_deadline_utc"] or "",
            received_at=r["received_at"] or "",
            forwarded_at=r["forwarded_at"],
            completed_at=r["completed_at"],
            iet_seconds_remaining=r["iet_seconds_remaining"],
            failure_reason=r["failure_reason"],
        )
        for r in rows
    ]
    return SBForwardingLogResponse(bank_id=bank_id, items=items, total=len(items))


@router_v1.get("/smb/reports", response_model=SMBReportsResponse)
async def get_smb_reports(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    days: int = Query(7, ge=1, le=30),
) -> SMBReportsResponse:
    """Returns per-SMB performance aggregates for the past N days. SB-only."""
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SB-only endpoint")

    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    today_str = date.today().isoformat()
    if db is None:
        return SMBReportsResponse(bank_id=bank_id, period_start=today_str, period_end=today_str, rows=[], total=0)

    try:
        rows = await db.fetch(
            f"""
            SELECT
                ad.sub_member_id,
                b.bank_name,
                b.bank_ifsc,
                ad.decided_at::date::text                                        AS date,
                COUNT(*)::int                                                    AS total_presented,
                COUNT(*) FILTER (WHERE ad.decision_outcome IN ('STP_CONFIRM','CONFIRMED'))::int AS stp_confirmed,
                COUNT(*) FILTER (WHERE ad.decision_outcome IN ('STP_RETURN','RETURNED'))::int  AS stp_returned,
                COUNT(*) FILTER (WHERE ad.decision_outcome = 'HUMAN_REVIEW')::int             AS human_review,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE ad.decision_outcome IN ('STP_RETURN','RETURNED'))
                    / NULLIF(COUNT(*), 0), 2
                )::float                                                         AS return_rate_pct,
                AVG(ad.decision_latency_ms)::int                                 AS avg_decision_ms,
                0::int                                                           AS iet_breach_count
            FROM cts.agent_decisions ad
            JOIN cts.sub_member_banks b
                 ON b.bank_id = ad.bank_id AND b.sub_member_id = ad.sub_member_id
            WHERE ad.bank_id = $1
              AND ad.decided_at >= NOW() - ($2 || ' days')::interval
              AND ad.sub_member_id IS NOT NULL
            GROUP BY ad.sub_member_id, b.bank_name, b.bank_ifsc, ad.decided_at::date
            ORDER BY ad.decided_at::date DESC, b.bank_name
            LIMIT {_SMB_REPORTS_MAX_ROWS}
            """,
            bank_id,
            str(days),
        )
    except Exception as exc:
        log.warning("cts.smb_reports.query_failed", bank_id=bank_id, error=str(exc))
        return SMBReportsResponse(bank_id=bank_id, period_start=today_str, period_end=today_str, rows=[], total=0)

    period_start = rows[-1]["date"] if rows else today_str
    report_rows = [
        SMBReportRow(
            sub_member_id=r["sub_member_id"],
            bank_name=r["bank_name"],
            bank_ifsc=r["bank_ifsc"] or "",
            date=r["date"],
            total_presented=r["total_presented"],
            stp_confirmed=r["stp_confirmed"],
            stp_returned=r["stp_returned"],
            human_review=r["human_review"],
            return_rate_pct=float(r["return_rate_pct"] or 0),
            avg_decision_ms=r["avg_decision_ms"],
            iet_breach_count=r["iet_breach_count"],
        )
        for r in rows
    ]
    return SMBReportsResponse(
        bank_id=bank_id,
        period_start=period_start,
        period_end=today_str,
        rows=report_rows,
        total=len(report_rows),
    )
