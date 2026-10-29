"""
CTS Outward Data Router — 17 routes.

Extracted from cts.py (Step 1g of the router-split plan).

Routes:
  POST /v1/cts/endorsement/batch
  GET  /v1/cts/outward/files/{filename}/download-url
  POST /v1/cts/iqa/{scan_id}/rescan
  GET  /v1/cts/sessions/{session_id}/download/{report_type}
  GET  /v1/cts/outward/human-review-queue
  POST /v1/cts/outward/review/{instrument_id}/decide
  GET  /v1/cts/outward/settlement
  GET  /v1/cts/outward/lots/{lot_id}/instruments
  GET  /v1/cts/outward/analytics/daily
  GET  /v1/cts/outward/reconciliation
  GET  /v1/cts/outward/lots
  GET  /v1/cts/outward/sessions
  GET  /v1/cts/outward/compliance
  GET  /v1/cts/outward/endorsement-queue
  GET  /v1/cts/outward/decisions
  GET  /v1/cts/outward/iqa-results
  GET  /v1/cts/outward/pipeline
"""
from __future__ import annotations

import json
from datetime import date
from typing import List, Literal, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from apps.api.schemas.types import IsoTimestamp, OptIsoTimestamp

from shared.auth.rbac import UserContext

from .cts_deps import (
    _COMPLIANCE_MAX_ROWS,
    _safe_temporal_param,
    get_current_user_context,
    get_temporal_client,
)

log = structlog.get_logger()


def _parse_jsonb(value):
    """asyncpg returns JSONB columns as a raw JSON string unless a codec is
    registered on the pool -- never assume it's already a dict."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return json.loads(value)

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS Outward Data v1"])


# ── Models ────────────────────────────────────────────────────────────────────

class EndorsementBatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str
    instrument_ids: list[str]
    bank_ifsc: str
    session_id: Optional[str] = None


class EndorsementBatchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    lot_number: str
    status: Literal["TRIGGERED"]
    instrument_count: int


class OutwardFileDownloadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    download_url: str
    expires_in_seconds: int = 300


class IQARescanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    workflow_id: str
    status: Literal["TRIGGERED"]


_SESSION_REPORT_EXTENSIONS = {
    "npci": "npci_rrf.zip",
    "mis": "mis.csv",
    "settlement": "settlement.xlsx",
}


class SessionDownloadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    report_type: str
    download_url: str
    expires_in_seconds: int


class OutwardQueueItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    cheque_number: str
    account_display: str
    payee_display: str
    amount_range: str
    outcome: str
    fraud_score: Optional[float] = None
    ocr_confidence: Optional[float] = None
    review_reason: Optional[str] = None
    received_at: IsoTimestamp
    branch_id: Optional[str] = None
    lot_id: Optional[str] = None
    instrument_category: str = "CHEQUE"   # "CHEQUE" | "DEMAND_DRAFT"
    assigned_to: Optional[str] = None     # reviewer holding the item (allocation lock), if any
    assigned_to_me: Optional[bool] = None  # True when the caller holds it


class OutwardQueueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[OutwardQueueItem]
    total: int


class OutwardReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Literal["CONFIRMED", "REJECTED"]
    reason: str
    reason_category: str = "manual"


class OutwardReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    action: str
    workflow_signal_sent: bool
    message: str


class OutwardValidationItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    cheque_number: str
    payee_display: str
    amount_range: str
    review_reason: Optional[str] = None
    branch_id: Optional[str] = None
    lot_id: Optional[str] = None
    instrument_category: str = "CHEQUE"
    maker_id: str
    maker_decision: str
    maker_reason: str = ""
    made_at: IsoTimestamp
    assigned_to: Optional[str] = None     # checker holding the item, if any
    assigned_to_me: Optional[bool] = None


class OutwardValidationQueueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[OutwardValidationItem]
    total: int


class SessionSettlementRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    branch_id: str
    branch_name: Optional[str] = None
    status: str
    clearing_date: IsoTimestamp
    hub_type: str
    total_uploaded: int
    total_accepted: int
    total_rejected: int
    total_held: int
    opened_at: IsoTimestamp
    closed_at: OptIsoTimestamp = None


class SettlementResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: IsoTimestamp
    sessions: list[SessionSettlementRow]
    total_instruments: int
    total_accepted: int
    total_rejected: int
    total_held: int


class LotInstrumentRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    instrument_id: Optional[str]
    micr_suffix: Optional[str]
    payee_display: Optional[str]
    amount_range: Optional[str]
    outcome: str
    scanned_at: IsoTimestamp


class LotInstrumentsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_id: str
    bank_id: str
    lot_status: str
    instrument_count: int
    instruments: list[LotInstrumentRow]


class DailyAnalyticsRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    total: int
    stp_confirm: int
    stp_return: int
    human_review: int
    avg_ms: float
    ocr_conf: Optional[float] = None
    sig_prec: Optional[float] = None


class DailyAnalyticsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    days: int
    daily: list[DailyAnalyticsRow]


class ReconciliationSessionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    recon_session_id: str
    recon_type: str
    status: str
    astra_instrument_count: Optional[int]
    ngch_instrument_count: Optional[int]
    discrepancy_count: int
    started_at: OptIsoTimestamp
    completed_at: OptIsoTimestamp


class DiscrepancyItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    discrepancy_id: str
    recon_session_id: str
    instrument_id: Optional[str]
    cheque_number: Optional[str]
    discrepancy_type: str
    astra_value: Optional[dict]
    ngch_value: Optional[dict]
    status: str
    created_at: IsoTimestamp
    instrument_category: str = "CHEQUE"   # "CHEQUE" | "DEMAND_DRAFT"


class ReconciliationOverviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    recon_date: IsoTimestamp
    sessions: list[ReconciliationSessionSummary]
    discrepancies: list[DiscrepancyItem]


class LotSummaryRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_id: str
    branch_id: str
    branch_name: Optional[str]
    session_id: str
    sequence_number: int
    status: str
    instrument_count: int
    max_instruments: int
    created_at: IsoTimestamp
    sealed_at: OptIsoTimestamp


class LotsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: IsoTimestamp
    lots: list[LotSummaryRow]


class ClearingSessionItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    clearing_date: IsoTimestamp
    session_type: str
    status: str
    label: str
    total_lots: int
    total_instruments: int
    ngch_reference: Optional[str] = None
    opened_at: IsoTimestamp
    closed_at: OptIsoTimestamp = None
    submitted_at: OptIsoTimestamp = None


class ClearingSessionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    sessions: list[ClearingSessionItem]
    total: int


class ComplianceCheckItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_id: str
    instrument_id: str
    check_type: str
    result: str
    detail: Optional[str] = None
    occurred_at: IsoTimestamp


class OutwardComplianceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    clearing_date: IsoTimestamp
    total_checked: int
    pass_count: int
    fail_count: int
    pass_rate_pct: float
    items: list[ComplianceCheckItem]


class EndorsementQueueItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    cheque: str
    suffix: str
    lot: str


class EndorsementQueueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[EndorsementQueueItem]
    total: int


class OutwardDecisionItem(BaseModel):
    instrument_id: str
    decision: str
    decision_reason: Optional[str] = None
    fraud_score: Optional[float] = None
    account_last4: Optional[str] = None
    amount_bucket: Optional[str] = None
    drawee_ifsc: Optional[str] = None
    lot_number: Optional[str] = None
    processing_started_at: OptIsoTimestamp = None
    instrument_category: str = "CHEQUE"   # "CHEQUE" | "DEMAND_DRAFT"


class OutwardDecisionsResponse(BaseModel):
    bank_id: str
    items: List[OutwardDecisionItem]
    total: int


class IQAResultItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    account: str
    lot: str
    scanner: Optional[str]
    status: str
    fail_reason: Optional[str]
    fail_label: Optional[str]
    scanned_at: IsoTimestamp
    ocr_conf: Optional[str]
    dpi: Optional[int]


class IQAResultsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[IQAResultItem]
    total: int


class OutwardPipelineInstrument(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    stage: str
    drawee: str
    amount: str
    lot: Optional[str]
    session_deadline: Optional[str]
    ocr_conf: Optional[float]
    iqa_fail: bool
    cts_violation: bool
    amount_mismatch: bool
    scanner: Optional[str]


class OutwardPipelineResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    instruments: list[OutwardPipelineInstrument]


# ── Role constants ─────────────────────────────────────────────────────────────

_OUTWARD_Q_ROLES = {"ops_reviewer", "ops_manager", "bank_it_admin", "branch_manager"}
SQL_MAKER_QUEUE = ("SELECT instrument_id, scan_id AS cheque_number, NULL::text AS account_display, "
                   "payee_display, amount_range, outcome AS status, NULL::float AS fraud_score, "
                   "NULL::float AS ocr_confidence, reject_reason AS review_reason, "
                   "scanned_at::text AS received_at, branch_id, lot_id, instrument_category "
                   "FROM cts.outward_scan_events "
                   "WHERE bank_id = $1 "
                   "AND outcome IN ('HUMAN_REVIEW', 'MISMATCH_HELD', 'CTS_REJECTED', 'WORKFLOW_ERROR') "
                   "AND ($3::text IS NULL OR instrument_category = $3) "
                   # any stage row means a maker has decided (waiting for a checker, or already filed): not the maker's work
                   "AND NOT EXISTS (SELECT 1 FROM cts.outward_review_stage g WHERE g.bank_id = outward_scan_events.bank_id "
                   "AND g.instrument_id = outward_scan_events.instrument_id) "
                   "ORDER BY scanned_at DESC LIMIT $2")
_OUTWARD_CHECK_ROLES = {"ops_reviewer", "ops_manager"}
SQL_STAGE_INSERT = ("INSERT INTO cts.outward_review_stage (bank_id, instrument_id, maker_id, maker_decision, maker_reason) "
                    "VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING")
SQL_STAGE_GET = ("SELECT maker_id, maker_decision FROM cts.outward_review_stage "
                 "WHERE bank_id = $1 AND instrument_id = $2 AND status = 'MAKER_DECIDED'")
SQL_STAGE_FINAL = ("UPDATE cts.outward_review_stage SET status = 'FINAL', checker_id = $3, checked_at = now() "
                   "WHERE bank_id = $1 AND instrument_id = $2 AND status = 'MAKER_DECIDED'")
SQL_STAGE_LIST = ("SELECT g.instrument_id, e.scan_id AS cheque_number, e.payee_display, e.amount_range, "
                  "e.reject_reason AS review_reason, e.branch_id, e.lot_id, e.instrument_category, "
                  "g.maker_id, g.maker_decision, g.maker_reason, g.made_at::text AS made_at, "
                  "EXTRACT(EPOCH FROM (now() - g.made_at)) AS age_seconds "
                  "FROM cts.outward_review_stage g LEFT JOIN cts.outward_scan_events e "
                  "ON e.bank_id = g.bank_id AND e.instrument_id = g.instrument_id "
                  "WHERE g.bank_id = $1 AND g.status = 'MAKER_DECIDED' ORDER BY g.made_at LIMIT $2")
_LOT_READ_ROLES = {"ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager"}
_ANALYTICS_READ_ROLES = {"ops_manager", "fraud_analyst", "bank_it_admin", "ops_reviewer"}
_RECON_READ_ROLES = {"ops_manager", "bank_it_admin", "compliance_officer"}
_LOTS_LIST_ROLES = {"ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager"}

_OUTCOME_TO_STAGE: dict[str, str] = {
    "SCANNED":       "SCANNED",
    "IQA_FAIL":      "IQA",
    "IQA_PASS":      "IQA",
    "AI_EXTRACTED":  "AI_EXTRACTED",
    "PKI_SIGNED":    "PKI_SIGNED",
    "LOT_ASSIGNED":  "LOT",
    "ENDORSED":      "ENDORSED",
    "NGCH_FILED":    "NGCH",
    "STP_CONFIRMED": "NGCH",
    "HUMAN_REVIEW":  "AI_EXTRACTED",
    "MISMATCH_HELD": "AI_EXTRACTED",
    "CTS_REJECTED":  "IQA",
    "STP_RETURN":    "IQA",
    "WORKFLOW_ERROR": "IQA",
}

_IQA_LABELS = {
    "DARK": "Image too dark — rescan required",
    "MICR": "MICR band not readable",
    "SKEW": "Image skew > 2°",
    "TORN": "Torn corner — rescan",
    "DUPLICATE": "Duplicate instrument detected",
    "BLUR": "Focus blur — rescan required",
    "FOLD": "Fold crease over amount field",
}


# ── Routes ─────────────────────────────────────────────────────────────────────

@router_v1.post(
    "/endorsement/batch",
    response_model=EndorsementBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def endorse_batch(
    body: EndorsementBatchRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> EndorsementBatchResponse:
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops_manager role required")

    import time as _time
    session_id = body.session_id or f"manual-{int(_time.time())}"
    workflow_id = f"cts-endorse-{bank_id}-{body.lot_number}"

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from modules.cts.workflows.batch_endorsement_workflow import (
                BatchEndorsementWorkflow, BatchEndorsementInput,
            )
            from temporalio.exceptions import WorkflowAlreadyStartedError
            try:
                await temporal_client.start_workflow(
                    BatchEndorsementWorkflow.run,
                    BatchEndorsementInput(
                        lot_number=body.lot_number,
                        bank_id=bank_id,
                        bank_ifsc=body.bank_ifsc,
                        session_id=session_id,
                        instrument_ids=body.instrument_ids,
                    ),
                    id=workflow_id,
                    task_queue=f"cts-processing-{bank_id}",
                )
            except WorkflowAlreadyStartedError:
                # Expected on a retriggered lot: the workflow id is deterministic (per lot). The prior
                # run's outcome stands; the caller should query it rather than expecting a new one.
                log.info("cts.endorsement.already_started", lot_number=body.lot_number, workflow_id=workflow_id)
        except Exception as exc:
            log.error("cts.endorsement_trigger_failed", lot_number=body.lot_number, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to trigger endorsement workflow",
            ) from exc

    log.info(
        "cts.endorsement.triggered",
        bank_id=bank_id,
        lot_number=body.lot_number,
        instrument_count=len(body.instrument_ids),
        workflow_id=workflow_id,
    )
    return EndorsementBatchResponse(
        workflow_id=workflow_id,
        lot_number=body.lot_number,
        status="TRIGGERED",
        instrument_count=len(body.instrument_ids),
    )


@router_v1.get(
    "/outward/files/{filename}/download-url",
    response_model=OutwardFileDownloadResponse,
)
async def get_outward_file_download_url(
    filename: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> OutwardFileDownloadResponse:
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "ops_reviewer", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    minio_client = getattr(request.app.state, "minio_client", None)
    if minio_client is not None:
        try:
            from datetime import timedelta
            bucket = f"cts-outward-{bank_id}"
            url = await minio_client.presigned_get_object(
                bucket,
                filename,
                expires=timedelta(seconds=300),
            )
            return OutwardFileDownloadResponse(filename=filename, download_url=url)
        except Exception as exc:
            log.error("cts.outward_file.presign_failed", filename=filename, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found or not yet generated",
            ) from exc

    return OutwardFileDownloadResponse(
        filename=filename,
        download_url=f"/dev-placeholder/{filename}",
        expires_in_seconds=300,
    )


@router_v1.post(
    "/iqa/{scan_id}/rescan",
    response_model=IQARescanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_iqa_rescan(
    scan_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IQARescanResponse:
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "ops_reviewer", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops_manager role required")

    import time as _time
    workflow_id = f"cts-iqa-rescan-{bank_id}-{scan_id}-{int(_time.time())}"

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow, OutwardScanInput
            await temporal_client.start_workflow(
                OutwardScanWorkflow.run,
                OutwardScanInput(
                    scan_id=scan_id,
                    bank_id=bank_id,
                    triggered_by=ctx.user_id,
                    rescan=True,
                ),
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
            )
        except Exception as exc:
            log.error("cts.iqa_rescan_failed", scan_id=scan_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to trigger re-scan workflow",
            ) from exc

    log.info("cts.iqa.rescan_triggered", scan_id=scan_id, bank_id=bank_id, workflow_id=workflow_id)
    return IQARescanResponse(scan_id=scan_id, workflow_id=workflow_id, status="TRIGGERED")


@router_v1.get(
    "/sessions/{session_id}/download/{report_type}",
    response_model=SessionDownloadResponse,
)
async def get_session_report_download_url(
    session_id: str,
    report_type: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> SessionDownloadResponse:
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "ops_reviewer", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops_manager role required")

    if report_type not in _SESSION_REPORT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown report_type '{report_type}'. Valid: {list(_SESSION_REPORT_EXTENSIONS)}",
        )

    ext = _SESSION_REPORT_EXTENSIONS[report_type]
    object_name = f"cts/{bank_id}/sessions/{session_id}/{ext}"

    minio_client = getattr(request.app.state, "minio_client", None)
    if minio_client is not None:
        try:
            from datetime import timedelta as _td
            presigned = minio_client.presigned_get_object(
                "astra-cts",
                object_name,
                expires=_td(seconds=300),
            )
            download_url = presigned
        except Exception as exc:
            log.error("cts.session_download.presign_failed", session_id=session_id, report_type=report_type, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to generate download URL",
            ) from exc
    else:
        download_url = f"/dev-placeholder/sessions/{session_id}/{ext}"

    log.info("cts.session_download.url_issued", session_id=session_id, report_type=report_type, bank_id=bank_id)
    return SessionDownloadResponse(
        session_id=session_id,
        report_type=report_type,
        download_url=download_url,
        expires_in_seconds=300,
    )


@router_v1.get("/outward/human-review-queue", response_model=OutwardQueueResponse)
async def get_outward_human_review_queue(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = 50,
    instrument_category: Optional[str] = Query(None),
) -> OutwardQueueResponse:
    if ctx.role.value not in _OUTWARD_Q_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    bank_id = ctx.bank_id
    if limit > 100:
        limit = 100

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return OutwardQueueResponse(bank_id=bank_id, items=[], total=0)

    try:
        rows = await db.fetch(SQL_MAKER_QUEUE, bank_id, limit, instrument_category)
    except Exception as exc:
        log.error("cts.outward_queue.query_failed", bank_id=bank_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable") from exc

    cfg = await _cts_config(request, bank_id)
    holders = await _holders_and_assign(request, ctx, [r["instrument_id"] for r in rows], cfg)
    items = [
        OutwardQueueItem(
            instrument_id=r["instrument_id"],
            cheque_number=r["cheque_number"] or "",
            account_display=r["account_display"] or "****",
            payee_display=r["payee_display"] or "",
            amount_range=r["amount_range"] or "",
            outcome=r["status"],
            fraud_score=r["fraud_score"],
            ocr_confidence=r["ocr_confidence"],
            review_reason=r["review_reason"],
            received_at=r["received_at"],
            branch_id=r["branch_id"],
            lot_id=r.get("lot_id"),
            instrument_category=r["instrument_category"] or "CHEQUE",
            assigned_to=holders.get(r["instrument_id"]),
            assigned_to_me=holders.get(r["instrument_id"]) == ctx.user_id,
        )
        for r in rows
    ]
    return OutwardQueueResponse(bank_id=bank_id, items=items, total=len(items))


async def _cts_config(request: Request, bank_id: str) -> dict:
    cs = getattr(request.app.state, "config_service", None)
    if cs is None:
        return {}
    try:
        return dict(await cs.get_cts_config(bank_id))
    except Exception:  # noqa: BLE001 - config trouble must not change who can file a decision
        return {}


async def _maker_checker_on(request: Request, bank_id: str) -> bool:
    return bool((await _cts_config(request, bank_id)).get("maker_checker_enabled"))


def _lock_service(request: Request):
    """The same allocation locks the inward queue uses (None without Redis, in which case outward works as before)."""
    redis = getattr(request.app.state, "redis_cts", None)
    if redis is None:
        return None
    from modules.cts.allocation.lock_service import LockService
    return LockService(redis_client=redis)


async def _holders_and_assign(request: Request, ctx: UserContext, instrument_ids: list, cfg: dict,
                              exclude_by_id: Optional[dict] = None) -> dict:
    """Heartbeat the caller, assign unheld items in AUTO mode (never to an excluded person), return {instrument_id: holder}.
    Outward items carry no bucket, so any active reviewer is eligible; their load counts alongside inward work."""
    lock = _lock_service(request)
    if lock is None or not instrument_ids:
        return {}
    bank_id = ctx.bank_id
    try:
        if ctx.role.value in ("ops_reviewer", "ops_manager"):
            await lock.heartbeat_reviewer(bank_id, ctx.user_id, pu_ids=list(getattr(ctx, "pu_ids", None) or []))
        holders = dict(await lock.get_lock_holders(instrument_ids))
        if cfg.get("allocation_mode") == "AUTO":
            from modules.cts.allocation.allocation_service import AllocationService
            alloc = AllocationService(lock_service=lock)
            available = await lock.get_active_reviewers(bank_id)
            for iid in instrument_ids:
                if holders.get(iid):
                    continue
                excl = {(exclude_by_id or {}).get(iid)} - {None}
                res = await alloc.auto_assign(iid, available, cfg, bank_id=bank_id, exclude=excl or None)
                if res.claimed:
                    holders[iid] = res.reviewer_id
        return holders
    except Exception as exc:  # noqa: BLE001 - allocation trouble must never hide the queue itself
        log.warning("cts.outward_alloc.failed", bank_id=bank_id, error=str(exc))
        return {}


async def _take_or_check_claim(request: Request, ctx: UserContext, instrument_id: str, cfg: dict) -> None:
    """Whoever decides must hold the item: take it if free, refuse (409, without saying who) if another reviewer holds it."""
    lock = _lock_service(request)
    if lock is None:
        return
    holder = await lock.get_lock_holder(instrument_id)
    if holder is not None and holder != ctx.user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This instrument is being worked by another reviewer")
    if holder is None and not await lock.acquire_lock(instrument_id, ctx.user_id, cfg):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This instrument is being worked by another reviewer")


async def _release_claim(request: Request, ctx: UserContext, instrument_id: str) -> None:
    lock = _lock_service(request)
    if lock is None:
        return
    try:
        await lock.release_lock(instrument_id, ctx.user_id, bank_id=ctx.bank_id)
        await lock.forget_item(ctx.bank_id, instrument_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("cts.outward_alloc.release_failed", instrument_id=instrument_id, error=str(exc))


async def _file_outward_decision(request: Request, ctx: UserContext, instrument_id: str, action: str, reason: str) -> bool:
    """Make a decision final: signal the workflow, set the instrument status, close the review item. True if signalled."""
    bank_id = ctx.bank_id
    temporal = getattr(request.app.state, "temporal_client", None)
    signal_sent = False
    if temporal is not None:
        try:
            wf = temporal.get_workflow_handle(f"cts-{bank_id}-{instrument_id}")
            await wf.signal("receive_review_decision", {"action": action, "reason": reason})
            signal_sent = True
        except Exception as exc:
            log.warning("cts.outward_review.signal_failed", instrument_id=instrument_id, error=str(exc))

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is not None:
        try:
            new_status = "STP_CONFIRM" if action == "CONFIRMED" else "STP_RETURN"
            async with db.acquire() as conn:
                await conn.execute(
                    "UPDATE cts.cheque_instruments SET status=$1 WHERE instrument_id=$2 AND bank_id=$3",
                    new_status, instrument_id, bank_id,
                )
        except Exception as exc:
            log.warning("cts.outward_review.db_update_failed", instrument_id=instrument_id, error=str(exc))
        try:
            from modules.cts.review_queue import decide_by_instrument
            async with db.acquire() as conn:
                await decide_by_instrument(conn, bank_id=bank_id, direction="OUTWARD", instrument_ref=instrument_id,
                                           decision=action, reviewer_id=ctx.user_id, notes=reason or "")
        except Exception as exc:  # noqa: BLE001
            log.warning("cts.review_queue.decision_record_failed", instrument_id=instrument_id, error=str(exc))
    return signal_sent


@router_v1.post(
    "/outward/review/{instrument_id}/decide",
    response_model=OutwardReviewDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def decide_outward_review(
    instrument_id: str,
    body: OutwardReviewDecisionRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> OutwardReviewDecisionResponse:
    """The reviewer's decision. With maker-checker on it is the maker's: staged for a checker, not yet final."""
    if ctx.role.value not in _OUTWARD_Q_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    bank_id = ctx.bank_id
    instrument_id = _safe_temporal_param(instrument_id, "instrument_id")

    db = getattr(request.app.state, "db_pool_cts", None)
    cfg = await _cts_config(request, bank_id)
    await _take_or_check_claim(request, ctx, instrument_id, cfg)
    if db is not None and cfg.get("maker_checker_enabled"):
        async with db.acquire() as conn:
            result = await conn.execute(SQL_STAGE_INSERT, bank_id, instrument_id, ctx.user_id, body.action, body.reason or "")
        if not str(result).endswith(" 1"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="A decision has already been made on this instrument and is waiting for a checker")
        await _release_claim(request, ctx, instrument_id)        # free for a checker (never the maker)
        log.info("cts.outward_review.maker_decided", instrument_id=instrument_id, action=body.action, bank_id=bank_id)
        return OutwardReviewDecisionResponse(
            instrument_id=instrument_id, action=body.action, workflow_signal_sent=False,
            message=f"Decision {body.action} recorded and sent to a checker; it is not final until the checker confirms.")

    signal_sent = await _file_outward_decision(request, ctx, instrument_id, body.action, body.reason)
    await _release_claim(request, ctx, instrument_id)
    log.info("cts.outward_review.decided", instrument_id=instrument_id, action=body.action, bank_id=bank_id)
    return OutwardReviewDecisionResponse(
        instrument_id=instrument_id,
        action=body.action,
        workflow_signal_sent=signal_sent,
        message=f"Decision {body.action} recorded. Workflow signal {'sent' if signal_sent else 'queued (Temporal unavailable)'}.",
    )


@router_v1.post(
    "/outward/review/{instrument_id}/validate",
    response_model=OutwardReviewDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_outward_review(
    instrument_id: str,
    body: OutwardReviewDecisionRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> OutwardReviewDecisionResponse:
    """The checker's decision on a staged maker decision: confirm or overrule it. Never the maker."""
    if ctx.role.value not in _OUTWARD_CHECK_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    bank_id = ctx.bank_id
    instrument_id = _safe_temporal_param(instrument_id, "instrument_id")
    if not body.reason or not body.reason.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="reason is required for validation")
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")
    if not await _maker_checker_on(request, bank_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Maker-checker is not enabled for this bank")

    async with db.acquire() as conn:
        staged = await conn.fetchrow(SQL_STAGE_GET, bank_id, instrument_id)
    if not staged:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This instrument is not waiting for a checker")
    if staged["maker_id"] == ctx.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You made the first decision on this instrument; a different person must check it")
    await _take_or_check_claim(request, ctx, instrument_id, await _cts_config(request, bank_id))

    # Claim the decision first (only one checker, or the timeout, can move it from MAKER_DECIDED to FINAL), then file it.
    try:
        async with db.acquire() as conn:
            claimed = await conn.execute(SQL_STAGE_FINAL, bank_id, instrument_id, ctx.user_id)
    except asyncpg.exceptions.SerializationError as exc:
        # Another checker finished this item at the same moment (YugabyteDB aborts the second writer).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another checker is handling this instrument") from exc
    if not str(claimed).endswith(" 1"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This instrument is not waiting for a checker")
    signal_sent = await _file_outward_decision(request, ctx, instrument_id, body.action, body.reason.strip())
    await _release_claim(request, ctx, instrument_id)
    log.info("cts.outward_review.validated", instrument_id=instrument_id, bank_id=bank_id, checker_id=ctx.user_id,
             maker_id=staged["maker_id"], overrode=body.action != staged["maker_decision"])
    return OutwardReviewDecisionResponse(
        instrument_id=instrument_id, action=body.action, workflow_signal_sent=signal_sent,
        message=f"Decision {body.action} filed by the checker.")


async def _file_overdue_maker_decisions(request: Request, ctx: UserContext, db, rows: list, cfg: dict) -> list:
    """A staged decision no checker took within checker_review_timeout_minutes is filed on the maker's word (inward does the
    same). Outward has no workflow to time out, so this runs whenever the validation queue is read. The conditional update
    means a checker and this timeout can never both file the same item."""
    from types import SimpleNamespace
    timeout_s = max(1, int(cfg.get("checker_review_timeout_minutes", 15))) * 60
    system = SimpleNamespace(bank_id=ctx.bank_id, user_id="SYSTEM")
    kept = []
    for r in rows:
        if float(r.get("age_seconds") or 0.0) < timeout_s:
            kept.append(r)
            continue
        try:
            async with db.acquire() as conn:
                claimed = await conn.execute(SQL_STAGE_FINAL, ctx.bank_id, r["instrument_id"], "SYSTEM")
        except Exception as exc:  # noqa: BLE001 - leave it for a checker
            log.warning("cts.outward_review.timeout_claim_failed", instrument_id=r["instrument_id"], error=str(exc))
            kept.append(r)
            continue
        if not str(claimed).endswith(" 1"):
            continue                                          # a checker got there first
        await _file_outward_decision(request, system, r["instrument_id"], r["maker_decision"],
                                     "Filed on the maker's decision: no checker acted in time")
        await _release_claim(request, system, r["instrument_id"])
        log.info("cts.outward_review.maker_auto_filed", instrument_id=r["instrument_id"], maker_id=r["maker_id"],
                 action=r["maker_decision"], bank_id=ctx.bank_id)
    return kept


@router_v1.get("/outward/validation-queue", response_model=OutwardValidationQueueResponse)
async def get_outward_validation_queue(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = Query(100, ge=1, le=100),
) -> OutwardValidationQueueResponse:
    """Outward instruments whose maker has decided and which wait for a checker."""
    if ctx.role.value not in _OUTWARD_CHECK_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return OutwardValidationQueueResponse(bank_id=ctx.bank_id, items=[], total=0)
    try:
        rows = await db.fetch(SQL_STAGE_LIST, ctx.bank_id, limit)
    except Exception as exc:
        log.error("cts.outward_validation_queue.query_failed", bank_id=ctx.bank_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable") from exc
    cfg = await _cts_config(request, ctx.bank_id)
    rows = await _file_overdue_maker_decisions(request, ctx, db, rows, cfg)
    holders = await _holders_and_assign(request, ctx, [r["instrument_id"] for r in rows], cfg,
                                        exclude_by_id={r["instrument_id"]: r["maker_id"] for r in rows})
    items = [OutwardValidationItem(
        instrument_id=r["instrument_id"], cheque_number=r["cheque_number"] or "", payee_display=r["payee_display"] or "",
        amount_range=r["amount_range"] or "", review_reason=r["review_reason"], branch_id=r["branch_id"], lot_id=r["lot_id"],
        instrument_category=r["instrument_category"] or "CHEQUE", maker_id=r["maker_id"],
        maker_decision=r["maker_decision"], maker_reason=r["maker_reason"], made_at=str(r["made_at"]),
        assigned_to=holders.get(r["instrument_id"]), assigned_to_me=holders.get(r["instrument_id"]) == ctx.user_id) for r in rows]
    return OutwardValidationQueueResponse(bank_id=ctx.bank_id, items=items, total=len(items))


@router_v1.get("/outward/settlement", response_model=SettlementResponse)
async def get_outward_settlement(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    clearing_date: OptIsoTimestamp = None,
) -> SettlementResponse:
    if ctx.role.value not in {"ops_manager", "bank_it_admin", "compliance_officer"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    bank_id = ctx.bank_id
    target_date = clearing_date or date.today().isoformat()

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return SettlementResponse(
            bank_id=bank_id, clearing_date=target_date,
            sessions=[], total_instruments=0, total_accepted=0, total_rejected=0, total_held=0,
        )

    try:
        rows = await db.fetch(
            """
            SELECT s.session_id, s.branch_id, b.branch_name,
                   s.status, s.clearing_date::text, s.hub_type,
                   s.total_uploaded, s.total_accepted, s.total_rejected, s.total_held,
                   s.opened_at::text, s.closed_at::text
            FROM cts.eeh_sessions s
            LEFT JOIN cts.branches b USING (branch_id, bank_id)
            WHERE s.bank_id = $1 AND s.clearing_date = $2::date
            ORDER BY s.opened_at ASC
            """,
            bank_id, target_date,
        )
    except Exception as exc:
        log.error("cts.settlement.query_failed", bank_id=bank_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable") from exc

    sessions = [
        SessionSettlementRow(
            session_id=r["session_id"],
            branch_id=r["branch_id"],
            branch_name=r["branch_name"],
            status=r["status"],
            clearing_date=r["clearing_date"],
            hub_type=r["hub_type"],
            total_uploaded=r["total_uploaded"],
            total_accepted=r["total_accepted"],
            total_rejected=r["total_rejected"],
            total_held=r["total_held"],
            opened_at=r["opened_at"],
            closed_at=r["closed_at"],
        )
        for r in rows
    ]
    total_instruments = sum(s.total_uploaded for s in sessions)
    total_accepted    = sum(s.total_accepted for s in sessions)
    total_rejected    = sum(s.total_rejected for s in sessions)
    total_held        = sum(s.total_held    for s in sessions)
    return SettlementResponse(
        bank_id=bank_id,
        clearing_date=target_date,
        sessions=sessions,
        total_instruments=total_instruments,
        total_accepted=total_accepted,
        total_rejected=total_rejected,
        total_held=total_held,
    )


@router_v1.get("/outward/lots/{lot_id}/instruments", response_model=LotInstrumentsResponse)
async def get_lot_instruments(
    lot_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
):
    if ctx.role.value not in _LOT_READ_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    bank_id = ctx.bank_id

    async with db.acquire() as conn:
        lot_row = await conn.fetchrow(
            "SELECT lot_id, bank_id, status, instrument_count FROM cts.lots WHERE lot_id = $1",
            lot_id,
        )
        if lot_row is None:
            raise HTTPException(status_code=404, detail="Lot not found")
        if lot_row["bank_id"] != bank_id:
            raise HTTPException(status_code=403, detail="Lot belongs to a different bank")

        rows = await conn.fetch(
            """
            SELECT scan_id::text, instrument_id, micr_suffix, payee_display,
                   amount_range, outcome, scanned_at::text
            FROM cts.outward_scan_events
            WHERE lot_id = $1
              AND bank_id = $2
            ORDER BY scanned_at
            """,
            lot_id,
            bank_id,
        )

    instruments = [
        LotInstrumentRow(
            scan_id=str(r["scan_id"]),
            instrument_id=r["instrument_id"],
            micr_suffix=r["micr_suffix"],
            payee_display=r["payee_display"],
            amount_range=r["amount_range"],
            outcome=r["outcome"],
            scanned_at=str(r["scanned_at"]),
        )
        for r in rows
    ]

    return LotInstrumentsResponse(
        lot_id=lot_id,
        bank_id=bank_id,
        lot_status=lot_row["status"],
        instrument_count=lot_row["instrument_count"],
        instruments=instruments,
    )


@router_v1.get("/outward/analytics/daily", response_model=DailyAnalyticsResponse)
async def get_outward_analytics_daily(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    days: int = 7,
    instrument_category: Optional[str] = Query(None),
):
    if ctx.role.value not in _ANALYTICS_READ_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    bank_id = ctx.bank_id
    days = max(1, min(days, 30))

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH daily AS (
                SELECT
                    DATE(scanned_at AT TIME ZONE 'Asia/Kolkata')   AS day,
                    COUNT(*)                                        AS total,
                    COUNT(*) FILTER (WHERE outcome = 'ACCEPTED')   AS stp_confirm,
                    COUNT(*) FILTER (WHERE outcome = 'CTS_REJECTED') AS stp_return,
                    COUNT(*) FILTER (WHERE outcome = 'MISMATCH_HELD') AS human_review
                FROM cts.outward_scan_events
                WHERE bank_id = $1
                  AND scanned_at >= NOW() - ($2 || ' days')::INTERVAL
                  AND ($3::text IS NULL OR instrument_category = $3)
                GROUP BY day
                ORDER BY day
            )
            SELECT
                day::text                     AS date,
                total::int                    AS total,
                stp_confirm::int              AS stp_confirm,
                stp_return::int               AS stp_return,
                human_review::int             AS human_review,
                0.0::float                    AS avg_ms
            FROM daily
            """,
            bank_id,
            str(days),
            instrument_category,
        )

    daily_list = [
        DailyAnalyticsRow(
            date=r["date"],
            total=r["total"],
            stp_confirm=r["stp_confirm"],
            stp_return=r["stp_return"],
            human_review=r["human_review"],
            avg_ms=r["avg_ms"],
        )
        for r in rows
    ]

    return DailyAnalyticsResponse(
        bank_id=bank_id,
        days=days,
        daily=daily_list,
    )


@router_v1.get("/outward/reconciliation", response_model=ReconciliationOverviewResponse)
async def get_outward_reconciliation(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    recon_date: OptIsoTimestamp = None,
    limit: int = Query(200, ge=1, le=500),
    instrument_category: Optional[str] = Query(None),
) -> ReconciliationOverviewResponse:
    if ctx.role.value not in _RECON_READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    bank_id = ctx.bank_id
    date_str = recon_date or date.today().isoformat()

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return ReconciliationOverviewResponse(
            bank_id=bank_id, recon_date=date_str, sessions=[], discrepancies=[],
        )

    try:
        session_rows = await db.fetch(
            """
            SELECT recon_session_id::text, recon_type, status,
                   astra_instrument_count, ngch_instrument_count, discrepancy_count,
                   started_at::text, completed_at::text
            FROM cts.reconciliation_sessions
            WHERE bank_id = $1 AND recon_date = $2::date
            ORDER BY started_at DESC
            """,
            bank_id, date_str,
        )

        recon_ids = [r["recon_session_id"] for r in session_rows]
        disc_rows: list = []
        if recon_ids:
            disc_rows = await db.fetch(
                """
                SELECT rd.discrepancy_id::text, rd.recon_session_id::text,
                       rd.instrument_id::text, rd.cheque_number, rd.discrepancy_type,
                       rd.astra_value, rd.ngch_value, rd.status, rd.created_at::text,
                       ose.instrument_category
                FROM cts.reconciliation_discrepancies rd
                LEFT JOIN cts.outward_scan_events ose
                  ON ose.instrument_id = rd.instrument_id::text AND ose.bank_id = rd.bank_id
                WHERE rd.recon_session_id = ANY($1::uuid[])
                  AND rd.bank_id = $2
                  AND ($4::text IS NULL OR ose.instrument_category = $4)
                ORDER BY rd.created_at DESC
                LIMIT $3
                """,
                recon_ids, bank_id, limit, instrument_category,
            )
    except Exception as exc:
        log.error("cts.reconciliation.query_failed", bank_id=bank_id, error=str(exc))
        return ReconciliationOverviewResponse(
            bank_id=bank_id, recon_date=date_str, sessions=[], discrepancies=[],
        )

    sessions = [
        ReconciliationSessionSummary(
            recon_session_id=r["recon_session_id"],
            recon_type=r["recon_type"],
            status=r["status"],
            astra_instrument_count=r["astra_instrument_count"],
            ngch_instrument_count=r["ngch_instrument_count"],
            discrepancy_count=r["discrepancy_count"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
        )
        for r in session_rows
    ]
    discrepancies = [
        DiscrepancyItem(
            discrepancy_id=r["discrepancy_id"],
            recon_session_id=r["recon_session_id"],
            instrument_id=r["instrument_id"],
            cheque_number=r["cheque_number"],
            discrepancy_type=r["discrepancy_type"],
            astra_value=_parse_jsonb(r["astra_value"]),
            ngch_value=_parse_jsonb(r["ngch_value"]),
            status=r["status"],
            created_at=r["created_at"],
            instrument_category=r["instrument_category"] or "CHEQUE",
        )
        for r in disc_rows
    ]
    return ReconciliationOverviewResponse(
        bank_id=bank_id, recon_date=date_str, sessions=sessions, discrepancies=discrepancies,
    )


@router_v1.get("/outward/lots", response_model=LotsListResponse)
async def list_outward_lots(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    clearing_date: OptIsoTimestamp = None,
) -> LotsListResponse:
    if ctx.role.value not in _LOTS_LIST_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    bank_id = ctx.bank_id
    date_str = clearing_date or date.today().isoformat()

    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return LotsListResponse(bank_id=bank_id, clearing_date=date_str, lots=[])

    try:
        rows = await db.fetch(
            """
            SELECT l.lot_id, l.branch_id, b.branch_name,
                   l.session_id, l.sequence_number, l.status,
                   l.instrument_count, l.max_instruments,
                   l.created_at::text, l.sealed_at::text
            FROM cts.lots l
            LEFT JOIN cts.branches b
              ON b.branch_id = l.branch_id AND b.bank_id = l.bank_id
            WHERE l.bank_id = $1 AND l.clearing_date = $2::date
            ORDER BY l.created_at ASC
            """,
            bank_id, date_str,
        )
    except Exception as exc:
        log.error("cts.lots_list.query_failed", bank_id=bank_id, error=str(exc))
        return LotsListResponse(bank_id=bank_id, clearing_date=date_str, lots=[])

    lots = [
        LotSummaryRow(
            lot_id=r["lot_id"],
            branch_id=r["branch_id"],
            branch_name=r["branch_name"],
            session_id=r["session_id"],
            sequence_number=r["sequence_number"],
            status=r["status"],
            instrument_count=r["instrument_count"],
            max_instruments=r["max_instruments"],
            created_at=r["created_at"],
            sealed_at=r["sealed_at"],
        )
        for r in rows
    ]
    return LotsListResponse(bank_id=bank_id, clearing_date=date_str, lots=lots)


@router_v1.get("/outward/sessions", response_model=ClearingSessionsResponse)
async def get_clearing_sessions(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = Query(20, ge=1, le=100),
) -> ClearingSessionsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return ClearingSessionsResponse(bank_id=bank_id, sessions=[], total=0)

    try:
        rows = await db.fetch(
            """
            SELECT
                cs.session_id,
                cs.clearing_date::text,
                cs.session_type,
                cs.status,
                cs.ngch_reference,
                cs.opened_at::text,
                cs.closed_at::text,
                cs.submitted_at::text,
                COUNT(DISTINCT l.lot_id)::int         AS total_lots,
                COALESCE(SUM(l.instrument_count), 0)::int AS total_instruments
            FROM cts.clearing_sessions cs
            LEFT JOIN cts.lots l
                   ON l.session_id = cs.session_id AND l.bank_id = cs.bank_id
            WHERE cs.bank_id = $1
              AND cs.clearing_date = CURRENT_DATE
            GROUP BY cs.session_id, cs.clearing_date, cs.session_type,
                     cs.status, cs.ngch_reference, cs.opened_at,
                     cs.closed_at, cs.submitted_at
            ORDER BY cs.opened_at DESC
            LIMIT $2
            """,
            bank_id,
            limit,
        )
    except Exception as exc:
        log.warning("cts.sessions.query_failed", bank_id=bank_id, error=str(exc))
        return ClearingSessionsResponse(bank_id=bank_id, sessions=[], total=0)

    sessions = []
    for r in rows:
        stype = r["session_type"] or "MORNING"
        label_map = {
            "MORNING":   "10:00–12:00",
            "AFTERNOON": "12:00–14:00",
            "EVENING":   "14:00–16:00",
            "SPECIAL":   "Special Session",
        }
        sessions.append(ClearingSessionItem(
            session_id=r["session_id"],
            clearing_date=r["clearing_date"],
            session_type=stype,
            status=r["status"],
            label=label_map.get(stype, stype),
            total_lots=r["total_lots"],
            total_instruments=r["total_instruments"],
            ngch_reference=r["ngch_reference"],
            opened_at=r["opened_at"] or "",
            closed_at=r["closed_at"],
            submitted_at=r["submitted_at"],
        ))
    return ClearingSessionsResponse(bank_id=bank_id, sessions=sessions, total=len(sessions))


@router_v1.get("/outward/compliance", response_model=OutwardComplianceResponse)
async def get_outward_compliance(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    result_filter: Optional[str] = Query(None, alias="result"),
) -> OutwardComplianceResponse:
    bank_id = ctx.bank_id
    today = date.today().isoformat()
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return OutwardComplianceResponse(
            bank_id=bank_id, clearing_date=today,
            total_checked=0, pass_count=0, fail_count=0, pass_rate_pct=0.0, items=[]
        )

    try:
        result_clause = "AND cc.result = $2" if result_filter else ""
        params: list = [bank_id]
        if result_filter:
            params.append(result_filter)
        rows = await db.fetch(
            f"""
            SELECT
                cc.lot_id, cc.instrument_id, cc.check_type,
                cc.result, cc.detail, cc.occurred_at::text
            FROM cts.compliance_checks cc
            WHERE cc.bank_id = $1
              AND cc.occurred_at::date = CURRENT_DATE
              {result_clause}
            ORDER BY cc.result DESC, cc.occurred_at DESC
            LIMIT {_COMPLIANCE_MAX_ROWS}
            """,
            *params,
        )
        totals = await db.fetchrow(
            """
            SELECT
                COUNT(*)::int                                    AS total,
                COUNT(*) FILTER (WHERE result = 'PASS')::int    AS pass_count,
                COUNT(*) FILTER (WHERE result = 'FAIL')::int    AS fail_count
            FROM cts.compliance_checks
            WHERE bank_id = $1 AND occurred_at::date = CURRENT_DATE
            """,
            bank_id,
        )
    except Exception as exc:
        log.warning("cts.compliance.query_failed", bank_id=bank_id, error=str(exc))
        return OutwardComplianceResponse(
            bank_id=bank_id, clearing_date=today,
            total_checked=0, pass_count=0, fail_count=0, pass_rate_pct=0.0, items=[]
        )

    total = totals["total"] if totals else 0
    pass_c = totals["pass_count"] if totals else 0
    fail_c = totals["fail_count"] if totals else 0
    pass_rate = round(100.0 * pass_c / total, 2) if total > 0 else 0.0

    items = [
        ComplianceCheckItem(
            lot_id=r["lot_id"] or "",
            instrument_id=r["instrument_id"] or "",
            check_type=r["check_type"],
            result=r["result"],
            detail=r["detail"],
            occurred_at=r["occurred_at"] or "",
        )
        for r in rows
    ]
    return OutwardComplianceResponse(
        bank_id=bank_id, clearing_date=today,
        total_checked=total, pass_count=pass_c, fail_count=fail_c,
        pass_rate_pct=pass_rate, items=items
    )


@router_v1.get("/outward/endorsement-queue", response_model=EndorsementQueueResponse)
async def get_endorsement_queue(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    ctx: UserContext = Depends(get_current_user_context),
) -> EndorsementQueueResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return EndorsementQueueResponse(bank_id=bank_id, items=[], total=0)
    try:
        rows = await db.fetch(
            """
            SELECT instrument_id, cheque_number, account_suffix, lot_number
            FROM cts.cheque_instruments
            WHERE bank_id = $1
              AND direction = 'OUTWARD'
              AND status IN ('PENDING_ENDORSEMENT', 'SCANNED', 'OCR_COMPLETE')
              AND received_at::date = CURRENT_DATE
            ORDER BY lot_number, received_at
            LIMIT $2
            """,
            bank_id,
            limit,
        )
    except Exception as exc:
        log.warning("cts.endorsement_queue.query_failed", bank_id=bank_id, error=str(exc))
        return EndorsementQueueResponse(bank_id=bank_id, items=[], total=0)

    items = [
        EndorsementQueueItem(
            id=r["instrument_id"],
            cheque=r["cheque_number"] or "",
            suffix=r["account_suffix"] or "0000",
            lot=r["lot_number"] or "LOT-01",
        )
        for r in rows
    ]
    return EndorsementQueueResponse(bank_id=bank_id, items=items, total=len(items))


@router_v1.get("/outward/decisions", response_model=OutwardDecisionsResponse)
async def get_outward_decisions(
    request: Request,
    outcome: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    ctx: UserContext = Depends(get_current_user_context),
) -> OutwardDecisionsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return OutwardDecisionsResponse(bank_id=bank_id, items=[], total=0)

    outcome_filter: Optional[list] = None
    if outcome:
        outcome_filter = [o.strip() for o in outcome.split(",") if o.strip()]

    try:
        if outcome_filter:
            rows = await db.fetch(
                """
                SELECT instrument_id, scan_id, payee_display, amount_range,
                       outcome, lot_id, branch_id, reject_reason, scanned_at::text,
                       instrument_category
                FROM cts.outward_scan_events
                WHERE bank_id = $1
                  AND outcome = ANY($2)
                  AND scanned_at > NOW() - INTERVAL '24 hours'
                ORDER BY scanned_at DESC
                LIMIT $3
                """,
                bank_id, outcome_filter, limit,
            )
        else:
            rows = await db.fetch(
                """
                SELECT instrument_id, scan_id, payee_display, amount_range,
                       outcome, lot_id, branch_id, reject_reason, scanned_at::text,
                       instrument_category
                FROM cts.outward_scan_events
                WHERE bank_id = $1
                  AND scanned_at > NOW() - INTERVAL '24 hours'
                ORDER BY scanned_at DESC
                LIMIT $2
                """,
                bank_id, limit,
            )
    except Exception as exc:
        log.warning("cts.outward_decisions.query_failed", bank_id=bank_id, error=str(exc))
        return OutwardDecisionsResponse(bank_id=bank_id, items=[], total=0)

    items = [
        OutwardDecisionItem(
            instrument_id=r["instrument_id"],
            decision=r["outcome"],
            decision_reason=r["reject_reason"],
            fraud_score=None,
            account_last4=None,
            amount_bucket=r["amount_range"],
            drawee_ifsc=None,
            lot_number=r["lot_id"],
            processing_started_at=r["scanned_at"],
            instrument_category=r["instrument_category"] or "CHEQUE",
        )
        for r in rows
    ]
    return OutwardDecisionsResponse(bank_id=bank_id, items=items, total=len(items))


@router_v1.get("/outward/iqa-results", response_model=IQAResultsResponse)
async def get_iqa_results(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    ctx: UserContext = Depends(get_current_user_context),
) -> IQAResultsResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return IQAResultsResponse(bank_id=bank_id, items=[], total=0)
    try:
        rows = await db.fetch(
            """
            SELECT instrument_id, account_suffix, lot_number, scanner_id,
                   iqa_status, iqa_fail_reason, scanned_at, ocr_confidence, scan_dpi
            FROM cts.cheque_instruments
            WHERE bank_id = $1
              AND direction = 'OUTWARD'
              AND scanned_at::date = CURRENT_DATE
              AND scanned_at IS NOT NULL
            ORDER BY scanned_at DESC
            LIMIT $2
            """,
            bank_id,
            limit,
        )
    except Exception as exc:
        log.warning("cts.iqa_results.query_failed", bank_id=bank_id, error=str(exc))
        return IQAResultsResponse(bank_id=bank_id, items=[], total=0)

    items = [
        IQAResultItem(
            id=r["instrument_id"],
            account=f"****{r['account_suffix']}" if r["account_suffix"] else "****0000",
            lot=r["lot_number"] or "LOT-01",
            scanner=r["scanner_id"],
            status=r["iqa_status"] or "IQA_PASS",
            fail_reason=r["iqa_fail_reason"],
            fail_label=_IQA_LABELS.get(r["iqa_fail_reason"] or "", r["iqa_fail_reason"]),
            scanned_at=r["scanned_at"].isoformat() if r["scanned_at"] else "",
            ocr_conf=f"{r['ocr_confidence']:.2f}" if r["ocr_confidence"] is not None else None,
            dpi=r["scan_dpi"],
        )
        for r in rows
    ]
    return IQAResultsResponse(bank_id=bank_id, items=items, total=len(items))


@router_v1.get("/outward/pipeline", response_model=OutwardPipelineResponse)
async def get_outward_pipeline(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> OutwardPipelineResponse:
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return OutwardPipelineResponse(bank_id=bank_id, instruments=[])
    try:
        rows = await db.fetch(
            """SELECT instrument_id, scan_id, payee_display, amount_range, outcome,
                      lot_id, branch_id, reject_reason, scanned_at
               FROM cts.outward_scan_events
               WHERE bank_id = $1
               ORDER BY scanned_at DESC
               LIMIT 200""",
            bank_id,
        )
    except Exception as exc:
        log.error("cts.outward_pipeline.query_failed", bank_id=bank_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable") from exc

    instruments = [
        OutwardPipelineInstrument(
            id=r["instrument_id"],
            stage=_OUTCOME_TO_STAGE.get(r["outcome"] or "", "SCANNED"),
            drawee="—",
            amount=r["amount_range"] or "—",
            lot=r["lot_id"],
            session_deadline=None,
            ocr_conf=None,
            iqa_fail=bool(r["reject_reason"]),
            cts_violation=(r["outcome"] == "CTS_REJECTED"),
            amount_mismatch=(r["outcome"] == "MISMATCH_HELD"),
            scanner=r["branch_id"],
        )
        for r in rows
    ]
    return OutwardPipelineResponse(bank_id=bank_id, instruments=instruments)
