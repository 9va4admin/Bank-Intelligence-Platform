"""
CTS API router — versioned public endpoints for cheque submission and decision retrieval.

Routes:
  POST /v1/cts/inward/{instrument_id}/submit   — trigger ChequeProcessingWorkflow
  GET  /v1/cts/decisions/{instrument_id}       — poll workflow status
  POST /v1/cts/review/{instrument_id}/decide   — ops_reviewer submits CONFIRM/RETURN signal
  GET  /v1/cts/queue                           — human review queue for ops workstation

All routes require JWT auth (bank_id extracted from token claim).
No business logic — delegates to Temporal workflow client.
"""
import time
from datetime import date, datetime, timezone
from typing import List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from apps.api.routers.cts_deps import (
    _safe_temporal_param,
    _VAULT_GAP_MAX_ROWS,
    _SCAN_LOG_MAX_ROWS,
    _ANALYTICS_TOP_N,
    _SMB_REPORTS_MAX_ROWS,
    _COMPLIANCE_MAX_ROWS,
    _NGCH_ROUTING_MAX_ROWS,
    _MICR_PREFIX_MAX_ROWS,
    get_current_user_context,
    get_current_bank_id,
    get_bank_id_scanner_or_user,
    get_current_user_id,
    get_temporal_client,
    get_kafka_producer,
)
from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
from modules.cts.workflows.human_review_workflow import ReviewDecision
from shared.auth.rbac import BankType, Role, PermissionLevel, RBACPolicy, UserContext
from shared.config.config_service import config_service
from shared.event_bus.producer import EventProducer as KafkaEventProducer
from shared.utils.masking import mask_amount

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

_policy = RBACPolicy()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChequeSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    account_number: str
    cheque_number: str
    presented_amount: float
    presented_payee: str
    iet_deadline: float   # Unix timestamp


class ChequeSubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    status: Literal["ACCEPTED"]
    estimated_decision_ms: int


class ChequeDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    workflow_status: str        # "RUNNING" | "STP_CONFIRM" | "STP_RETURN" | "HUMAN_REVIEW"
    decision: Optional[str] = None
    rationale: Optional[str] = None


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Literal["CONFIRM", "RETURN"]
    reason: str


class ReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    signal_sent: bool


class QueueItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    bank_id: str
    account_display: str          # masked: ****1234
    payee_display: str            # masked: N***
    amount_range: str             # ₹[1L-5L]
    clearing_zone: str
    received_at: float            # Unix timestamp
    iet_deadline: float           # Unix timestamp
    reason: str                   # VAULT_MISS | FRAUD_SCORE_HIGH | OCR_LOW_CONFIDENCE | ...
    fraud_score: Optional[float] = None
    ocr_confidence: Optional[float] = None
    sig_match_score: Optional[float] = None
    security_features: Optional[dict] = None   # {"void_pantograph": bool, "rupee_symbol": bool, ...}


class QueueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[QueueItem]
    total: int
    bank_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.post(
    "/inward/{instrument_id}/submit",
    response_model=ChequeSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_inward_cheque(
    instrument_id: str,
    body: ChequeSubmitRequest,
    request: Request,
    response: Response,
    bank_id: str = Depends(get_current_bank_id),
) -> ChequeSubmitResponse:
    """
    Publish inward cheque to Kafka cts.inward.{bank_id} (feeds KEDA autoscaler),
    then trigger ChequeProcessingWorkflow directly for low-latency path.
    Workflow ID is deterministic — submitting the same instrument_id twice is idempotent.
    """
    workflow_id = f"cts-{bank_id}-{instrument_id}"

    # Fetch bank-specific thresholds (Layer 3) so the workflow uses the
    # configured values instead of falling back to hardcoded literals.
    # Degrade gracefully — a config fetch failure must never block a cheque;
    # the workflow's own Field(default=...) values are the safe fallback.
    from shared.config.config_service import config_service
    cts_config: dict = {}
    try:
        cts_config = await config_service.get_workflow_thresholds(bank_id)
    except Exception as _cfg_exc:
        log.warning(
            "submit_inward.cts_config_fetch_failed",
            instrument_id=instrument_id,
            bank_id=bank_id,
            error=str(_cfg_exc),
        )

    workflow_input = ChequeWorkflowInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        image_url=body.image_url,
        account_number=body.account_number,
        cheque_number=body.cheque_number,
        presented_amount=body.presented_amount,
        presented_payee=body.presented_payee,
        iet_deadline=body.iet_deadline,
        cts_config=cts_config,
    )

    # Publish to Kafka cts.inward.{bank_id} so KEDA ScaledObject has a real lag
    # metric for autoscaling CTS workers. Fire-and-forget — Temporal is the
    # durability guarantee, not Kafka.
    kafka_producer: Optional[KafkaEventProducer] = get_kafka_producer(request)
    if kafka_producer is not None:
        try:
            kafka_producer.publish(
                topic=f"cts.inward.{bank_id}",
                event_type="CTS_INWARD_SUBMITTED",
                payload={
                    "instrument_id": instrument_id,
                    "workflow_id": workflow_id,
                    "iet_deadline": body.iet_deadline,
                },
                bank_id=bank_id,
            )
        except Exception as exc:
            # Kafka publish failure is non-fatal — Temporal is the primary path.
            # KEDA will scale conservatively until Kafka recovers.
            log.warning(
                "cts.kafka_publish_failed",
                instrument_id=instrument_id,
                bank_id=bank_id,
                error=str(exc),
            )

    temporal_client = getattr(request.app.state, "temporal_client", None)

    if temporal_client is not None:
        try:
            from datetime import timedelta as _td
            from temporalio.exceptions import WorkflowAlreadyStartedError
            from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

            await temporal_client.start_workflow(
                ChequeProcessingWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
                execution_timeout=_td(hours=4),  # IET window (3h) + 1h buffer; auto-terminates stuck workflows
            )
        except WorkflowAlreadyStartedError:
            pass  # idempotent — workflow already running for this instrument_id
        except Exception as exc:
            log.error(
                "cts.submit_workflow_error",
                instrument_id=instrument_id,
                bank_id=bank_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to start workflow",
            ) from exc

    log.info(
        "cts.submit_accepted",
        instrument_id=instrument_id,
        bank_id=bank_id,
        workflow_id=workflow_id,
    )

    response.headers["X-Workflow-Id"] = workflow_id
    return ChequeSubmitResponse(
        instrument_id=instrument_id,
        workflow_id=workflow_id,
        status="ACCEPTED",
        estimated_decision_ms=600,
    )


@router_v1.get(
    "/decisions/{instrument_id}",
    response_model=ChequeDecisionResponse,
)
async def get_decision(
    instrument_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ChequeDecisionResponse:
    """
    Poll status of a ChequeProcessingWorkflow.
    Returns current status — RUNNING until workflow completes.
    """
    workflow_id = f"cts-{bank_id}-{instrument_id}"

    temporal_client = getattr(request.app.state, "temporal_client", None)

    if temporal_client is not None:
        try:
            from temporalio.client import WorkflowExecutionStatus
            handle = temporal_client.get_workflow_handle(workflow_id)
            desc = await handle.describe()
            wf_status = desc.status

            if wf_status == WorkflowExecutionStatus.COMPLETED:
                result = await handle.result()
                return ChequeDecisionResponse(
                    instrument_id=instrument_id,
                    workflow_id=workflow_id,
                    workflow_status=result.decision,
                    decision=result.decision,
                    rationale=result.rationale,
                )
            elif wf_status in (
                WorkflowExecutionStatus.FAILED,
                WorkflowExecutionStatus.TERMINATED,
                WorkflowExecutionStatus.CANCELED,
                WorkflowExecutionStatus.TIMED_OUT,
            ):
                return ChequeDecisionResponse(
                    instrument_id=instrument_id,
                    workflow_id=workflow_id,
                    workflow_status="FAILED",
                    rationale=f"Workflow ended with status: {wf_status.name}",
                )
            else:
                return ChequeDecisionResponse(
                    instrument_id=instrument_id,
                    workflow_id=workflow_id,
                    workflow_status="RUNNING",
                )
        except Exception:
            pass

    return ChequeDecisionResponse(
        instrument_id=instrument_id,
        workflow_id=workflow_id,
        workflow_status="RUNNING",
    )


@router_v1.post(
    "/review/{instrument_id}/decide",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_review_decision(
    instrument_id: str,
    body: ReviewDecisionRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    reviewer_id: str = Depends(get_current_user_id),
) -> ReviewDecisionResponse:
    """
    ops_reviewer submits CONFIRM or RETURN decision.
    Sends a Temporal signal to HumanReviewWorkflow.
    Reason is mandatory — reviewer cannot submit without justification.
    """
    if not body.reason or not body.reason.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="reason is required for review decisions",
        )

    workflow_id = f"cts-humanreview-{bank_id}-{instrument_id}"
    decision = ReviewDecision(
        action=body.action,
        reason=body.reason.strip(),
        reviewer_id=reviewer_id,
        decided_at=time.time(),
    )

    temporal_client = getattr(request.app.state, "temporal_client", None)
    signal_sent = False

    if temporal_client is not None:
        try:
            from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow

            handle = temporal_client.get_workflow_handle(workflow_id)
            await handle.signal(HumanReviewWorkflow.receive_decision, decision)
            signal_sent = True
        except Exception as exc:
            log.error(
                "cts.review_signal_error",
                instrument_id=instrument_id,
                bank_id=bank_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to send review signal",
            ) from exc

    log.info(
        "cts.review_decision_submitted",
        instrument_id=instrument_id,
        bank_id=bank_id,
        action=body.action,
        reviewer_id=reviewer_id,
    )

    return ReviewDecisionResponse(
        instrument_id=instrument_id,
        workflow_id=workflow_id,
        signal_sent=signal_sent,
    )


@router_v1.get(
    "/queue",
    response_model=QueueResponse,
)
async def get_human_review_queue(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = 50,
) -> QueueResponse:
    """
    Return current human review queue for the ops workstation.
    Items are sorted by IET deadline ascending (most urgent first).
    When Temporal is unavailable, returns an empty queue rather than 503
    so the workstation can still load.

    Row-level isolation: SMB users see only their own instruments.
    smb_instrument_filter() returns (effective_bank_id, smb_id_filter).
    """
    if limit > 100:
        limit = 100

    policy = RBACPolicy()
    eff_bank_id, smb_id_filter = policy.smb_instrument_filter(ctx)

    temporal_client = getattr(request.app.state, "temporal_client", None)
    items: list[QueueItem] = []

    if temporal_client is not None:
        try:
            # Query Temporal for open HumanReviewWorkflow instances.
            # SMB users: add SmbId filter to enforce row-level isolation.
            # Validate params to prevent Temporal visibility query injection.
            safe_bank = _safe_temporal_param(eff_bank_id, "bank_id")
            query = (
                f"WorkflowType = 'HumanReviewWorkflow' "
                f"AND ExecutionStatus = 'Running' "
                f"AND BankId = '{safe_bank}'"
            )
            if smb_id_filter:
                safe_smb = _safe_temporal_param(smb_id_filter, "smb_id")
                query += f" AND SmbId = '{safe_smb}'"

            async for wf in temporal_client.list_workflows(query=query, page_size=limit):
                memo = wf.memo or {}
                items.append(QueueItem(
                    instrument_id=memo.get("instrument_id", wf.id.split("-")[-1]),
                    workflow_id=wf.id,
                    bank_id=eff_bank_id,
                    account_display=memo.get("account_display", "****????"),
                    payee_display=memo.get("payee_display", "?***"),
                    amount_range=memo.get("amount_range", "₹[unknown]"),
                    clearing_zone=memo.get("clearing_zone", "UNKNOWN"),
                    received_at=memo.get("received_at", wf.start_time.timestamp() if wf.start_time else 0.0),
                    iet_deadline=memo.get("iet_deadline", 0.0),
                    reason=memo.get("reason", "UNKNOWN"),
                    fraud_score=memo.get("fraud_score"),
                    ocr_confidence=memo.get("ocr_confidence"),
                    sig_match_score=memo.get("sig_match_score"),
                    security_features=memo.get("security_features"),
                ))
        except Exception as exc:
            log.warning("cts.queue_fetch_error", bank_id=eff_bank_id, error=str(exc))

    # Sort by IET deadline ascending — most urgent first
    items.sort(key=lambda x: x.iet_deadline)

    log.info("cts.queue_fetched", bank_id=eff_bank_id, smb_filter=smb_id_filter, count=len(items))

    return QueueResponse(items=items, total=len(items), bank_id=eff_bank_id)


# ---------------------------------------------------------------------------
# Cheque search (global search bar)
# ---------------------------------------------------------------------------

class DecisionLogItem(BaseModel):
    """One row from cts.agent_decisions, joined with cts.cheque_instruments.
    All PII fields are masked — no raw account numbers or amounts in response.
    """
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    decision: str                   # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW
    decision_reason: str
    fraud_score: float
    shap_values: dict
    processing_duration_ms: int
    iet_margin_seconds: int
    degraded_mode: bool
    created_at: float               # Unix timestamp
    ocr_engines_used: list[str] = []
    indic_ocr_kill_switch_active: bool = False
    signature_match_score: float = 0.0
    signature_verdict: str = "UNKNOWN"
    pps_verdict: str = "NOT_CHECKED"
    cbs_balance_status: str = "NOT_CHECKED"
    alteration_detected: bool = False
    # From cheque_instruments JOIN — may be None if instrument not yet written
    micr_code: Optional[str] = None
    account_display: Optional[str] = None   # ****last4
    amount_range: Optional[str] = None
    presenting_ifsc: Optional[str] = None


class DecisionLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[DecisionLogItem]
    total: int
    bank_id: str


@router_v1.get(
    "/decisions",
    response_model=DecisionLogResponse,
)
async def list_decisions(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    limit: int = 50,
) -> DecisionLogResponse:
    """
    List recent CTS agent decisions for the ops workstation CTSDecisionsLog page.
    Queries cts.agent_decisions LEFT JOIN cts.cheque_instruments.
    Results ordered by created_at DESC (most recent first).
    Explicit column list — no SELECT * on PII tables.
    Returns empty list when db_pool_cts is unavailable (dev mode, worker not started).
    """
    import json as _json

    if limit > 100:
        limit = 100

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    items: list[DecisionLogItem] = []

    if db_pool is not None:
        _SQL = """
            SELECT
                d.instrument_id,
                d.workflow_id,
                d.decision,
                d.decision_reason,
                d.fraud_score,
                d.shap_values,
                d.processing_duration_ms,
                d.iet_margin_seconds,
                d.degraded_mode,
                EXTRACT(EPOCH FROM d.created_at) AS created_at_epoch,
                d.ocr_engines_used,
                d.indic_ocr_kill_switch_active,
                d.signature_match_score,
                d.signature_verdict,
                d.pps_verdict,
                d.cbs_balance_status,
                d.alteration_detected,
                i.micr_code,
                i.account_last4,
                i.amount_range,
                i.presenting_ifsc
            FROM cts.agent_decisions d
            LEFT JOIN cts.cheque_instruments i
                   ON i.instrument_id = d.instrument_id
                  AND i.bank_id = d.bank_id
            WHERE d.bank_id = $1
            ORDER BY d.created_at DESC
            LIMIT $2
        """.strip()
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(_SQL, bank_id, limit)
            for row in rows:
                shap = row["shap_values"]
                if isinstance(shap, str):
                    shap = _json.loads(shap)
                ocr_engines = row["ocr_engines_used"] or []
                if isinstance(ocr_engines, str):
                    ocr_engines = _json.loads(ocr_engines)
                account_last4 = row["account_last4"]
                items.append(DecisionLogItem(
                    instrument_id=row["instrument_id"],
                    workflow_id=row["workflow_id"],
                    decision=row["decision"],
                    decision_reason=row["decision_reason"] or "",
                    fraud_score=float(row["fraud_score"] or 0.0),
                    shap_values=shap or {},
                    processing_duration_ms=int(row["processing_duration_ms"] or 0),
                    iet_margin_seconds=int(row["iet_margin_seconds"] or 0),
                    degraded_mode=bool(row["degraded_mode"]),
                    created_at=float(row["created_at_epoch"] or 0.0),
                    ocr_engines_used=ocr_engines,
                    indic_ocr_kill_switch_active=bool(row["indic_ocr_kill_switch_active"]),
                    signature_match_score=float(row["signature_match_score"] or 0.0),
                    signature_verdict=row["signature_verdict"] or "UNKNOWN",
                    pps_verdict=row["pps_verdict"] or "NOT_CHECKED",
                    cbs_balance_status=row["cbs_balance_status"] or "NOT_CHECKED",
                    alteration_detected=bool(row["alteration_detected"]),
                    micr_code=row["micr_code"],
                    account_display=f"****{account_last4}" if account_last4 else None,
                    amount_range=row["amount_range"],
                    presenting_ifsc=row["presenting_ifsc"],
                ))
        except Exception as exc:
            log.warning("cts.decisions_list_error", bank_id=bank_id, error=str(exc))

    log.info("cts.decisions_list", bank_id=bank_id, count=len(items))
    return DecisionLogResponse(items=items, total=len(items), bank_id=bank_id)


# ── Vault Gap Report ────────────────────────────────────────────────────────
# After banking hours, ops team uses this to see which accounts presented
# cheques without a signature in vault → trigger enrollment overnight.

class VaultGapAccount(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_display: str         # ****4521
    instrument_count: int
    instrument_ids: list[str]
    micr_codes: list[Optional[str]]
    first_seen_at: float         # Unix epoch
    last_seen_at: float


class VaultGapResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    bank_id: str
    total_accounts_affected: int
    total_instruments: int
    gaps: list[VaultGapAccount]


@router_v1.get("/vault-gaps", response_model=VaultGapResponse)
async def get_vault_gaps(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    date: Optional[str] = None,   # YYYY-MM-DD; defaults to today
) -> VaultGapResponse:
    """
    Post-banking-hours report: accounts that presented cheques but have no
    signature in vault. Ops team uses this to drive overnight enrollment.

    Queries cts.agent_decisions for HUMAN_REVIEW rows where decision_reason
    contains 'NO_SIGNATURE_IN_VAULT', grouped by account_last4 for the
    specified clearing date (today by default).

    Returns at most 200 gap accounts — sufficient for any single clearing session.
    """
    import json as _json
    from datetime import date as _date

    session_date = date or _date.today().isoformat()

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    gaps: list[VaultGapAccount] = []

    if db_pool is not None:
        _SQL = """
            SELECT
                i.account_last4,
                d.instrument_id,
                d.decision_reason,
                i.micr_code,
                EXTRACT(EPOCH FROM d.created_at) AS created_at_epoch
            FROM cts.agent_decisions d
            LEFT JOIN cts.cheque_instruments i
                   ON i.instrument_id = d.instrument_id
                  AND i.bank_id = d.bank_id
            WHERE d.bank_id = $1
              AND d.decision = 'HUMAN_REVIEW'
              AND d.decision_reason ILIKE '%NO_SIGNATURE_IN_VAULT%'
              AND d.created_at::date = $2::date
            ORDER BY i.account_last4, d.created_at ASC
            LIMIT {_VAULT_GAP_MAX_ROWS}
        """.strip()

        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(_SQL, bank_id, session_date)

            # Group by account_last4
            grouped: dict[str, dict] = {}
            for row in rows:
                key = row["account_last4"] or "UNKNOWN"
                display = f"****{key}" if key != "UNKNOWN" else "****????"
                if key not in grouped:
                    grouped[key] = {
                        "account_display": display,
                        "instrument_ids": [],
                        "micr_codes": [],
                        "first_seen_at": float(row["created_at_epoch"] or 0.0),
                        "last_seen_at": float(row["created_at_epoch"] or 0.0),
                    }
                g = grouped[key]
                g["instrument_ids"].append(row["instrument_id"])
                g["micr_codes"].append(row["micr_code"])
                g["last_seen_at"] = max(g["last_seen_at"], float(row["created_at_epoch"] or 0.0))

            for g in list(grouped.values())[:200]:
                gaps.append(VaultGapAccount(
                    account_display=g["account_display"],
                    instrument_count=len(g["instrument_ids"]),
                    instrument_ids=g["instrument_ids"],
                    micr_codes=g["micr_codes"],
                    first_seen_at=g["first_seen_at"],
                    last_seen_at=g["last_seen_at"],
                ))
        except Exception as exc:
            log.warning("cts.vault_gaps_error", bank_id=bank_id, error=str(exc))

    total_instruments = sum(g.instrument_count for g in gaps)
    log.info("cts.vault_gaps", bank_id=bank_id, date=session_date,
             accounts=len(gaps), instruments=total_instruments)
    return VaultGapResponse(
        date=session_date,
        bank_id=bank_id,
        total_accounts_affected=len(gaps),
        total_instruments=total_instruments,
        gaps=gaps,
    )


class ChequeSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    cheque_number: str
    account_display: str    # masked ****1234
    payee_display: str      # masked N***
    amount_range: str       # ₹[1L-5L]
    status: str             # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW | RUNNING
    clearing_zone: str
    received_at: float      # Unix timestamp
    fraud_score: Optional[float] = None
    ocr_confidence: Optional[float] = None


class ChequeSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    results: list[ChequeSearchResult]
    total: int
    bank_id: str


@router_v1.get(
    "/instruments/search",
    response_model=ChequeSearchResponse,
)
async def search_instruments(
    q: str,
    bank_id: str = Depends(get_current_bank_id),
    limit: int = 8,
) -> ChequeSearchResponse:
    """
    Typeahead search by cheque number, instrument ID, or masked account suffix.
    Minimum query length enforced at 3 chars.
    Returns masked fields only — no raw PII in search results.
    """
    if len(q.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query must be at least 3 characters",
        )
    if limit > 20:
        limit = 20

    log.info("cts.instrument_search", bank_id=bank_id, query_len=len(q))
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return ChequeSearchResponse(results=[], total=0, bank_id=bank_id)
    try:
        return await _instrument_search(bank_id, q.strip(), limit, db)
    except Exception as exc:
        log.error("cts.instrument_search.query_failed", bank_id=bank_id, error=str(exc))
        return ChequeSearchResponse(results=[], total=0, bank_id=bank_id)


# [MOVED to cts_admin_ops.py — Step 1f]
# get_instrument_digest  → GET  /v1/cts/instruments/{instrument_id}/digest
# trigger_workflow_cleanup → POST /v1/cts/admin/workflows/cleanup


# [MOVED to cts_vault_ops.py — Step 1e]
# get_vault_sync_status → GET /v1/cts/vault-sync/status
# trigger_vault_sync   → POST /v1/cts/vault-sync/trigger


# [MOVED to cts_admin_ops.py — Step 1f]
# list_schedules   → GET   /v1/cts/schedules
# update_schedule  → PATCH /v1/cts/schedules/{schedule_id}
# pause_schedule   → POST  /v1/cts/schedules/{schedule_id}/pause
# resume_schedule  → POST  /v1/cts/schedules/{schedule_id}/resume


# ---------------------------------------------------------------------------
# [SMB models and routes moved to cts_smb.py]

# [SMB route handlers moved to cts_smb.py]


# ---------------------------------------------------------------------------
# Outward scan — /v1/cts/outward/scan/upload-url
# Called by the local scanner agent BEFORE submit to obtain presigned MinIO PUT
# URLs for direct image upload from the teller PC. The agent never touches the
# MinIO credentials — presigned URLs are scoped to exactly one object for 5 min.
# ---------------------------------------------------------------------------

_CTS_IMAGES_BUCKET = "cts-images"
_UPLOAD_URL_EXPIRY_SECONDS = 300


class ScanUploadURLRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    include_uv: bool = False  # True when scanner has UV lamp (CR-120 UV model)


class ScanUploadURLResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    front_presigned_url: str
    rear_presigned_url: str
    front_object_url: str            # s3://... passed back as-is in submit request
    rear_object_url: str
    uv_presigned_url: Optional[str] = None   # only when include_uv=True
    uv_object_url: Optional[str] = None
    expires_at: int                  # Unix timestamp


# [MOVED to cts_outward_core.py — Step 1h]
# request_scan_upload_urls → POST /v1/cts/outward/scan/upload-url
# ---------------------------------------------------------------------------
# Outward scan — /v1/cts/outward/scan/image
# Returns a short-lived presigned GET URL for a scan image in MinIO.
# Used by the browser to display BFB/BBB/BFG scan views without exposing
# MinIO credentials. scan_id is instrument_id with "INS-" prefix stripped.
# ---------------------------------------------------------------------------

# [MOVED to cts_outward_core.py — Step 1h]
# get_scan_image_url → GET /v1/cts/outward/scan/image
# ---------------------------------------------------------------------------
# Outward scan — /v1/cts/outward/scan/submit
# Called by the local scanner agent (edge/cts-scanner-agent/) running on the
# teller PC after it has uploaded images to MinIO and extracted hardware MICR.
# ---------------------------------------------------------------------------

class OutwardScanSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str                    # generated by scanner agent: SCAN-{date}-{uuid8}
    instrument_id: str              # pre-assigned by scanner agent: INS-{scan_id}
    bank_ifsc: str                  # teller's branch IFSC — determines lot assignment zone
    session_id: str                 # clearing session open on this teller terminal

    image_front_url: str            # s3://cts-images/{bank_id}/outward/{scan_id}/front.tiff
    image_rear_url: str             # s3://cts-images/{bank_id}/outward/{scan_id}/rear.tiff

    cheque_number: str = ""

    # CTS-2010 image metrics (populated by scanner agent from OEM SDK callback)
    front_dpi: Optional[int] = None
    rear_dpi: Optional[int] = None
    front_colour_depth: Optional[int] = None
    rear_colour_depth: Optional[int] = None
    front_file_size_kb: Optional[float] = None
    rear_file_size_kb: Optional[float] = None

    # Hardware MICR from Ranger Transport API TransportGetMICR() — present on CR-120 path.
    # When provided, OutwardScanWorkflow skips GOT-OCR2 and uses a single Qwen2-VL call.
    micr_hardware_raw: Optional[str] = None

    # UV wavelength image — set when scanner has UV lamp (CR-120 UV model) and
    # enable_uv_scan=true in config.ini. Passed to OutwardScanWorkflow for
    # security feature verification. Optional and additive (non-breaking).
    image_uv_url: Optional[str] = None

    pu_id: Optional[str] = None     # processing unit identifier (multi-PU teller desks)
    branch_id: Optional[str] = None


class OutwardScanSubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    instrument_id: str
    workflow_id: str
    status: Literal["ACCEPTED"]
    path: str                       # "CR120" | "LEGACY" — which pipeline was selected


# [MOVED to cts_outward_core.py — Step 1h]
# submit_outward_scan → POST /v1/cts/outward/scan/submit
# [MOVED to cts_admin_ops.py — Step 1f]
# list_ifsc_registry  → GET    /v1/cts/ifsc-registry
# get_ifsc_by_id      → GET    /v1/cts/ifsc-registry/{entry_id}
# create_ifsc         → POST   /v1/cts/ifsc-registry
# approve_ifsc        → PUT    /v1/cts/ifsc-registry/{entry_id}/approve
# deactivate_ifsc     → DELETE /v1/cts/ifsc-registry/{entry_id}


# [MOVED to cts_holds.py — Step 1c]
# place_hold              → POST /v1/cts/holds/{instrument_id}
# list_holds              → GET  /v1/cts/holds
# release_hold            → POST /v1/cts/holds/{instrument_id}/release
# submit_hold_recommendation → POST /v1/cts/holds/{instrument_id}/recommendation
# list_mismatches         → GET  /v1/cts/mismatches
# resolve_mismatch        → POST /v1/cts/mismatches/{mismatch_id}/resolve


# [MOVED to cts_outward_data.py -- Step 1g]
# EndorsementBatchRequest, EndorsementBatchResponse
# endorse_batch -- POST /v1/cts/endorsement/batch

# [MOVED to cts_outward_data.py -- Step 1g]
# OutwardFileDownloadResponse
# get_outward_file_download_url -- GET /v1/cts/outward/files/{filename}/download-url

# [MOVED to cts_outward_data.py -- Step 1g]
# IQARescanResponse
# trigger_iqa_rescan -- POST /v1/cts/iqa/{scan_id}/rescan

# [MOVED to cts_outward_data.py -- Step 1g]
# SessionDownloadResponse
# get_session_report_download_url -- GET /v1/cts/sessions/{session_id}/download/{report_type}
# ─── Branch Scan Monitor — recent outward scan events ─────────────────────────

# [MOVED to cts_scanner.py — Step 1d]
# ScanEventItem, ScanMonitorResponse, get_recent_scan_events → GET /v1/cts/scan-monitor/recent


# [MOVED to cts_holds.py — Step 1c]
# claim_instrument    → POST /v1/cts/review/{instrument_id}/claim
# unclaim_instrument  → DELETE /v1/cts/review/{instrument_id}/claim
# get_allocation_status → GET /v1/cts/allocation/status


# ── Hub Summary + Scanning Batch Lot Management ────────────────────────────────
#
# Hub dashboard for CTSHubDashboard in POC/PROD mode.
#
# Data sources:
#   cts.branches          — branch master
#   cts.eeh_sessions      — today's ACTIVE scanning session per branch
#   cts.scanner_registrations — scanner hardware health
#   cts.lots              — scanning batch lots (OPEN/SEALED, max 25 per lot)
#
# Lot lifecycle (server-managed):
#   scan submitted → _ensure_open_lot() → increment instrument_count
#   instrument_count == max_instruments → auto-seal → create next lot
#   Hub Manager → PATCH /v1/cts/outward/lots/{lot_id}/seal (manual early seal)
#   Window close → POST /v1/cts/outward/lots/seal-all
#
# Allowed roles: bank_it_admin, platform_admin, ops_manager
# ─────────────────────────────────────────────────────────────────────────────

_HUB_READ_ROLES  = {"bank_it_admin", "platform_admin", "ops_manager"}
_HUB_WRITE_ROLES = {"bank_it_admin", "platform_admin", "ops_manager"}

_HUB_SUMMARY_SQL = """
    SELECT
        b.branch_id,
        b.branch_name,
        b.branch_ifsc,
        COALESCE(s.hub_type, 'EEH')         AS hub_type,
        COALESCE(r.health, 'UNKNOWN')        AS scanner_health,
        s.session_id,
        s.status                             AS session_status,
        s.opened_at,
        s.total_uploaded,
        s.total_accepted,
        s.total_rejected,
        COALESCE(s.total_held, 0)            AS total_held,
        cl.lot_id                            AS current_lot_id,
        cl.instrument_count                  AS current_lot_filled,
        cl.max_instruments                   AS current_lot_max,
        cl.status                            AS current_lot_status,
        COALESCE(sl.sealed_count, 0)         AS lots_sealed_today
    FROM cts.branches b
    LEFT JOIN cts.eeh_sessions s
        ON  s.branch_id     = b.branch_id
        AND s.clearing_date = $2
        AND s.status        = 'ACTIVE'
    LEFT JOIN cts.scanner_registrations r
        ON  r.branch_id = b.branch_id
        AND r.bank_id   = $1
        AND r.is_active = true
    LEFT JOIN cts.lots cl
        ON  cl.branch_id     = b.branch_id
        AND cl.clearing_date = $2
        AND cl.status        = 'OPEN'
    LEFT JOIN (
        SELECT branch_id, COUNT(*) AS sealed_count
        FROM cts.lots
        WHERE bank_id = $1 AND clearing_date = $2 AND status = 'SEALED'
        GROUP BY branch_id
    ) sl ON sl.branch_id = b.branch_id
    WHERE b.bank_id = $1
    ORDER BY b.branch_id
"""


class LotInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_id: str
    filled: int
    max:    int
    status: str


class BranchSessionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id:      str
    status:          str
    opened_at:       str
    total_uploaded:  int
    total_accepted:  int
    total_rejected:  int
    total_held:      int = 0


class BranchSessionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id:         str
    branch_name:       str
    branch_ifsc:       str
    hub_type:          str
    scanner_health:    str
    session:           Optional[BranchSessionInfo]
    current_lot:       Optional[LotInfo] = None
    lots_sealed_today: int = 0


class HubSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id:         str
    clearing_date:   str
    branches:        list[BranchSessionSummary]
    total_branches:  int
    active_sessions: int
    generated_at:    str


def _row_to_branch_summary(row: dict) -> BranchSessionSummary:
    session = None
    if row.get("session_id") is not None:
        opened = row["opened_at"]
        opened_str = opened.isoformat() if hasattr(opened, "isoformat") else str(opened)
        session = BranchSessionInfo(
            session_id=row["session_id"],
            status=row["session_status"] or "ACTIVE",
            opened_at=opened_str,
            total_uploaded=row["total_uploaded"] or 0,
            total_accepted=row["total_accepted"] or 0,
            total_rejected=row["total_rejected"] or 0,
            total_held=row.get("total_held") or 0,
        )
    current_lot = None
    if row.get("current_lot_id") is not None:
        current_lot = LotInfo(
            lot_id=row["current_lot_id"],
            filled=row["current_lot_filled"] or 0,
            max=row["current_lot_max"] or 25,
            status=row["current_lot_status"] or "OPEN",
        )
    return BranchSessionSummary(
        branch_id=row["branch_id"],
        branch_name=row["branch_name"],
        branch_ifsc=row["branch_ifsc"],
        hub_type=row.get("hub_type") or "EEH",
        scanner_health=row.get("scanner_health") or "UNKNOWN",
        session=session,
        current_lot=current_lot,
        lots_sealed_today=row.get("lots_sealed_today") or 0,
    )


async def _ensure_open_lot(
    conn,
    bank_id: str,
    branch_id: str,
    session_id: str,
    clearing_date,
    max_instruments: int = 25,
) -> tuple[str, int]:
    """
    Find or create the OPEN scanning batch lot for this branch today.
    If the current lot is full, auto-seals it and opens the next one.
    Returns (lot_id, new_instrument_count).
    """
    row = await conn.fetchrow(
        "SELECT lot_id, instrument_count, max_instruments "
        "FROM cts.lots "
        "WHERE branch_id = $1 AND clearing_date = $2 AND status = 'OPEN'",
        branch_id, clearing_date,
    )

    if row is None:
        # No open lot — create lot #(max_seq + 1)
        seq_row = await conn.fetchrow(
            "SELECT COALESCE(MAX(sequence_number), 0) AS max_seq "
            "FROM cts.lots WHERE branch_id = $1 AND clearing_date = $2",
            branch_id, clearing_date,
        )
        seq = (seq_row["max_seq"] or 0) + 1
        date_str = clearing_date.strftime("%Y%m%d") if hasattr(clearing_date, "strftime") else str(clearing_date).replace("-", "")
        lot_id = f"LOT-{branch_id}-{date_str}-{seq:04d}"
        await conn.execute(
            "INSERT INTO cts.lots "
            "(lot_id, bank_id, branch_id, session_id, clearing_date, sequence_number, "
            " status, instrument_count, max_instruments) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'OPEN', 1, $7)",
            lot_id, bank_id, branch_id, session_id, clearing_date, seq, max_instruments,
        )
        return lot_id, 1

    lot_id = row["lot_id"]
    new_count = row["instrument_count"] + 1

    if new_count >= row["max_instruments"]:
        # Lot full — seal it, then recurse to create the next one
        await conn.execute(
            "UPDATE cts.lots SET status='SEALED', instrument_count=$1, sealed_at=NOW() "
            "WHERE lot_id=$2",
            new_count, lot_id,
        )
        return await _ensure_open_lot(conn, bank_id, branch_id, session_id, clearing_date, max_instruments)

    await conn.execute(
        "UPDATE cts.lots SET instrument_count=$1 WHERE lot_id=$2",
        new_count, lot_id,
    )
    return lot_id, new_count


# [MOVED to cts_outward_core.py — Step 1h]
# get_hub_summary → GET /v1/cts/outward/hub-summary
# [MOVED to cts_outward_core.py — Step 1h]
# seal_lot → PATCH /v1/cts/outward/lots/{lot_id}/seal
# [MOVED to cts_outward_core.py — Step 1h]
# seal_all_lots → POST /v1/cts/outward/lots/seal-all
# ── Session Report ─────────────────────────────────────────────────────────────

class SessionReportMeta(BaseModel):
    model_config = ConfigDict(frozen=True)
    report_id:        str
    session_id:       str
    bank_id:          str
    branch_ifsc:      str
    clearing_date:    str
    session_type:     str
    generated_at:     str
    instrument_count: int
    accepted_count:   int
    rejected_count:   int
    held_count:       int
    compliance_pass_count: int
    compliance_fail_count: int
    status:           str
    html_url:         Optional[str] = None
    pdf_url:          Optional[str] = None


# [MOVED to cts_outward_core.py — Step 1h]
# get_session_report → GET /v1/cts/outward/sessions/{session_id}/report
# ---------------------------------------------------------------------------
# Vault Upload — UI path
# POST /v1/cts/vault/upload/{vault_type}
# GET  /v1/cts/vault/batches/{batch_id}
# GET  /v1/cts/vault/batches/{batch_id}/errors.csv
# ---------------------------------------------------------------------------

import csv as _csv
import io as _io
from fastapi import UploadFile, File
from fastapi.responses import RedirectResponse, StreamingResponse

_VAULT_TABLE_MAP: dict[str, str] = {
    "PPS":            "cts.pps_vault_entries",
    "CHEQUE_BOOK":    "cts.cheque_books",
    "LEAF_STATUS":    "cts.cheque_leaves",
    "ACCOUNT_DETAIL": "cts.account_vault_detail",
    "SIGNATURE":      "cts.account_signatories",
}

_VALID_VAULT_TYPES = frozenset(_VAULT_TABLE_MAP)


class VaultUploadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    vault_type: str
    db_table: str
    status: str          # COMPLETE | PARTIAL | FAILED
    rows_total: int
    rows_processed: int
    rows_failed: int
    errors_preview: list[dict]   # first 20 inline; full list → /errors.csv


class VaultBatchStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    bank_id: str
    vault_type: str
    db_table: str
    filename: Optional[str]
    upload_channel: str
    uploaded_by: str
    status: str
    rows_total: int
    rows_processed: int
    rows_failed: int
    errors_preview: list[dict]   # first 20 from stored errors_json
    error_file_path: Optional[str]   # MinIO object key; None when clean batch or MinIO unavailable
    has_error_file: bool             # convenience flag for UI download button
    created_at: float
    completed_at: Optional[float]


def _vault_status(rows_processed: int, rows_failed: int) -> str:
    if rows_processed == 0 and rows_failed > 0:
        return "FAILED"
    if rows_failed > 0:
        return "PARTIAL"
    return "COMPLETE"


def _publish_vault_batch_event(
    kafka_producer,
    *,
    batch_id: str,
    bank_id: str,
    vault_type: str,
    status: str,
    rows_total: int,
    rows_processed: int,
    rows_failed: int,
) -> None:
    """Emit Kafka event on PARTIAL or FAILED batch → PlatformHealthCheckWorkflow → dispatcher → alert."""
    if kafka_producer is None or rows_failed == 0:
        return
    event_type = "VAULT_BATCH_FAILED" if rows_processed == 0 else "VAULT_BATCH_PARTIAL"
    try:
        kafka_producer.publish(
            topic="platform.audit.events",
            event_type=event_type,
            payload={
                "batch_id": batch_id,
                "vault_type": vault_type,
                "db_table": _VAULT_TABLE_MAP.get(vault_type, "unknown"),
                "bank_id": bank_id,
                "rows_total": rows_total,
                "rows_processed": rows_processed,
                "rows_failed": rows_failed,
            },
            bank_id=bank_id,
        )
        log.warning(
            "vault.batch_alert_emitted",
            batch_id=batch_id,
            bank_id=bank_id,
            vault_type=vault_type,
            event_type=event_type,
            rows_failed=rows_failed,
        )
    except Exception as exc:
        log.error("vault.batch_alert_publish_failed", batch_id=batch_id, error=str(exc))


# [MOVED to cts_outward_core.py — Step 1h]
# upload_vault_csv → POST /v1/cts/vault/upload/{vault_type}
# [MOVED to cts_outward_core.py — Step 1h]
# get_vault_batch_status → GET /v1/cts/vault/batches/{batch_id}
# [MOVED to cts_outward_core.py — Step 1h]
# download_vault_batch_errors → GET /v1/cts/vault/batches/{batch_id}/errors.csv
# ---------------------------------------------------------------------------
# Outward scan events — branch scanner agent reporting + Branch Scan Dashboard
# ---------------------------------------------------------------------------

# [MOVED to cts_scanner.py — Step 1d]
# OutwardScanEventRequest/Response, ScanSessionItem, ScanSessionLogResponse


# [MOVED to cts_scanner.py — Step 1d]
# report_outward_scan_event → POST /v1/cts/outward/scan/event


# [MOVED to cts_scanner.py — Step 1d]
# get_scan_session_log → GET /v1/cts/outward/session/{session_id}/scan-log


# [MOVED to cts_scanner.py — Step 1d]
# list_outward_scan_events → GET /v1/cts/outward/scan-events


# [MOVED to cts_scanner.py — Step 1d]
# generate_scanner_registration_code → POST /v1/cts/admin/scanner/registration-code


# [MOVED to cts_scanner.py — Step 1d]
# register_scanner → POST /v1/cts/admin/scanner/register


# ===========================================================================
# OUTWARD WIRING SPRINT — all gaps wired below
# ===========================================================================

# ---------------------------------------------------------------------------
# B1 — Scanner session open / close
# ---------------------------------------------------------------------------

class ScannerSessionOpenRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id: str
    hub_type: str = "EEH"
    cert_fingerprint: str


class ScannerSessionOpenResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    branch_id: str
    bank_id: str
    hub_type: str
    status: Literal["ACTIVE"]
    clearing_date: str
    opened_at: str


class ScannerSessionCloseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str


class ScannerSessionCloseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    status: Literal["CLOSED"]
    closed_at: str


_SESSION_OPEN_ROLES = {"ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager"}


# [MOVED to cts_outward_core.py — Step 1h]
# open_scanner_session → POST /v1/cts/outward/scanner/session/open
# [MOVED to cts_outward_core.py — Step 1h]
# close_scanner_session → POST /v1/cts/outward/scanner/session/close
# ---------------------------------------------------------------------------
# B2 — Trigger ClearingSessionWorkflow (Hub Manager "Submit to NGCH")
# ---------------------------------------------------------------------------

class ClearingSessionSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    clearing_date: str               # ISO date YYYY-MM-DD
    session_type: str = "MORNING"    # MORNING | AFTERNOON | EVENING
    deployment_mode: str = "SB_NGCH"
    pu_ids: list[str] = []           # empty = all PUs for this bank


class ClearingSessionSubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    bank_id: str
    clearing_date: str
    session_type: str
    status: Literal["STARTED"]
    message: str


_HUB_SUBMIT_ROLES = {"ops_manager", "bank_it_admin"}


# [MOVED to cts_outward_core.py — Step 1h]
# submit_clearing_session → POST /v1/cts/outward/clearing-session/submit
# ---------------------------------------------------------------------------
# B3 — Clearing window schedule (Hub Dashboard countdown)
# ---------------------------------------------------------------------------

class ClearingWindowResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    open_time_utc: str      # HH:MM
    close_time_utc: str     # HH:MM
    clearing_date: str      # ISO date
    is_open: bool


# [MOVED to cts_outward_core.py — Step 1h]
# get_clearing_window → GET /v1/cts/outward/clearing-window
# ---------------------------------------------------------------------------
# B4 — Outward human-review queue + decision signal
# [MOVED to cts_outward_data.py -- Step 1g]
# OutwardQueueItem, OutwardQueueResponse
# OutwardReviewDecisionRequest, OutwardReviewDecisionResponse
# get_outward_human_review_queue -- GET /v1/cts/outward/human-review-queue
# decide_outward_review -- POST /v1/cts/outward/review/{instrument_id}/decide

# [MOVED to cts_outward_data.py -- Step 1g]
# SessionSettlementRow, SettlementResponse
# get_outward_settlement -- GET /v1/cts/outward/settlement
# [SMB helper functions moved to cts_smb.py]


# ---------------------------------------------------------------------------
# B7 — Instrument search real query
# ---------------------------------------------------------------------------

async def _instrument_search(bank_id: str, q: str, limit: int, db) -> ChequeSearchResponse:
    """Real DB query for instrument typeahead."""
    rows = await db.fetch(
        """
        SELECT instrument_id, cheque_number, account_display, payee_display,
               amount_range, status, clearing_zone, received_at::text,
               fraud_score, ocr_confidence
        FROM cts.cheque_instruments
        WHERE bank_id = $1
          AND (cheque_number ILIKE $2 OR instrument_id ILIKE $2 OR account_display ILIKE $2)
        ORDER BY received_at DESC
        LIMIT $3
        """,
        bank_id, f"%{q}%", limit,
    )
    results = [
        ChequeSearchResult(
            instrument_id=r["instrument_id"],
            cheque_number=r["cheque_number"] or "",
            account_display=r["account_display"] or "****",
            payee_display=r["payee_display"] or "",
            amount_range=r["amount_range"] or "",
            status=r["status"],
            clearing_zone=r["clearing_zone"],
            received_at=r["received_at"],
            fraud_score=r["fraud_score"],
            ocr_confidence=r["ocr_confidence"],
        )
        for r in rows
    ]
    return ChequeSearchResponse(results=results, total=len(results), bank_id=bank_id)


# [MOVED to cts_outward_data.py -- Step 1g]
# LotInstrumentRow, LotInstrumentsResponse
# get_lot_instruments -- GET /v1/cts/outward/lots/{lot_id}/instruments

# [MOVED to cts_outward_data.py -- Step 1g]
# DailyAnalyticsRow, DailyAnalyticsResponse
# get_outward_analytics_daily -- GET /v1/cts/outward/analytics/daily

# ---------------------------------------------------------------------------
# B10 — GET /v1/cts/inward/analytics
# Aggregates from cts.agent_decisions for the Analytics page inward metrics:
# daily throughput + AI confidence, fraud score distribution, risk flags,
# return reasons, branch breakdown, and IET near-breach trend.
# ---------------------------------------------------------------------------

class InwardDailyRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    total: int
    stp_confirm: int
    stp_return: int
    human_review: int
    avg_ms: float
    ocr_conf: Optional[float]
    sig_prec: Optional[float]


class FraudDistRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    range: str
    count: int


class RiskFlagRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    flag: str
    count: int


class ReturnReasonRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    reason: str
    count: int


class BranchRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch: str
    processed: int
    hrq_pct: float
    vault_miss: int
    avg_ms: float
    returns: int


class IETTrendRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    nearBreach: int


class InwardAnalyticsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    days: int
    daily: list[InwardDailyRow]
    fraud_dist: list[FraudDistRow]
    risk_flags: list[RiskFlagRow]
    return_reasons: list[ReturnReasonRow]
    branches: list[BranchRow]
    iet_trend: list[IETTrendRow]


_INWARD_ANALYTICS_READ_ROLES = {
    Role.OPS_MANAGER, Role.FRAUD_ANALYST, Role.BANK_IT_ADMIN,
    Role.OPS_REVIEWER, Role.COMPLIANCE_OFFICER,
}

_FRAUD_DIST_COLORS = {
    "0–10":   "#10b981",
    "10–30":  "#34d399",
    "30–50":  "#f59e0b",
    "50–70":  "#f97316",
    "70–90":  "#ef4444",
    "90–100": "#dc2626",
}


@router_v1.get("/inward/analytics", response_model=InwardAnalyticsResponse)
async def get_inward_analytics(
    request: Request,
    ctx: UserContext = Depends(require_user_context),
    days: int = 7,
):
    bank_id = ctx.bank_id
    if ctx.role not in _INWARD_ANALYTICS_READ_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    days = max(1, min(days, 30))

    cts_cfg = await config_service.get_cts_config(bank_id)
    ocr_min_conf = float(cts_cfg.get("cts.ocr_min_confidence", 0.90))

    async with pool.acquire() as conn:
        # 1 — daily throughput + AI confidence means
        daily_rows = await conn.fetch(
            """
            SELECT
                TO_CHAR(ad.processing_started_at AT TIME ZONE 'Asia/Kolkata', 'Mon DD') AS date,
                COUNT(*)::int                                                              AS total,
                COUNT(*) FILTER (WHERE ad.decision = 'STP_CONFIRM')::int                  AS stp_confirm,
                COUNT(*) FILTER (WHERE ad.decision = 'STP_RETURN')::int                   AS stp_return,
                COUNT(*) FILTER (WHERE ad.decision = 'HUMAN_REVIEW')::int                 AS human_review,
                COALESCE(ROUND(AVG(ad.processing_duration_ms)), 0)::float                 AS avg_ms,
                ROUND(AVG(ad.ocr_confidence) * 100, 2)                                   AS ocr_conf,
                ROUND(AVG(ad.signature_match_score) * 100, 2)                            AS sig_prec
            FROM cts.agent_decisions ad
            WHERE ad.bank_id = $1
              AND ad.processing_started_at >= NOW() - ($2 * INTERVAL '1 day')
            GROUP BY DATE(ad.processing_started_at AT TIME ZONE 'Asia/Kolkata'),
                     TO_CHAR(ad.processing_started_at AT TIME ZONE 'Asia/Kolkata', 'Mon DD')
            ORDER BY DATE(ad.processing_started_at AT TIME ZONE 'Asia/Kolkata')
            """,
            bank_id, days,
        )

        # 2 — fraud score distribution (6 buckets)
        fraud_rows = await conn.fetch(
            """
            SELECT
                CASE
                    WHEN fraud_score < 0.10 THEN '0–10'
                    WHEN fraud_score < 0.30 THEN '10–30'
                    WHEN fraud_score < 0.50 THEN '30–50'
                    WHEN fraud_score < 0.70 THEN '50–70'
                    WHEN fraud_score < 0.90 THEN '70–90'
                    ELSE '90–100'
                END AS range,
                COUNT(*)::int AS count
            FROM cts.agent_decisions
            WHERE bank_id = $1
              AND fraud_score IS NOT NULL
              AND processing_started_at >= NOW() - ($2 * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY MIN(fraud_score)
            """,
            bank_id, days,
        )

        # 3 — risk flag counts (single aggregate row)
        flags_row = await conn.fetchrow(
            """
            SELECT
                SUM(CASE WHEN ci.amount_range = 'HIGH_VALUE'      THEN 1 ELSE 0 END)::int AS high_value,
                SUM(CASE WHEN ci.amount_range = 'VERY_HIGH_VALUE' THEN 1 ELSE 0 END)::int AS very_high_value,
                SUM(CASE WHEN ad.signature_verdict = 'VAULT_MISS'
                          OR  ad.pps_verdict       = 'VAULT_MISS' THEN 1 ELSE 0 END)::int AS vault_miss,
                SUM(CASE WHEN ad.alteration_detected = true        THEN 1 ELSE 0 END)::int AS alteration,
                SUM(CASE WHEN ad.pps_verdict = 'MISMATCH'          THEN 1 ELSE 0 END)::int AS stop_payment,
                SUM(CASE WHEN ad.ocr_confidence < $3               THEN 1 ELSE 0 END)::int AS ocr_low_conf,
                SUM(CASE WHEN ad.signature_verdict = 'LOW_CONFIDENCE' THEN 1 ELSE 0 END)::int AS sig_low_conf,
                SUM(CASE WHEN ad.cbs_balance_status = 'ACCOUNT_FROZEN' THEN 1 ELSE 0 END)::int AS dormant
            FROM cts.agent_decisions ad
            LEFT JOIN cts.cheque_instruments ci
                   ON ci.instrument_id = ad.instrument_id AND ci.bank_id = ad.bank_id
            WHERE ad.bank_id = $1
              AND ad.processing_started_at >= NOW() - ($2 * INTERVAL '1 day')
            """,
            bank_id, days, ocr_min_conf,
        )

        # 4 — return reasons (STP_RETURN breakdown)
        return_rows = await conn.fetch(
            """
            SELECT
                CASE
                    WHEN decision_reason ILIKE '%FRAUD%'                               THEN 'Fraud Risk'
                    WHEN decision_reason ILIKE '%SIGNATURE%' OR decision_reason ILIKE '%SIG%' THEN 'Sig Mismatch'
                    WHEN decision_reason ILIKE '%ALTERATION%'                          THEN 'Alteration'
                    WHEN decision_reason ILIKE '%INSUFFICIENT%' OR decision_reason ILIKE '%BALANCE%' THEN 'Insufficient Funds'
                    WHEN decision_reason ILIKE '%STOP%' OR decision_reason ILIKE '%PPS%' THEN 'Stop Payment'
                    WHEN decision_reason ILIKE '%FROZEN%' OR decision_reason ILIKE '%DORMANT%' THEN 'Dormant Account'
                    ELSE 'Other'
                END AS reason,
                COUNT(*)::int AS count
            FROM cts.agent_decisions
            WHERE bank_id = $1
              AND decision = 'STP_RETURN'
              AND processing_started_at >= NOW() - ($2 * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY count DESC
            """,
            bank_id, days,
        )

        # 5 — branch breakdown (group by presenting_ifsc from cheque_instruments)
        branch_rows = await conn.fetch(
            """
            SELECT
                COALESCE(ci.presenting_ifsc, 'UNKNOWN')                               AS branch,
                COUNT(*)::int                                                          AS processed,
                COALESCE(ROUND(
                    100.0 * COUNT(*) FILTER (WHERE ad.decision = 'HUMAN_REVIEW')
                    / NULLIF(COUNT(*), 0), 1
                ), 0.0)::float                                                         AS hrq_pct,
                COUNT(*) FILTER (
                    WHERE ad.signature_verdict = 'VAULT_MISS'
                       OR ad.pps_verdict       = 'VAULT_MISS'
                )::int                                                                 AS vault_miss,
                COALESCE(ROUND(AVG(ad.processing_duration_ms)), 0)::float             AS avg_ms,
                COUNT(*) FILTER (WHERE ad.decision = 'STP_RETURN')::int               AS returns
            FROM cts.agent_decisions ad
            LEFT JOIN cts.cheque_instruments ci
                   ON ci.instrument_id = ad.instrument_id AND ci.bank_id = ad.bank_id
            WHERE ad.bank_id = $1
              AND ad.processing_started_at >= NOW() - ($2 * INTERVAL '1 day')
            GROUP BY ci.presenting_ifsc
            ORDER BY COUNT(*) DESC
            LIMIT {_ANALYTICS_TOP_N}
            """,
            bank_id, days,
        )

        # 6 — IET near-breach trend (margin ≤ 30 seconds)
        iet_rows = await conn.fetch(
            """
            SELECT
                TO_CHAR(processing_started_at AT TIME ZONE 'Asia/Kolkata', 'Mon DD') AS date,
                COUNT(*) FILTER (
                    WHERE iet_margin_seconds IS NOT NULL AND iet_margin_seconds <= 30
                )::int AS near_breach
            FROM cts.agent_decisions
            WHERE bank_id = $1
              AND processing_started_at >= NOW() - ($2 * INTERVAL '1 day')
            GROUP BY DATE(processing_started_at AT TIME ZONE 'Asia/Kolkata'),
                     TO_CHAR(processing_started_at AT TIME ZONE 'Asia/Kolkata', 'Mon DD')
            ORDER BY DATE(processing_started_at AT TIME ZONE 'Asia/Kolkata')
            """,
            bank_id, days,
        )

    # Build risk flags list (sorted by count desc, exclude zeros)
    flag_map = {
        "HIGH_VALUE":     flags_row["high_value"]     if flags_row else 0,
        "VERY_HIGH_VALUE":flags_row["very_high_value"] if flags_row else 0,
        "VAULT_MISS":     flags_row["vault_miss"]      if flags_row else 0,
        "ALTERATION":     flags_row["alteration"]      if flags_row else 0,
        "STOP_PAYMENT":   flags_row["stop_payment"]    if flags_row else 0,
        "OCR_LOW_CONF":   flags_row["ocr_low_conf"]    if flags_row else 0,
        "SIG_LOW_CONF":   flags_row["sig_low_conf"]    if flags_row else 0,
        "DORMANT_ACCOUNT":flags_row["dormant"]         if flags_row else 0,
    }
    risk_flags_list = [
        RiskFlagRow(flag=k, count=v)
        for k, v in sorted(flag_map.items(), key=lambda x: -x[1])
        if v > 0
    ]

    return InwardAnalyticsResponse(
        bank_id=bank_id,
        days=days,
        daily=[
            InwardDailyRow(
                date=r["date"],
                total=r["total"],
                stp_confirm=r["stp_confirm"],
                stp_return=r["stp_return"],
                human_review=r["human_review"],
                avg_ms=float(r["avg_ms"] or 0),
                ocr_conf=float(r["ocr_conf"]) if r["ocr_conf"] is not None else None,
                sig_prec=float(r["sig_prec"]) if r["sig_prec"] is not None else None,
            )
            for r in daily_rows
        ],
        fraud_dist=[
            FraudDistRow(range=r["range"], count=r["count"])
            for r in fraud_rows
        ],
        risk_flags=risk_flags_list,
        return_reasons=[
            ReturnReasonRow(reason=r["reason"], count=r["count"])
            for r in return_rows
        ],
        branches=[
            BranchRow(
                branch=r["branch"],
                processed=r["processed"],
                hrq_pct=float(r["hrq_pct"] or 0),
                vault_miss=r["vault_miss"],
                avg_ms=float(r["avg_ms"] or 0),
                returns=r["returns"],
            )
            for r in branch_rows
        ],
        iet_trend=[
            IETTrendRow(date=r["date"], nearBreach=r["near_breach"])
            for r in iet_rows
        ],
    )


# ---------------------------------------------------------------------------
# Phase 2 — Session & Clearing Data
# ---------------------------------------------------------------------------

# [get_all_smb_ledgers moved to cts_smb.py]


# [MOVED to cts_outward_data.py -- Step 1g]
# ReconciliationSessionSummary, DiscrepancyItem, ReconciliationOverviewResponse
# get_outward_reconciliation -- GET /v1/cts/outward/reconciliation

# [MOVED to cts_outward_data.py -- Step 1g]
# LotSummaryRow, LotsListResponse
# list_outward_lots -- GET /v1/cts/outward/lots

# [MOVED to cts_vault_ops.py — Step 1e]
# VaultHealthResponse, VaultMissEvent, VaultMissesResponse, PPSEntry, PPSListResponse
# StopChequeInstruction, StopChequesResponse, _VAULT_READ_ROLES, _VAULT_SENSITIVE_ROLES


# [MOVED to cts_vault_ops.py — Step 1e]
# get_vault_health → GET /v1/cts/vault/health


# [MOVED to cts_vault_ops.py — Step 1e]
# get_vault_misses → GET /v1/cts/vault/misses


# [MOVED to cts_vault_ops.py — Step 1e]
# list_vault_pps → GET /v1/cts/vault/pps


# [MOVED to cts_vault_ops.py — Step 1e]
# list_vault_stop_cheques → GET /v1/cts/vault/stop-cheques


# [dashboard routes moved to cts_dashboard.py]

# [get_smb_forwarding_log_all moved to cts_smb.py]

# [exceptions route moved to cts_dashboard.py]


# [MOVED to cts_outward_data.py -- Step 1g]
# ClearingSessionItem, ClearingSessionsResponse
# get_clearing_sessions -- GET /v1/cts/outward/sessions


# [MOVED to cts_admin_ops.py — Step 1f]
# get_auth_login_log → GET /v1/cts/admin/login-log


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/inward/live-flow — real-time inward instrument stream
# ─────────────────────────────────────────────────────────────────────────────

class LiveFlowItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    stage: str
    status: str
    amount_range: str
    micr_suffix: Optional[str] = None
    elapsed_ms: Optional[int] = None
    decision: Optional[str] = None
    fraud_score: Optional[float] = None
    started_at: str


class LiveFlowResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    items: list[LiveFlowItem]
    total: int


@router_v1.get("/inward/live-flow", response_model=LiveFlowResponse)
async def get_inward_live_flow(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = Query(50, ge=1, le=200),
) -> LiveFlowResponse:
    """
    Returns the most recent inward instruments still in-flight or completed
    in the last 10 minutes — used by CTSInwardMonitor ReactFlow diagram.
    """
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return LiveFlowResponse(bank_id=bank_id, items=[], total=0)

    try:
        rows = await db.fetch(
            """
            SELECT
                instrument_id,
                processing_stage    AS stage,
                processing_status   AS status,
                amount_range,
                micr_suffix,
                EXTRACT(EPOCH FROM (NOW() - received_at))::int * 1000 AS elapsed_ms,
                decision_outcome    AS decision,
                fraud_score,
                received_at::text   AS started_at
            FROM cts.cheque_instruments
            WHERE bank_id = $1
              AND received_at >= NOW() - INTERVAL '10 minutes'
            ORDER BY received_at DESC
            LIMIT $2
            """,
            bank_id,
            limit,
        )
    except Exception as exc:
        log.warning("cts.live_flow.query_failed", bank_id=bank_id, error=str(exc))
        return LiveFlowResponse(bank_id=bank_id, items=[], total=0)

    items = [
        LiveFlowItem(
            instrument_id=r["instrument_id"],
            stage=r["stage"] or "RECEIVED",
            status=r["status"] or "PENDING",
            amount_range=r["amount_range"] or "₹[<1L]",
            micr_suffix=r["micr_suffix"],
            elapsed_ms=r["elapsed_ms"],
            decision=r["decision"],
            fraud_score=float(r["fraud_score"]) if r["fraud_score"] is not None else None,
            started_at=r["started_at"] or "",
        )
        for r in rows
    ]
    return LiveFlowResponse(bank_id=bank_id, items=items, total=len(items))


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/inward/sessions — drawee view: today's inward sessions
# ─────────────────────────────────────────────────────────────────────────────

class InwardSessionItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    clearing_date: str
    session_type: str
    status: str
    total_received: int
    stp_confirmed: int
    stp_returned: int
    pending_review: int
    iet_at_risk: int
    opened_at: str
    closed_at: Optional[str] = None


class InwardSessionsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    sessions: list[InwardSessionItem]
    total: int


@router_v1.get("/inward/sessions", response_model=InwardSessionsResponse)
async def get_inward_sessions(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> InwardSessionsResponse:
    """
    Returns today's inward clearing sessions with decision aggregates.
    Used by CTSDraweeView for session-level status display.
    """
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        return InwardSessionsResponse(bank_id=bank_id, sessions=[], total=0)

    try:
        rows = await db.fetch(
            """
            SELECT
                cs.session_id,
                cs.clearing_date::text,
                cs.session_type,
                cs.status,
                cs.opened_at::text,
                cs.closed_at::text,
                COUNT(ad.instrument_id)::int                                         AS total_received,
                COUNT(ad.instrument_id) FILTER (
                    WHERE ad.decision_outcome IN ('STP_CONFIRM','CONFIRMED'))::int   AS stp_confirmed,
                COUNT(ad.instrument_id) FILTER (
                    WHERE ad.decision_outcome IN ('STP_RETURN','RETURNED'))::int     AS stp_returned,
                COUNT(ad.instrument_id) FILTER (
                    WHERE ad.decision_outcome = 'HUMAN_REVIEW')::int                AS pending_review,
                0::int AS iet_at_risk
            FROM cts.clearing_sessions cs
            LEFT JOIN cts.agent_decisions ad
                   ON ad.session_id = cs.session_id AND ad.bank_id = cs.bank_id
            WHERE cs.bank_id = $1
              AND cs.clearing_date = CURRENT_DATE
              AND cs.direction = 'INWARD'
            GROUP BY cs.session_id, cs.clearing_date, cs.session_type,
                     cs.status, cs.opened_at, cs.closed_at
            ORDER BY cs.opened_at DESC
            """,
            bank_id,
        )
    except Exception as exc:
        log.warning("cts.inward_sessions.query_failed", bank_id=bank_id, error=str(exc))
        return InwardSessionsResponse(bank_id=bank_id, sessions=[], total=0)

    sessions = [
        InwardSessionItem(
            session_id=r["session_id"],
            clearing_date=r["clearing_date"],
            session_type=r["session_type"] or "MORNING",
            status=r["status"],
            total_received=r["total_received"],
            stp_confirmed=r["stp_confirmed"],
            stp_returned=r["stp_returned"],
            pending_review=r["pending_review"],
            iet_at_risk=r["iet_at_risk"],
            opened_at=r["opened_at"] or "",
            closed_at=r["closed_at"],
        )
        for r in rows
    ]
    return InwardSessionsResponse(bank_id=bank_id, sessions=sessions, total=len(sessions))


# [MOVED to cts_outward_data.py -- Step 1g]
# ComplianceCheckItem, OutwardComplianceResponse
# get_outward_compliance -- GET /v1/cts/outward/compliance

# [MOVED to cts_admin_ops.py — Step 1f]
# get_ngch_routing   → GET /v1/cts/admin/ngch-routing
# get_micr_prefixes  → GET /v1/cts/admin/micr-prefixes
# get_rpc_zones      → GET /v1/cts/rpc/zones

# [MOVED to cts_outward_data.py -- Step 1g]
# EndorsementQueueItem, EndorsementQueueResponse
# OutwardDecisionItem, OutwardDecisionsResponse
# get_endorsement_queue -- GET /v1/cts/outward/endorsement-queue
# get_outward_decisions -- GET /v1/cts/outward/decisions

# [MOVED to cts_outward_data.py -- Step 1g]
# IQAResultItem, IQAResultsResponse
# get_iqa_results -- GET /v1/cts/outward/iqa-results
# [MOVED to cts_outward_data.py -- Step 1g]
# OutwardPipelineInstrument, OutwardPipelineResponse, _OUTCOME_TO_STAGE
# get_outward_pipeline -- GET /v1/cts/outward/pipeline
