"""
CTS Scanner routes — registration, session events, scan monitor.

Routes:
  GET  /v1/cts/scan-monitor/recent
  POST /v1/cts/outward/scan/event
  GET  /v1/cts/outward/session/{session_id}/scan-log
  GET  /v1/cts/outward/scan-events
  POST /v1/cts/admin/scanner/registration-code
  POST /v1/cts/admin/scanner/register
"""
from __future__ import annotations

from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.routers.cts_deps import (
    _SCAN_LOG_MAX_ROWS,
    get_bank_id_scanner_or_user,
    get_current_bank_id,
    get_current_user_context,
)
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

# ── Models ────────────────────────────────────────────────────────────────────

class ScanEventItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    micr_suffix: Optional[str]
    payee_display: Optional[str]
    amount_range: Optional[str]
    outcome: str
    lot_id: Optional[str]
    mismatch_id: Optional[str]
    mismatch_fields: Optional[list]
    reject_reason: Optional[str]
    scanned_at: str


class ScanMonitorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    events: list[ScanEventItem]
    total: int


class OutwardScanEventRequest(BaseModel):
    """Received from the edge scanner agent for non-submit scan outcomes."""
    model_config = ConfigDict(frozen=True)
    bank_id:          str
    branch_id:        Optional[str] = None
    session_id:       str
    scan_id:          str
    event_type:       Literal["DOUBLE_FEED_DETECTED", "IMPRINTER_FAULT", "UPLOAD_FAILED"]
    position_in_batch: Optional[int] = None
    micr_suffix:      Optional[str] = None


class OutwardScanEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    status:   Literal["RECORDED"]


class ScanSessionItem(BaseModel):
    """One instrument row in the Branch Scan Dashboard session log."""
    model_config = ConfigDict(frozen=True)
    event_id:          str
    scan_id:           str
    instrument_id:     Optional[str] = None
    workflow_id:       Optional[str] = None
    event_type:        str
    position_in_batch: Optional[int] = None
    micr_suffix:       Optional[str] = None
    imprinter_stamped: bool = False
    micr_source:       Optional[str] = None
    branch_id:         Optional[str] = None
    created_at:        float


class ScanSessionLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id:    str
    bank_id:       str
    branch_id:     Optional[str] = None
    total:         int
    double_feeds:  int
    items:         list[ScanSessionItem]


class BranchScanEventRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id:           str
    event_type:        str
    micr_suffix:       Optional[str] = None
    micr_source:       Optional[str] = None
    branch_id:         Optional[str] = None
    session_id:        str
    position_in_batch: Optional[int] = None
    created_at:        str


class BranchScanEventsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id:  str
    total:    int
    events:   list[BranchScanEventRow]


class ScannerRegCodeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id: str


class ScannerRegCodeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    code:        str
    branch_id:   str
    branch_name: str
    bank_id:     str
    expires_at:  str


class ScannerRegisterRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    registration_code: str
    machine_id:        str


class ScannerRegisterResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    api_url:          str
    bank_id:          str
    bank_ifsc:        str
    branch_id:        str
    branch_name:      str
    api_token:        str
    endorsement_text: str
    enable_imprinter: bool
    enable_uv_scan:   bool
    mocr_weight:      int


# ── Routes ────────────────────────────────────────────────────────────────────

@router_v1.get("/scan-monitor/recent", response_model=ScanMonitorResponse)
async def get_recent_scan_events(
    request: Request,
    limit: int = 50,
    ctx: UserContext = Depends(get_current_user_context),
) -> ScanMonitorResponse:
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    if limit > 100:
        limit = 100

    db = getattr(request.app.state, "db", None)
    if db is None:
        return ScanMonitorResponse(bank_id=bank_id, events=[], total=0)

    try:
        rows = await db.fetch(
            """
            SELECT scan_id, micr_suffix, payee_display, amount_range, outcome,
                   lot_id, mismatch_id, mismatch_fields, reject_reason,
                   scanned_at::text
            FROM cts.outward_scan_events
            WHERE bank_id = $1
              AND scanned_at > NOW() - INTERVAL '8 hours'
            ORDER BY scanned_at DESC
            LIMIT $2
            """,
            bank_id, limit,
        )
    except Exception as exc:
        log.error("cts.scan_monitor.query_failed", bank_id=bank_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable") from exc

    events = [
        ScanEventItem(
            scan_id=r["scan_id"],
            micr_suffix=r["micr_suffix"],
            payee_display=r["payee_display"],
            amount_range=r["amount_range"],
            outcome=r["outcome"],
            lot_id=r["lot_id"],
            mismatch_id=r["mismatch_id"],
            mismatch_fields=r["mismatch_fields"],
            reject_reason=r["reject_reason"],
            scanned_at=r["scanned_at"],
        )
        for r in rows
    ]
    return ScanMonitorResponse(bank_id=bank_id, events=events, total=len(events))


@router_v1.post(
    "/outward/scan/event",
    response_model=OutwardScanEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def report_outward_scan_event(
    body: OutwardScanEventRequest,
    request: Request,
    bank_id: str = Depends(get_bank_id_scanner_or_user),
) -> OutwardScanEventResponse:
    """
    Called by the edge scanner agent for non-submit scan outcomes:
    DOUBLE_FEED_DETECTED, IMPRINTER_FAULT, UPLOAD_FAILED.
    Non-fatal DB write — agent gets 202 regardless so the scan session is not blocked.
    """
    import uuid as _uuid

    if body.bank_id != bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="bank_id in request body must match authenticated bank",
        )

    event_id = str(_uuid.uuid4())
    db_pool = getattr(request.app.state, "db_pool_cts", None)

    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO cts.outward_scan_session_events
                        (event_id, bank_id, branch_id, session_id, scan_id,
                         event_type, position_in_batch, micr_suffix, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
                    """,
                    event_id, bank_id, body.branch_id, body.session_id, body.scan_id,
                    body.event_type, body.position_in_batch, body.micr_suffix,
                )
        except Exception as exc:
            log.warning(
                "cts.outward_scan_event_write_failed",
                bank_id=bank_id, scan_id=body.scan_id, event_type=body.event_type,
                error=str(exc),
            )

    log.info(
        "cts.outward_scan_event",
        bank_id=bank_id,
        branch_id=body.branch_id,
        session_id=body.session_id,
        scan_id=body.scan_id,
        event_type=body.event_type,
        position=body.position_in_batch,
    )
    return OutwardScanEventResponse(event_id=event_id, status="RECORDED")


@router_v1.get(
    "/outward/session/{session_id}/scan-log",
    response_model=ScanSessionLogResponse,
)
async def get_scan_session_log(
    session_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    branch_id: Optional[str] = None,
) -> ScanSessionLogResponse:
    """
    Branch Scan Dashboard data source — returns all instruments from a scanning session.
    Items with event_type = DOUBLE_FEED_DETECTED are flagged for re-scan.
    """
    db_pool = getattr(request.app.state, "db_pool_cts", None)
    items: list[ScanSessionItem] = []

    if db_pool is not None:
        _SQL = f"""
            SELECT
                event_id, scan_id, instrument_id, workflow_id, event_type,
                position_in_batch, micr_suffix, imprinter_stamped, micr_source,
                branch_id,
                EXTRACT(EPOCH FROM created_at) AS created_at_epoch
            FROM cts.outward_scan_session_events
            WHERE bank_id = $1
              AND session_id = $2
              AND ($3::text IS NULL OR branch_id = $3)
            ORDER BY COALESCE(position_in_batch, 999999), created_at ASC
            LIMIT {_SCAN_LOG_MAX_ROWS}
        """.strip()
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(_SQL, bank_id, session_id, branch_id)
            for row in rows:
                items.append(ScanSessionItem(
                    event_id=row["event_id"],
                    scan_id=row["scan_id"],
                    instrument_id=row["instrument_id"],
                    workflow_id=row["workflow_id"],
                    event_type=row["event_type"],
                    position_in_batch=row["position_in_batch"],
                    micr_suffix=row["micr_suffix"],
                    imprinter_stamped=bool(row["imprinter_stamped"]),
                    micr_source=row["micr_source"],
                    branch_id=row["branch_id"],
                    created_at=float(row["created_at_epoch"] or 0.0),
                ))
        except Exception as exc:
            log.warning("cts.scan_session_log_error", bank_id=bank_id,
                        session_id=session_id, error=str(exc))

    double_feeds = sum(1 for i in items if i.event_type == "DOUBLE_FEED_DETECTED")

    log.info("cts.scan_session_log", bank_id=bank_id, session_id=session_id,
             total=len(items), double_feeds=double_feeds)
    return ScanSessionLogResponse(
        session_id=session_id,
        bank_id=bank_id,
        branch_id=branch_id,
        total=len(items),
        double_feeds=double_feeds,
        items=items,
    )


@router_v1.get(
    "/outward/scan-events",
    response_model=BranchScanEventsResponse,
)
async def list_outward_scan_events(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    branch_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> BranchScanEventsResponse:
    """
    Branch Scan Monitor — scan-event feed filtered by branch (not session).
    Called by BranchScanMonitor.jsx to surface double-feed and imprinter-fault events.
    """
    if limit > 100:
        limit = 100

    events: list[BranchScanEventRow] = []
    db_pool = getattr(request.app.state, "db_pool_cts", None)

    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT scan_id, event_type, micr_suffix, micr_source,
                           branch_id, session_id, position_in_batch,
                           to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
                    FROM cts.outward_scan_session_events
                    WHERE bank_id = $1
                      AND ($2::text IS NULL OR branch_id = $2)
                      AND ($3::text IS NULL OR event_type = $3)
                      AND event_type != 'SUBMITTED'
                      AND created_at > NOW() - INTERVAL '12 hours'
                    ORDER BY created_at DESC
                    LIMIT $4
                    """,
                    bank_id, branch_id, event_type, limit,
                )
                for row in rows:
                    events.append(BranchScanEventRow(
                        scan_id=row["scan_id"],
                        event_type=row["event_type"],
                        micr_suffix=row["micr_suffix"],
                        micr_source=row["micr_source"],
                        branch_id=row["branch_id"],
                        session_id=row["session_id"],
                        position_in_batch=row["position_in_batch"],
                        created_at=row["created_at"],
                    ))
        except Exception as exc:
            log.warning("cts.branch_scan_events_error", bank_id=bank_id,
                        branch_id=branch_id, error=str(exc))

    log.info("cts.branch_scan_events", bank_id=bank_id, branch_id=branch_id,
             event_type=event_type, total=len(events))
    return BranchScanEventsResponse(bank_id=bank_id, total=len(events), events=events)


@router_v1.post(
    "/admin/scanner/registration-code",
    response_model=ScannerRegCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_scanner_registration_code(
    body: ScannerRegCodeRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScannerRegCodeResponse:
    """
    Generate a one-time 8-char registration code for a branch scanner.
    Code stored in Redis with 24h TTL, single-use.
    Subsequent call from installer exchanges code for machine-bound API token.
    """
    import secrets as _secrets
    import json as _json
    from datetime import datetime, timedelta, timezone

    branch_id = body.branch_id
    if not branch_id or len(branch_id) > 128:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error_code": "INVALID_BRANCH_ID", "message": "branch_id is required."})

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    redis   = getattr(request.app.state, "redis_client", None)

    branch_name = branch_id
    bank_ifsc   = ""
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT branch_name, bank_ifsc, scanner_input_mode FROM cts.branches "
                    "WHERE bank_id = $1 AND branch_id = $2 AND is_active = true",
                    bank_id, branch_id,
                )
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"error_code": "BRANCH_NOT_FOUND",
                                "message": f"Branch {branch_id} not found or not active for bank {bank_id}."},
                    )
                branch_name = row["branch_name"]
                bank_ifsc   = row["bank_ifsc"]
                if row["scanner_input_mode"] != "SDK_PUSH":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error_code": "BRANCH_NOT_SDK",
                                "message": f"Branch {branch_id} is not configured for SDK_PUSH mode."},
                    )
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("scanner_reg_code.db_error", bank_id=bank_id, branch_id=branch_id, error=str(exc))
            branch_name = branch_id
            bank_ifsc   = ""

    bank_prefix = bank_id[:4].upper().replace("-", "")[:4].ljust(4, "X")
    random_part = _secrets.token_hex(2).upper()
    code = f"{bank_prefix}{random_part}"

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    payload = _json.dumps({
        "bank_id":          bank_id,
        "branch_id":        branch_id,
        "branch_name":      branch_name,
        "bank_ifsc":        bank_ifsc,
        "endorsement_text": f"PRESENTED BY {bank_id.upper().replace('-', ' ')}",
        "enable_imprinter": True,
        "enable_uv_scan":   False,
        "mocr_weight":      50,
    })

    if redis is not None:
        existing_keys = await redis.keys(f"scanner_reg:{bank_id}:*")
        for k in existing_keys:
            raw = await redis.get(k)
            if raw:
                try:
                    existing = _json.loads(raw)
                    if existing.get("branch_id") == branch_id:
                        await redis.delete(k)
                except Exception:
                    pass
        await redis.setex(f"scanner_reg:{bank_id}:{code}", 86400, payload)

    log.info("scanner_reg_code.generated",
             bank_id=bank_id, branch_id=branch_id,
             code_suffix=code[-4:],
             expires_at=expires_at.isoformat())

    return ScannerRegCodeResponse(
        code=code,
        branch_id=branch_id,
        branch_name=branch_name,
        bank_id=bank_id,
        expires_at=expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@router_v1.post(
    "/admin/scanner/register",
    response_model=ScannerRegisterResponse,
    status_code=status.HTTP_200_OK,
)
async def register_scanner(
    body: ScannerRegisterRequest,
    request: Request,
) -> ScannerRegisterResponse:
    """
    One-time registration code exchange. Called by the ASTRA installer on first run.
    Code is validated from Redis (single-use, 24h TTL), then a machine-bound API token
    is issued. The branch identity comes from the code — never from user input.
    """
    import secrets as _secrets
    import uuid as _uuid

    code = body.registration_code.upper().strip()
    if len(code) != 8 or not code.isalnum():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "SCANNER_REG_INVALID_CODE",
                    "message": "Registration code must be 8 alphanumeric characters."},
        )

    redis_client = getattr(request.app.state, "redis_client", None)
    db_pool      = getattr(request.app.state, "db_pool_cts", None)

    reg_data: dict | None = None

    if redis_client is not None:
        import json as _json
        keys = await redis_client.keys(f"scanner_reg:*:{code}")
        if keys:
            raw = await redis_client.getdel(keys[0])
            if raw:
                reg_data = _json.loads(raw)

    if reg_data is None:
        log.warning("scanner_reg.code_invalid", code_suffix=code[-4:],
                    machine_id=body.machine_id[:32])
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "SCANNER_REG_CODE_NOT_FOUND",
                    "message": "Registration code not found, expired, or already used. "
                               "Generate a new code in ASTRA Admin UI → Branches → Register Scanner."},
        )

    bank_id   = reg_data["bank_id"]
    branch_id = reg_data["branch_id"]
    bank_ifsc = reg_data["bank_ifsc"]

    api_token  = f"svc-scanner-{_secrets.token_urlsafe(32)}"
    token_id   = str(_uuid.uuid4())
    machine_id = body.machine_id[:128]

    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO cts.scanner_tokens
                        (token_id, bank_id, branch_id, machine_id, token_hash,
                         issued_at, expires_at, revoked)
                    VALUES ($1, $2, $3, $4,
                            encode(sha256($5::bytea), 'hex'),
                            now(),
                            now() + INTERVAL '10 years',
                            false)
                    """,
                    token_id, bank_id, branch_id, machine_id, api_token,
                )
        except Exception as exc:
            log.error("scanner_reg.token_write_failed", bank_id=bank_id,
                      branch_id=branch_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error_code": "SCANNER_REG_TOKEN_WRITE_FAILED",
                        "message": "Internal error issuing token. Please retry."},
            )

    log.info("scanner_reg.success",
             bank_id=bank_id, branch_id=branch_id,
             machine_id=machine_id[:16] + "...",
             token_id=token_id)

    api_url = str(request.base_url).rstrip("/")

    return ScannerRegisterResponse(
        api_url=api_url,
        bank_id=bank_id,
        bank_ifsc=bank_ifsc,
        branch_id=branch_id,
        branch_name=reg_data.get("branch_name", branch_id),
        api_token=api_token,
        endorsement_text=reg_data.get("endorsement_text", "ASTRA/CTS"),
        enable_imprinter=bool(reg_data.get("enable_imprinter", True)),
        enable_uv_scan=bool(reg_data.get("enable_uv_scan", False)),
        mocr_weight=int(reg_data.get("mocr_weight", 50)),
    )
