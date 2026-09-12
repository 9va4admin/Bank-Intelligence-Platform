"""
CTS Inward router — cheque submission, decision polling, human review, analytics.

Routes:
  POST /v1/cts/inward/{instrument_id}/submit
  GET  /v1/cts/decisions/{instrument_id}
  POST /v1/cts/review/{instrument_id}/decide
  GET  /v1/cts/queue
  GET  /v1/cts/decisions
  GET  /v1/cts/vault-gaps
  GET  /v1/cts/instruments/search
  GET  /v1/cts/inward/analytics
  GET  /v1/cts/inward/live-flow
  GET  /v1/cts/inward/sessions
"""
import time
from typing import List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict

from apps.api.routers.cts_deps import (
    _safe_temporal_param,
    _VAULT_GAP_MAX_ROWS,
    _ANALYTICS_TOP_N,
    get_current_user_context,
    get_current_bank_id,
    get_current_user_id,
    get_kafka_producer,
)
from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
from modules.cts.workflows.human_review_workflow import ReviewDecision
from shared.auth.rbac import RBACPolicy, Role, UserContext
from shared.config.config_service import config_service
from shared.event_bus.producer import EventProducer as KafkaEventProducer

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS Inward v1"])


# ─── Models ──────────────────────────────────────────────────────────────────

class ChequeSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    account_number: str
    cheque_number: str
    presented_amount: float
    presented_payee: str
    iet_deadline: float


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
    workflow_status: str
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
    account_display: str
    payee_display: str
    amount_range: str
    clearing_zone: str
    received_at: float
    iet_deadline: float
    reason: str
    fraud_score: Optional[float] = None
    ocr_confidence: Optional[float] = None
    sig_match_score: Optional[float] = None
    security_features: Optional[dict] = None


class QueueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[QueueItem]
    total: int
    bank_id: str


class DecisionLogItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    decision: str
    decision_reason: str
    fraud_score: float
    shap_values: dict
    processing_duration_ms: int
    iet_margin_seconds: int
    degraded_mode: bool
    created_at: float
    ocr_engines_used: list[str] = []
    indic_ocr_kill_switch_active: bool = False
    signature_match_score: float = 0.0
    signature_verdict: str = "UNKNOWN"
    pps_verdict: str = "NOT_CHECKED"
    cbs_balance_status: str = "NOT_CHECKED"
    alteration_detected: bool = False
    micr_code: Optional[str] = None
    account_display: Optional[str] = None
    amount_range: Optional[str] = None
    presenting_ifsc: Optional[str] = None


class DecisionLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[DecisionLogItem]
    total: int
    bank_id: str


class VaultGapAccount(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_display: str
    instrument_count: int
    instrument_ids: list[str]
    micr_codes: list[Optional[str]]
    first_seen_at: float
    last_seen_at: float


class VaultGapResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    date: str
    bank_id: str
    total_accounts_affected: int
    total_instruments: int
    gaps: list[VaultGapAccount]


class ChequeSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    cheque_number: str
    account_display: str
    payee_display: str
    amount_range: str
    status: str
    clearing_zone: str
    received_at: float
    fraud_score: Optional[float] = None
    ocr_confidence: Optional[float] = None


class ChequeSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    results: list[ChequeSearchResult]
    total: int
    bank_id: str


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


_INWARD_ANALYTICS_READ_ROLES = {
    Role.OPS_MANAGER, Role.FRAUD_ANALYST, Role.BANK_IT_ADMIN,
    Role.OPS_REVIEWER, Role.COMPLIANCE_OFFICER,
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _instrument_search(bank_id: str, q: str, limit: int, db) -> ChequeSearchResponse:
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


# ─── Routes ──────────────────────────────────────────────────────────────────

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
    workflow_id = f"cts-{bank_id}-{instrument_id}"

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
                execution_timeout=_td(hours=4),
            )
        except WorkflowAlreadyStartedError:
            pass
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
    if limit > 100:
        limit = 100

    policy = RBACPolicy()
    eff_bank_id, smb_id_filter = policy.smb_instrument_filter(ctx)

    temporal_client = getattr(request.app.state, "temporal_client", None)
    items: list[QueueItem] = []

    if temporal_client is not None:
        try:
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

    items.sort(key=lambda x: x.iet_deadline)
    log.info("cts.queue_fetched", bank_id=eff_bank_id, smb_filter=smb_id_filter, count=len(items))
    return QueueResponse(items=items, total=len(items), bank_id=eff_bank_id)


@router_v1.get(
    "/decisions",
    response_model=DecisionLogResponse,
)
async def list_decisions(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    limit: int = 50,
) -> DecisionLogResponse:
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


@router_v1.get("/vault-gaps", response_model=VaultGapResponse)
async def get_vault_gaps(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
    date: Optional[str] = None,
) -> VaultGapResponse:
    import json as _json
    from datetime import date as _date

    session_date = date or _date.today().isoformat()

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    gaps: list[VaultGapAccount] = []

    if db_pool is not None:
        _SQL = f"""
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


@router_v1.get(
    "/instruments/search",
    response_model=ChequeSearchResponse,
)
async def search_instruments(
    request: Request,
    q: str,
    bank_id: str = Depends(get_current_bank_id),
    limit: int = 8,
) -> ChequeSearchResponse:
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


@router_v1.get("/inward/analytics", response_model=InwardAnalyticsResponse)
async def get_inward_analytics(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
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

        branch_rows = await conn.fetch(
            f"""
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

    flag_map = {
        "HIGH_VALUE":      flags_row["high_value"]      if flags_row else 0,
        "VERY_HIGH_VALUE": flags_row["very_high_value"] if flags_row else 0,
        "VAULT_MISS":      flags_row["vault_miss"]       if flags_row else 0,
        "ALTERATION":      flags_row["alteration"]       if flags_row else 0,
        "STOP_PAYMENT":    flags_row["stop_payment"]     if flags_row else 0,
        "OCR_LOW_CONF":    flags_row["ocr_low_conf"]     if flags_row else 0,
        "SIG_LOW_CONF":    flags_row["sig_low_conf"]     if flags_row else 0,
        "DORMANT_ACCOUNT": flags_row["dormant"]          if flags_row else 0,
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
        fraud_dist=[FraudDistRow(range=r["range"], count=r["count"]) for r in fraud_rows],
        risk_flags=risk_flags_list,
        return_reasons=[ReturnReasonRow(reason=r["reason"], count=r["count"]) for r in return_rows],
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
        iet_trend=[IETTrendRow(date=r["date"], nearBreach=r["near_breach"]) for r in iet_rows],
    )


@router_v1.get("/inward/live-flow", response_model=LiveFlowResponse)
async def get_inward_live_flow(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = Query(50, ge=1, le=200),
) -> LiveFlowResponse:
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


@router_v1.get("/inward/sessions", response_model=InwardSessionsResponse)
async def get_inward_sessions(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> InwardSessionsResponse:
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
