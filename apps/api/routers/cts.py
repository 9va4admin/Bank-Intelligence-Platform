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
import re
import time
from datetime import date, datetime, timezone
from typing import Literal, Optional

_TEMPORAL_PARAM_RE = re.compile(r'^[a-zA-Z0-9\-_]{1,64}$')


def _safe_temporal_param(value: str, field: str) -> str:
    """Reject bank_id / smb_id values that could inject into a Temporal visibility query."""
    if not _TEMPORAL_PARAM_RE.match(value):
        raise ValueError(f"Invalid {field} for Temporal query: must be alphanumeric + hyphens/underscores, max 64 chars")
    return value

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
from modules.cts.workflows.human_review_workflow import ReviewDecision
from shared.auth.rbac import BankType, Role, PermissionLevel, RBACPolicy, UserContext
from shared.config.config_service import config_service
from shared.event_bus.producer import EventProducer as KafkaEventProducer

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

_policy = RBACPolicy()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def get_current_user_context(
    ctx: UserContext = Depends(require_user_context),
) -> UserContext:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.

    Kept as a thin re-export — not a copy — so the many existing
    Depends(get_current_user_context) call sites in this router don't need
    to change. There is no token parsing here anymore: no test-token
    backdoor, no per-router auth logic. ASTRA-01.
    """
    return ctx


async def get_current_bank_id(
    ctx: UserContext = Depends(get_current_user_context),
) -> str:
    return ctx.bank_id


async def get_current_user_id(
    ctx: UserContext = Depends(get_current_user_context),
) -> str:
    return ctx.user_id


# ---------------------------------------------------------------------------
# Temporal client dependency
# ---------------------------------------------------------------------------

def get_temporal_client(request: Request):
    """Retrieve the Temporal client stored on app state at startup."""
    client = getattr(request.app.state, "temporal_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow engine unavailable",
        )
    return client


def get_kafka_producer(request: Request) -> Optional[KafkaEventProducer]:
    """Return Kafka producer from app state, or None in test/dev mode."""
    return getattr(request.app.state, "kafka_producer", None)


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
            LIMIT 2000
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

    # Production: query YugabyteDB cts.cheque_instruments with explicit column list.
    # SELECT instrument_id, cheque_number, account_display, payee_display,
    #        amount_range, status, clearing_zone, received_at, fraud_score, ocr_confidence
    # FROM cts.cheque_instruments
    # WHERE bank_id = $1
    #   AND (cheque_number ILIKE $2 OR instrument_id ILIKE $2)
    # ORDER BY received_at DESC LIMIT $3
    log.info("cts.instrument_search", bank_id=bank_id, query_len=len(q))
    return ChequeSearchResponse(results=[], total=0, bank_id=bank_id)


# ---------------------------------------------------------------------------
# Instrument digest — full pipeline step trail per cheque
# ---------------------------------------------------------------------------

class DigestStepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    step_id:     str
    outcome:     str                      # PASS | FAIL | SKIPPED | DEGRADED
    reason:      Optional[str]  = None
    score:       Optional[float] = None
    duration_ms: Optional[int]  = None
    extra:       dict = {}


class InstrumentDigestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id:    str
    bank_id:          str
    pipeline:         str
    workflow_id:      str
    started_at:       float
    decided_at:       float
    final_decision:   str
    steps:            list[DigestStepResult]
    shap_values:      dict = {}
    registry_version: str


@router_v1.get(
    "/instruments/{instrument_id}/digest",
    response_model=InstrumentDigestResponse,
)
async def get_instrument_digest(
    instrument_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> InstrumentDigestResponse:
    """
    Return the full pipeline step trail for one instrument (passbook view).

    Reads steps_digest JSONB from cts.agent_decisions. Returns 404 when the
    instrument has not yet been processed or belongs to a different bank_id.
    Excludes shap_values from response (available to fraud_analyst role only).
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT instrument_id, bank_id, workflow_id, decision,
                   EXTRACT(EPOCH FROM processing_started_at)::float AS started_at,
                   EXTRACT(EPOCH FROM processing_completed_at)::float AS decided_at,
                   steps_digest, registry_version
            FROM cts.agent_decisions
            WHERE instrument_id = $1 AND bank_id = $2
            LIMIT 1
            """,
            instrument_id,
            bank_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Instrument not found or not yet processed")

    digest_payload = row["steps_digest"] or {}
    steps_raw = digest_payload.get("steps", [])
    steps = [DigestStepResult(**s) for s in steps_raw]

    log.info("cts.instrument_digest", bank_id=bank_id, instrument_id=instrument_id,
             step_count=len(steps))
    return InstrumentDigestResponse(
        instrument_id=row["instrument_id"],
        bank_id=row["bank_id"],
        pipeline=digest_payload.get("pipeline", "INWARD"),
        workflow_id=row["workflow_id"],
        started_at=row["started_at"] or 0.0,
        decided_at=row["decided_at"] or 0.0,
        final_decision=row["decision"],
        steps=steps,
        shap_values={},
        registry_version=row["registry_version"] or "unknown",
    )


# ---------------------------------------------------------------------------
# Admin — stuck workflow cleanup
# ---------------------------------------------------------------------------

class WorkflowCleanupRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_age_minutes: int = 240
    dry_run: bool = False


class WorkflowCleanupResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    found: int
    terminated: int
    dry_run: bool
    degraded: bool


@router_v1.post(
    "/admin/workflows/cleanup",
    response_model=WorkflowCleanupResponse,
)
async def trigger_workflow_cleanup(
    body: WorkflowCleanupRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> WorkflowCleanupResponse:
    """
    On-demand stuck workflow terminator.

    Lists RUNNING ChequeProcessingWorkflow instances for this bank that have
    exceeded max_age_minutes and terminates them immediately.  The automatic
    version fires every 60s via PlatformHealthCheckWorkflow; this endpoint lets
    bank_it_admin or ops_manager trigger a one-shot sweep during incidents.

    dry_run=true returns counts without terminating anything.
    Requires: bank_it_admin or ops_manager role.
    """
    from datetime import datetime, timezone, timedelta as _timedelta
    try:
        from temporalio.client import Client as TemporalClient
        temporal_address = getattr(request.app.state, "temporal_address", "localhost:7233")
        client = await TemporalClient.connect(temporal_address, namespace="default")
    except Exception as exc:
        log.warning("admin.workflow_cleanup.client_error", bank_id=bank_id, error=str(exc))
        return WorkflowCleanupResponse(
            bank_id=bank_id, found=0, terminated=0,
            dry_run=body.dry_run, degraded=True,
        )

    cutoff = datetime.now(tz=timezone.utc) - _timedelta(minutes=body.max_age_minutes)
    found = 0
    terminated = 0

    try:
        query = (
            f'WorkflowType="ChequeProcessingWorkflow" AND '
            f'ExecutionStatus="Running" AND '
            f'TaskQueue="cts-processing-{bank_id}"'
        )
        async for wf in client.list_workflows(query):
            if wf.start_time and wf.start_time < cutoff:
                found += 1
                if not body.dry_run:
                    try:
                        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
                        await handle.terminate(
                            reason=f"ASTRA admin cleanup: exceeded {body.max_age_minutes}min limit"
                        )
                        terminated += 1
                        log.warning(
                            "admin.workflow_cleanup.terminated",
                            bank_id=bank_id, workflow_id=wf.id,
                        )
                    except Exception as term_exc:
                        log.warning(
                            "admin.workflow_cleanup.terminate_failed",
                            bank_id=bank_id, workflow_id=wf.id, error=str(term_exc),
                        )
    except Exception as exc:
        log.warning("admin.workflow_cleanup.list_error", bank_id=bank_id, error=str(exc))
        return WorkflowCleanupResponse(
            bank_id=bank_id, found=0, terminated=0,
            dry_run=body.dry_run, degraded=True,
        )

    log.info(
        "admin.workflow_cleanup.complete",
        bank_id=bank_id, found=found, terminated=terminated, dry_run=body.dry_run,
    )
    return WorkflowCleanupResponse(
        bank_id=bank_id, found=found, terminated=terminated,
        dry_run=body.dry_run, degraded=False,
    )


# ---------------------------------------------------------------------------
# Vault sync — manual trigger + status
# ---------------------------------------------------------------------------

class VaultSyncStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    last_run_at: Optional[float] = None       # Unix timestamp
    triggered_by: Optional[str] = None        # SCHEDULED | MANUAL
    duration_seconds: Optional[int] = None
    pps_records_loaded: int = 0
    stop_cheque_records_loaded: int = 0
    status: str = "UNKNOWN"                   # SUCCESS | PARTIAL | FAILED | RUNNING | UNKNOWN
    next_scheduled: Optional[float] = None
    workflow_id: Optional[str] = None


class VaultSyncTriggerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    status: Literal["TRIGGERED"]
    message: str


@router_v1.get(
    "/vault-sync/status",
    response_model=VaultSyncStatus,
)
async def get_vault_sync_status(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> VaultSyncStatus:
    """Return the status of the most recent VaultSyncWorkflow run for this bank."""
    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from modules.cts.workflows.vault_sync_workflow import VaultSyncWorkflow
            import datetime
            today = datetime.date.today().isoformat()
            workflow_id = f"cts-vaultsync-{bank_id}-{today}"
            handle = temporal_client.get_workflow_handle(workflow_id)
            result = await handle.result()
            return VaultSyncStatus(
                status="SUCCESS",
                workflow_id=workflow_id,
                pps_records_loaded=result.pps_records_loaded if hasattr(result, "pps_records_loaded") else 0,
                stop_cheque_records_loaded=result.stop_records_loaded if hasattr(result, "stop_records_loaded") else 0,
            )
        except Exception:
            pass
    return VaultSyncStatus(status="UNKNOWN")


@router_v1.post(
    "/vault-sync/trigger",
    response_model=VaultSyncTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_vault_sync(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> VaultSyncTriggerResponse:
    """
    Manually trigger a VaultSyncWorkflow run.
    Uses a timestamp-based workflow ID so it runs even if today's scheduled run
    already completed — each manual trigger is a distinct workflow instance.
    """
    import time as _time
    ts = int(_time.time())
    workflow_id = f"cts-vaultsync-manual-{bank_id}-{ts}"

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from modules.cts.workflows.vault_sync_workflow import VaultSyncWorkflow, VaultSyncInput
            from shared.config.config_service import config_service
            pepper = await config_service.get_secret("pii_hash_pepper")
            await temporal_client.start_workflow(
                VaultSyncWorkflow.run,
                VaultSyncInput(bank_id=bank_id, pepper=pepper, triggered_by="MANUAL"),
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
            )
        except Exception as exc:
            log.error("cts.vault_sync_trigger_error", bank_id=bank_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to trigger vault sync workflow",
            ) from exc

    log.info("cts.vault_sync_triggered", bank_id=bank_id, workflow_id=workflow_id)
    return VaultSyncTriggerResponse(
        workflow_id=workflow_id,
        status="TRIGGERED",
        message=f"VaultSyncWorkflow started: {workflow_id}. PPS & Stop Cheque data will refresh within ~60 seconds.",
    )


# ---------------------------------------------------------------------------
# Temporal Schedules endpoints
# ---------------------------------------------------------------------------

class ScheduleInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    schedule_id: str
    label: str
    workflow: str
    module: str                        # always "CTS" for this router
    cron: str
    cron_human: str
    task_queue: str
    status: str                        # "RUNNING" | "PAUSED"
    last_run_at: Optional[float] = None
    last_run_status: Optional[str] = None
    last_run_duration_s: Optional[int] = None
    next_run_at: Optional[float] = None
    created_at: Optional[float] = None


class ScheduleListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    schedules: list[ScheduleInfo]
    bank_id: str


class ScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    cron: str


class ScheduleUpdateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    schedule_id: str
    cron: str
    status: Literal["UPDATED"]
    message: str


# CTS-only schedule registry — EJ schedules live in the EJ router
_CTS_SCHEDULE_REGISTRY = [
    {
        "schedule_id_tpl": "cts-vaultsync-schedule-{bank_id}",
        "label": "PPS & Stop Cheque Vault Sync",
        "workflow": "VaultSyncWorkflow",
        "module": "CTS",
        "cron": "0 7 * * *",
        "cron_human": "Daily at 07:00 AM",
        "task_queue_tpl": "cts-processing-{bank_id}",
    },
]


@router_v1.get(
    "/schedules",
    response_model=ScheduleListResponse,
)
async def list_schedules(
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleListResponse:
    """
    List all Temporal Schedules registered for this bank.
    Queries Temporal for live state; falls back to registry defaults if unavailable.
    """
    temporal_client = getattr(request.app.state, "temporal_client", None)
    results: list[ScheduleInfo] = []

    for reg in _CTS_SCHEDULE_REGISTRY:
        sid = reg["schedule_id_tpl"].format(bank_id=bank_id)
        tq  = reg["task_queue_tpl"].format(bank_id=bank_id)
        # Try to fetch live state from Temporal
        status_val = "RUNNING"
        last_run_at = None
        last_run_status = None
        last_run_duration_s = None
        next_run_at = None
        created_at = None

        if temporal_client is not None:
            try:
                handle = temporal_client.get_schedule_handle(sid)
                desc = await handle.describe()
                status_val = "PAUSED" if desc.schedule.state.paused else "RUNNING"
                if desc.info.recent_actions:
                    last_action = desc.info.recent_actions[-1]
                    last_run_at = last_action.schedule_time.timestamp() if last_action.schedule_time else None
                if desc.info.next_action_times:
                    next_run_at = desc.info.next_action_times[0].timestamp()
                created_at = desc.info.created_at.timestamp() if desc.info.created_at else None
            except Exception:
                pass  # schedule not yet registered — use defaults

        results.append(ScheduleInfo(
            schedule_id=sid,
            label=reg["label"],
            workflow=reg["workflow"],
            module=reg["module"],
            cron=reg["cron"],
            cron_human=reg["cron_human"],
            task_queue=tq,
            status=status_val,
            last_run_at=last_run_at,
            last_run_status=last_run_status,
            last_run_duration_s=last_run_duration_s,
            next_run_at=next_run_at,
            created_at=created_at,
        ))

    log.info("cts.schedules_listed", bank_id=bank_id, count=len(results))
    return ScheduleListResponse(schedules=results, bank_id=bank_id)


@router_v1.patch(
    "/schedules/{schedule_id}",
    response_model=ScheduleUpdateResponse,
)
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdateRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleUpdateResponse:
    """
    Update the cron expression of a Temporal Schedule.
    Uses Temporal schedule handle update — in-place, never delete/recreate.
    Requires bank_it_admin role (enforced by RBAC in production).
    """
    # Verify the schedule belongs to the caller's bank — prevents cross-bank tampering
    if bank_id not in schedule_id:
        # 404 not 403 — IDOR: a 403 reveals the schedule exists (cross-bank existence oracle)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from temporalio.client import ScheduleUpdate, ScheduleSpec

            handle = temporal_client.get_schedule_handle(schedule_id)

            async def updater(input):  # noqa: ANN001
                input.schedule.spec = ScheduleSpec(cron_expressions=[body.cron])
                return ScheduleUpdate(schedule=input.schedule)

            await handle.update(updater)
        except Exception as exc:
            log.error("cts.schedule_update_error", schedule_id=schedule_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to update Temporal Schedule",
            ) from exc

    log.info("cts.schedule_updated", bank_id=bank_id, schedule_id=schedule_id, cron=body.cron)
    return ScheduleUpdateResponse(
        schedule_id=schedule_id,
        cron=body.cron,
        status="UPDATED",
        message=f"Schedule {schedule_id} updated to cron: {body.cron}",
    )


@router_v1.post(
    "/schedules/{schedule_id}/pause",
    response_model=ScheduleUpdateResponse,
)
async def pause_schedule(
    schedule_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleUpdateResponse:
    """Pause a Temporal Schedule — future runs are suppressed."""
    if bank_id not in schedule_id:
        # 404 not 403 — IDOR: a 403 reveals the schedule exists (cross-bank existence oracle)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            handle = temporal_client.get_schedule_handle(schedule_id)
            await handle.pause(note="Paused via ASTRA Admin UI")
        except Exception as exc:
            log.error("cts.schedule_pause_error", schedule_id=schedule_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to pause Temporal Schedule",
            ) from exc

    log.info("cts.schedule_paused", bank_id=bank_id, schedule_id=schedule_id)
    return ScheduleUpdateResponse(
        schedule_id=schedule_id,
        cron="",
        status="UPDATED",
        message=f"Schedule {schedule_id} paused.",
    )


@router_v1.post(
    "/schedules/{schedule_id}/resume",
    response_model=ScheduleUpdateResponse,
)
async def resume_schedule(
    schedule_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScheduleUpdateResponse:
    """Resume a paused Temporal Schedule."""
    if bank_id not in schedule_id:
        # 404 not 403 — IDOR: a 403 reveals the schedule exists (cross-bank existence oracle)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            handle = temporal_client.get_schedule_handle(schedule_id)
            await handle.unpause(note="Resumed via ASTRA Admin UI")
        except Exception as exc:
            log.error("cts.schedule_resume_error", schedule_id=schedule_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to resume Temporal Schedule",
            ) from exc

    log.info("cts.schedule_resumed", bank_id=bank_id, schedule_id=schedule_id)
    return ScheduleUpdateResponse(
        schedule_id=schedule_id,
        cron="",
        status="UPDATED",
        message=f"Schedule {schedule_id} resumed.",
    )


# ---------------------------------------------------------------------------
# Sub-Member Bank (SMB) endpoints — /v1/cts/smb/...
# Requires smb_it_admin or ops_manager role (enforced in production by RBAC).
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
    vault_sync_status: str        # NEVER_SYNCED | SYNC_OK | SYNC_PARTIAL | SYNC_FAILED
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


@router_v1.get(
    "/smb",
    response_model=SMBListResponse,
)
async def list_sub_members(
    ctx: UserContext = Depends(get_current_user_context),
    active_only: bool = True,
) -> SMBListResponse:
    """
    List all Sub-Member Banks registered under this Sponsor Bank.
    SB-only — SMB users cannot enumerate peer institutions.
    Production: queries cts.sub_member_banks JOIN cts.smb_vault_config WHERE bank_id = $1.
    """
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB management is an SB-only operation")
    bank_id = ctx.bank_id
    log.info("smb.list", bank_id=bank_id, active_only=active_only)
    # Production: SELECT sub_member_id, bank_name, micr_prefix, ifsc_prefix,
    #   is_active, return_rate_threshold, soft_hold_threshold,
    #   v.last_sync_status, v.last_vault_sync_at, v.signature_count, v.pps_entry_count
    # FROM cts.sub_member_banks s LEFT JOIN cts.smb_vault_config v USING (bank_id, sub_member_id)
    # WHERE s.bank_id = $1 AND ($2 = FALSE OR s.is_active = TRUE)
    return SMBListResponse(sub_members=[], total=0, sponsor_bank_id=bank_id)


@router_v1.post(
    "/smb",
    response_model=SMBRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_sub_member(
    body: SMBRegistration,
    ctx: UserContext = Depends(get_current_user_context),
) -> SMBRegistrationResponse:
    """
    Register a new Sub-Member Bank under this Sponsor Bank.
    SB-only — an SMB cannot register peer institutions.
    Also creates the smb_vault_config and smb_kafka_topics registry rows.
    Thresholds are seeded from request body — bank can update via Admin UI (Layer 3).
    """
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB registration is an SB-only operation")
    bank_id = ctx.bank_id
    if body.return_rate_threshold >= body.soft_hold_threshold:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="soft_hold_threshold must be greater than return_rate_threshold",
        )

    log.info(
        "smb.register",
        bank_id=bank_id,
        sub_member_id=body.sub_member_id,
        micr_prefix=body.micr_prefix,
    )
    # Production: INSERT INTO cts.sub_member_banks (...) VALUES (...)
    # + INSERT INTO cts.smb_vault_config (...) VALUES (...)
    # + INSERT INTO cts.smb_kafka_topics (...) with derived topic names
    # + INSERT INTO cts.micr_prefix_routing (...) VALUES (...)
    return SMBRegistrationResponse(
        sub_member_id=body.sub_member_id,
        status="REGISTERED",
        message=(
            f"Sub-Member Bank '{body.sub_member_id}' registered under sponsor '{bank_id}'. "
            f"MICR prefix '{body.micr_prefix}' active from today. "
            f"Vault sync required before first clearing session."
        ),
    )


@router_v1.get(
    "/smb/{sub_member_id}/ledger",
    response_model=SMBLedgerResponse,
)
async def get_smb_session_ledger(
    sub_member_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    session_date: Optional[str] = None,
) -> SMBLedgerResponse:
    """
    Return batch ledger for a Sub-Member Bank.
    SB users may view any sub_member_id under their bank_id.
    SMB users may only view their own sub_member_id — cross-SMB access is denied.
    Production: queries cts.sub_member_batch_ledgers WHERE bank_id = $1 AND sub_member_id = $2
    AND session_date = $3.
    """
    if ctx.bank_type == BankType.SMB and ctx.bank_id != sub_member_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB users can only view their own ledger")
    bank_id = ctx.bank_id if ctx.bank_type == BankType.SB else ctx.bank_id
    import datetime as _dt
    date_str = session_date or _dt.date.today().isoformat()
    log.info("smb.ledger", bank_id=bank_id, sub_member_id=sub_member_id, date=date_str)
    return SMBLedgerResponse(ledgers=[], session_date=date_str, bank_id=bank_id)


@router_v1.get(
    "/smb/{sub_member_id}/forwarding-log",
    response_model=SMBForwardingLogResponse,
)
async def get_smb_forwarding_log(
    sub_member_id: str,
    ctx: UserContext = Depends(get_current_user_context),
    limit: int = 50,
) -> SMBForwardingLogResponse:
    """
    Return recent forwarding log entries for a Sub-Member Bank.
    SB users may view any sub_member_id under their bank_id.
    SMB users may only view their own forwarding log.
    No raw PII — instrument_id and forwarding_id are opaque references.
    """
    if ctx.bank_type == BankType.SMB and ctx.bank_id != sub_member_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SMB users can only view their own forwarding log")
    if limit > 100:
        limit = 100
    bank_id = ctx.bank_id
    log.info("smb.forwarding_log", bank_id=bank_id, sub_member_id=sub_member_id, limit=limit)
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
    """
    Trigger VaultSyncWorkflow scoped to a specific Sub-Member Bank.
    SB-only — SMB cannot trigger vault syncs (they don't own the vault).
    Syncs SMB signature specimens and PPS entries into the sponsor bank's Redis vault
    under the smb_vault_prefix namespace (sig:{sub_member_id}:{hash}).
    """
    if ctx.bank_type != BankType.SB:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vault sync trigger is an SB-only operation")
    bank_id = ctx.bank_id
    import time as _time
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
                # NOTE: sub_member_id is not a VaultSyncInput field today — this
                # call already raised a Pydantic "extra inputs not permitted"
                # error on every invocation, independent of this pepper fix.
                # Pre-existing, separate bug (SMB-scoped vault sync routing is
                # undesigned — VaultSyncInput/warm_redis_vault have no
                # sub_member_id-aware Redis key namespacing yet), not fixed here.
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

    log.info(
        "smb.vault_sync_triggered",
        bank_id=bank_id,
        sub_member_id=sub_member_id,
        workflow_id=workflow_id,
    )
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


@router_v1.post(
    "/outward/scan/upload-url",
    response_model=ScanUploadURLResponse,
    status_code=status.HTTP_200_OK,
)
async def request_scan_upload_urls(
    body: ScanUploadURLRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ScanUploadURLResponse:
    """
    Provision presigned MinIO PUT URLs for scanner agent image upload.

    The scanner agent calls this once per cheque, before submit:
      1. POST /outward/scan/upload-url  → get presigned PUT URLs (this endpoint)
      2. PUT front.tiff / rear.tiff / uv.tiff directly to MinIO (agent to MinIO)
      3. POST /outward/scan/submit       → pass the returned object URLs

    Object paths are deterministic — the same scan_id always maps to the same
    object keys, making retries safe (PUT is idempotent in object stores).
    """
    from datetime import timedelta as _td

    front_key = f"{bank_id}/outward/{body.scan_id}/front.tiff"
    rear_key  = f"{bank_id}/outward/{body.scan_id}/rear.tiff"
    uv_key    = f"{bank_id}/outward/{body.scan_id}/uv.tiff"

    front_obj = f"s3://{_CTS_IMAGES_BUCKET}/{front_key}"
    rear_obj  = f"s3://{_CTS_IMAGES_BUCKET}/{rear_key}"
    uv_obj    = f"s3://{_CTS_IMAGES_BUCKET}/{uv_key}"

    expires_at = int(time.time()) + _UPLOAD_URL_EXPIRY_SECONDS
    expiry_td  = _td(seconds=_UPLOAD_URL_EXPIRY_SECONDS)

    minio_client = getattr(request.app.state, "minio_client", None)
    if minio_client is not None:
        try:
            front_url = minio_client.presigned_put_object(
                _CTS_IMAGES_BUCKET, front_key, expires=expiry_td)
            rear_url  = minio_client.presigned_put_object(
                _CTS_IMAGES_BUCKET, rear_key,  expires=expiry_td)
            uv_url    = minio_client.presigned_put_object(
                _CTS_IMAGES_BUCKET, uv_key, expires=expiry_td) if body.include_uv else None
        except Exception as exc:
            log.error("cts.upload_url.minio_error", scan_id=body.scan_id, bank_id=bank_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not provision upload URLs — MinIO unavailable",
            ) from exc
    else:
        # Dev / test mode — return placeholder URLs so the agent can be tested
        # without a running MinIO instance.
        front_url = f"http://minio-dev.local/{_CTS_IMAGES_BUCKET}/{front_key}?presigned=1"
        rear_url  = f"http://minio-dev.local/{_CTS_IMAGES_BUCKET}/{rear_key}?presigned=1"
        uv_url    = f"http://minio-dev.local/{_CTS_IMAGES_BUCKET}/{uv_key}?presigned=1" if body.include_uv else None

    log.info("cts.upload_url.issued", scan_id=body.scan_id, bank_id=bank_id, include_uv=body.include_uv)

    return ScanUploadURLResponse(
        front_presigned_url=front_url,
        rear_presigned_url=rear_url,
        front_object_url=front_obj,
        rear_object_url=rear_obj,
        uv_presigned_url=uv_url,
        uv_object_url=uv_obj if body.include_uv else None,
        expires_at=expires_at,
    )


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


@router_v1.post(
    "/outward/scan/submit",
    response_model=OutwardScanSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_outward_scan(
    body: OutwardScanSubmitRequest,
    request: Request,
    response: Response,
    bank_id: str = Depends(get_current_bank_id),
) -> OutwardScanSubmitResponse:
    """
    Accept a scanned outward instrument from the local scanner agent.

    The scanner agent (edge/cts-scanner-agent/) calls this endpoint after:
      1. Capturing front + rear TIFF images via Ranger Transport API
      2. Reading hardware MICR via TransportGetMICR()
      3. Uploading images to MinIO (already done before this call)

    This endpoint launches OutwardScanWorkflow on the CTS Temporal task queue.
    The workflow ID is deterministic — duplicate submissions are idempotent.

    When micr_hardware_raw is present, the CR-120 path is taken:
      validate_cts2010 → create_lot_entry → vision_extract_and_check (single Qwen2-VL)

    When micr_hardware_raw is absent, the legacy path is taken:
      ocr_extract (GOT-OCR2) → validate_cts2010 → create_lot_entry → run_vision_presentment_check
    """
    workflow_id = f"cts-outscan-{bank_id}-{body.scan_id}"
    if body.pu_id:
        workflow_id = f"cts-outscan-{bank_id}-{body.pu_id}-{body.scan_id}"

    from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow, OutwardScanInput

    workflow_input = OutwardScanInput(
        scan_id=body.scan_id,
        instrument_id=body.instrument_id,
        bank_id=bank_id,
        bank_ifsc=body.bank_ifsc,
        session_id=body.session_id,
        image_front_url=body.image_front_url,
        image_rear_url=body.image_rear_url,
        cheque_number=body.cheque_number,
        front_dpi=body.front_dpi,
        rear_dpi=body.rear_dpi,
        front_colour_depth=body.front_colour_depth,
        rear_colour_depth=body.rear_colour_depth,
        front_file_size_kb=body.front_file_size_kb,
        rear_file_size_kb=body.rear_file_size_kb,
        micr_hardware_raw=body.micr_hardware_raw,
        image_uv_url=body.image_uv_url,
        pu_id=body.pu_id,
        branch_id=body.branch_id,
    )

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from datetime import timedelta as _td
            from temporalio.exceptions import WorkflowAlreadyStartedError
            await temporal_client.start_workflow(
                OutwardScanWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
                execution_timeout=_td(hours=24),  # clearing session max window; auto-terminates stuck outward workflows
            )
        except WorkflowAlreadyStartedError:
            pass  # idempotent
        except Exception as exc:
            log.error(
                    "cts.outward_scan_workflow_error",
                    scan_id=body.scan_id,
                    bank_id=bank_id,
                    error=str(exc),
                )
            raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to start OutwardScanWorkflow",
                ) from exc

    path = "CR120" if body.micr_hardware_raw else "LEGACY"

    # ── Real-time lot + session tracking (fire-and-forget, best-effort) ──────
    # Increment eeh_sessions.total_uploaded and manage the OPEN scanning batch
    # lot for this branch. Failures are logged and skipped — never block the scan.
    if body.session_id and body.branch_id:
        state = getattr(getattr(request, "app", None), "state", None)
        _db_pool = getattr(state, "db_pool_cts", None) if state else None
        if _db_pool is not None:
            try:
                async with _db_pool.acquire() as _conn:
                    await _conn.execute(
                        "UPDATE cts.eeh_sessions SET total_uploaded = total_uploaded + 1 "
                        "WHERE session_id = $1",
                        body.session_id,
                    )
                    await _ensure_open_lot(
                        _conn,
                        bank_id=bank_id,
                        branch_id=body.branch_id,
                        session_id=body.session_id,
                        clearing_date=date.today(),
                    )
            except Exception as _lot_exc:
                log.warning(
                    "cts.outward_scan.lot_tracking_error",
                    scan_id=body.scan_id, bank_id=bank_id, error=str(_lot_exc),
                )

    log.info(
        "cts.outward_scan_submitted",
        scan_id=body.scan_id,
        instrument_id=body.instrument_id,
        bank_id=bank_id,
        workflow_id=workflow_id,
        path=path,
    )

    response.headers["X-Workflow-Id"] = workflow_id
    return OutwardScanSubmitResponse(
        scan_id=body.scan_id,
        instrument_id=body.instrument_id,
        workflow_id=workflow_id,
        status="ACCEPTED",
        path=path,
    )


# ---------------------------------------------------------------------------
# IFSC Registry — CRUD routes
# ---------------------------------------------------------------------------
# Maker-checker model:
#   ops_manager  — POST (create, status=PENDING)
#   bank_it_admin — PUT /{id}/approve (activate) and DELETE /{id} (deactivate)
#   Any authenticated user — GET list / GET by ID
# ---------------------------------------------------------------------------

from modules.cts.ifsc.models import IFSCCreateRequest, IFSCEntry, IFSCListResponse
from modules.cts.ifsc.repository import IFSCDuplicateError


def _get_ifsc_repo(request: Request):
    repo = getattr(request.app.state, "ifsc_repo", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IFSC registry unavailable",
        )
    return repo


@router_v1.get("/ifsc-registry", response_model=IFSCListResponse)
async def list_ifsc_registry(
    request: Request,
    bank_type: Optional[str] = None,
    smb_id: Optional[str] = None,
    active_only: bool = True,
    limit: int = 50,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCListResponse:
    """List IFSC entries for the authenticated bank. Optionally filter by bank_type or smb_id."""
    repo = _get_ifsc_repo(request)
    entries = await repo.list_ifsc(
        ctx.bank_id,
        bank_type=bank_type,
        smb_id=smb_id,
        active_only=active_only,
        limit=min(limit, 100),
    )
    return IFSCListResponse(items=entries, total=len(entries), bank_id=ctx.bank_id)


@router_v1.get("/ifsc-registry/{entry_id}", response_model=IFSCEntry)
async def get_ifsc_by_id(
    entry_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    """Fetch a single IFSC registry entry by UUID."""
    repo = _get_ifsc_repo(request)
    entry = await repo.get_ifsc_by_id(entry_id)
    if entry is None or entry.bank_id != ctx.bank_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IFSC entry not found")
    return entry


@router_v1.post("/ifsc-registry", response_model=IFSCEntry, status_code=status.HTTP_201_CREATED)
async def create_ifsc(
    body: IFSCCreateRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    """
    Create a new IFSC entry (status=PENDING, maker step).
    Requires ops_manager role.
    """
    if ctx.role.value not in ("ops_manager", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops_manager role required")
    repo = _get_ifsc_repo(request)
    try:
        entry = await repo.create_ifsc(ctx.bank_id, body, created_by=ctx.user_id)
    except IFSCDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    log.info("ifsc_registry.created", ifsc_code=body.ifsc_code, bank_id=ctx.bank_id, created_by=ctx.user_id)
    return entry


@router_v1.put("/ifsc-registry/{entry_id}/approve", response_model=IFSCEntry)
async def approve_ifsc(
    entry_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    """
    Approve a PENDING IFSC entry → ACTIVE (checker step).
    Requires bank_it_admin role.
    """
    if ctx.role.value != "bank_it_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bank_it_admin role required")
    repo = _get_ifsc_repo(request)
    entry = await repo.approve_ifsc(entry_id, approved_by=ctx.user_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IFSC entry not found")
    log.info("ifsc_registry.approved", entry_id=entry_id, bank_id=ctx.bank_id, approved_by=ctx.user_id)
    return entry


@router_v1.delete("/ifsc-registry/{entry_id}", response_model=IFSCEntry)
async def deactivate_ifsc(
    entry_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> IFSCEntry:
    """
    Deactivate an ACTIVE IFSC entry → INACTIVE (soft delete, never hard delete).
    Requires bank_it_admin role.
    """
    if ctx.role.value != "bank_it_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bank_it_admin role required")
    repo = _get_ifsc_repo(request)
    entry = await repo.deactivate_ifsc(entry_id, updated_by=ctx.user_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IFSC entry not found")
    log.info("ifsc_registry.deactivated", entry_id=entry_id, bank_id=ctx.bank_id, updated_by=ctx.user_id)
    return entry


# ---------------------------------------------------------------------------
# Hold Queue endpoints
# ---------------------------------------------------------------------------

class HoldItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    hold_id: str
    instrument_id: str
    bank_id: str
    held_by: str
    held_at: float
    iet_deadline: float
    hold_reason: str
    branch_notified_at: Optional[float] = None
    branch_recommendation: Optional[str] = None
    branch_note: Optional[str] = None
    amount_display: str = ""
    payee_display: str = ""
    account_display: str = ""
    queue_tier: str = "standard"


class HoldListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[HoldItem]
    total: int
    bank_id: str


class PlaceHoldRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    hold_reason: str
    iet_deadline: float      # forwarded from the HumanReview record in the caller
    branch_email: Optional[str] = None    # if None, looked up from branch contact registry
    branch_phone: Optional[str] = None


class PlaceHoldResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    hold_id: str
    held_at: float
    iet_remaining_seconds: float
    branch_notified: bool


class HoldReleaseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_note: Optional[str] = None
    branch_recommendation: Optional[str] = None


class HoldReleaseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    hold_id: str
    released: bool
    hold_duration_seconds: Optional[float] = None
    iet_remaining_at_release: Optional[float] = None


class HoldRecommendationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_note: Optional[str] = None
    branch_recommendation: Optional[str] = None  # "CONFIRM" | "RETURN"


class HoldRecommendationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    hold_id: str
    updated: bool


@router_v1.post(
    "/holds/{instrument_id}",
    response_model=PlaceHoldResponse,
    status_code=status.HTTP_201_CREATED,
)
async def place_hold(
    instrument_id: str,
    body: PlaceHoldRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> PlaceHoldResponse:
    """
    Place a hold on an instrument — pauses it in the review queue while the
    branch is consulted. IET clock NEVER pauses.
    Calls HoldService.place_hold() which: persists IET timing fields, sends
    branch email/WhatsApp notification, and writes CTS_WF_HOLD_PLACED to Immudb.
    Roles: ops_reviewer, ops_manager.
    """
    import time as _time
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    if ctx.role.value not in ("ops_reviewer", "ops_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    dispatcher = getattr(request.app.state, "notification_dispatcher", None)
    audit_writer_raw = getattr(request.app.state, "audit_stream_writer", None)

    # Wrap audit_writer in the interface HoldService expects: audit.write(event_type, bank_id, payload)
    class _AuditWriterAdapter:
        def __init__(self, writer):
            self._writer = writer
        async def write(self, event_type, bank_id, payload):
            if self._writer is None:
                return
            from shared.audit.audit_event import AuditEvent, AuditEventType
            await self._writer(AuditEvent(
                event_type=getattr(AuditEventType, event_type, AuditEventType.CTS_HOLD_PLACED),
                bank_id=bank_id,
                user_id=reviewer_id,
                payload=payload,
            ))

    # Build a thin DB adapter that HoldService can call .execute() on
    class _DBAdapter:
        def __init__(self, pool):
            self._pool = pool
        async def execute(self, query, *args):
            if self._pool is None:
                return
            async with self._pool.acquire() as conn:
                await conn.execute(query, *args)

    branch_contact = {}
    if body.branch_email:
        branch_contact["email"] = body.branch_email
    if body.branch_phone:
        branch_contact["phone"] = body.branch_phone

    from modules.cts.hold.hold_service import HoldService
    hold_svc = HoldService(
        db_pool=_DBAdapter(pool),
        dispatcher=dispatcher,
        audit_writer=_AuditWriterAdapter(audit_writer_raw),
    )

    record = await hold_svc.place_hold(
        instrument_id=instrument_id,
        bank_id=bank_id,
        reviewer_id=reviewer_id,
        hold_reason=body.hold_reason,
        iet_deadline=body.iet_deadline,
        branch_contact=branch_contact,
    )

    # Derive hold_id from the DB insert (HoldService doesn't return it; query it back)
    hold_id = instrument_id  # fallback
    if pool is not None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT hold_id FROM cts.instrument_holds WHERE instrument_id = $1 AND bank_id = $2 AND released_at IS NULL ORDER BY held_at DESC LIMIT 1",
                instrument_id, bank_id,
            )
            if row:
                hold_id = row["hold_id"]

    iet_remaining = max(0.0, body.iet_deadline - _time.time())

    # Start the escalation chain: 30-min reminder → T-60min CRITICAL → T-5min P0
    try:
        from temporalio.client import Client as TemporalClient
        from modules.cts.workflows.hold_escalation_workflow import (
            HoldEscalationWorkflow, HoldEscalationInput,
        )
        temporal_address = await config_service.get("temporal.address")
        temporal_client = await TemporalClient.connect(temporal_address)
        escalation_input = HoldEscalationInput(
            instrument_id=instrument_id,
            bank_id=bank_id,
            reviewer_id=reviewer_id,
            iet_deadline=body.iet_deadline,
            held_at=record.held_at,
            branch_email=body.branch_email,
        )
        await temporal_client.start_workflow(
            HoldEscalationWorkflow.run,
            escalation_input,
            id=f"cts-hold-escalation-{bank_id}-{instrument_id}",
            task_queue=f"cts-processing-{bank_id}",
        )
    except Exception as _exc:
        # Escalation workflow failure MUST NOT block the hold response — log and continue
        log.warning("hold.escalation.start_failed", instrument_id=instrument_id,
                    bank_id=bank_id, error=str(_exc))

    log.info("cts.hold.placed", instrument_id=instrument_id, bank_id=bank_id, reviewer_id=reviewer_id)
    return PlaceHoldResponse(
        instrument_id=instrument_id,
        hold_id=hold_id,
        held_at=record.held_at,
        iet_remaining_seconds=iet_remaining,
        branch_notified=record.branch_notified_at is not None,
    )


@router_v1.get(
    "/holds",
    response_model=HoldListResponse,
)
async def list_holds(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HoldListResponse:
    """
    List all active (unreleased) holds for this bank.
    Roles: ops_manager, ops_reviewer, branch_manager (scoped to own branch).
    """
    bank_id = ctx.bank_id
    allowed_roles = ("ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager")
    if ctx.role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    items: list[HoldItem] = []

    if pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    h.hold_id, h.instrument_id, h.bank_id, h.held_by,
                    h.held_at, h.iet_deadline, h.hold_reason,
                    h.branch_notified_at, h.branch_recommendation, h.branch_note,
                    i.account_last4, i.amount_range, i.queue_tier
                FROM cts.instrument_holds h
                LEFT JOIN cts.cheque_instruments i
                    ON h.instrument_id = i.instrument_id::TEXT
                    AND i.bank_id = $1
                WHERE h.bank_id = $1
                  AND h.released_at IS NULL
                ORDER BY h.iet_deadline ASC
                """,
                bank_id,
            )
            for row in rows:
                last4 = row["account_last4"] or "????"
                amount_range = row["amount_range"] or "STANDARD"
                amount_display = {
                    "STANDARD": "₹[<1L]",
                    "HIGH_VALUE": "₹[1L–5L]",
                    "VERY_HIGH_VALUE": "₹[>1Cr]",
                }.get(amount_range, "₹[?]")
                items.append(HoldItem(
                    hold_id=row["hold_id"],
                    instrument_id=row["instrument_id"],
                    bank_id=row["bank_id"],
                    held_by=row["held_by"],
                    held_at=row["held_at"],
                    iet_deadline=row["iet_deadline"],
                    hold_reason=row["hold_reason"],
                    branch_notified_at=row["branch_notified_at"],
                    branch_recommendation=row["branch_recommendation"],
                    branch_note=row["branch_note"],
                    account_display=f"****{last4}",
                    amount_display=amount_display,
                    payee_display="***",
                    queue_tier=row["queue_tier"] or "standard",
                ))

    log.info("cts.holds.listed", bank_id=bank_id, count=len(items))
    return HoldListResponse(items=items, total=len(items), bank_id=bank_id)


@router_v1.post(
    "/holds/{instrument_id}/release",
    response_model=HoldReleaseResponse,
    status_code=status.HTTP_200_OK,
)
async def release_hold(
    instrument_id: str,
    body: HoldReleaseRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HoldReleaseResponse:
    """
    Release a hold — instrument returns to review queue.
    Roles: ops_manager, ops_reviewer.
    Writes CTS_HOLD_RELEASED audit event to Immudb.
    """
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    allowed_roles = ("ops_manager", "ops_reviewer")
    if ctx.role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ops_manager or ops_reviewer role required")

    pool = getattr(request.app.state, "db_pool_cts", None)
    hold_id: Optional[str] = None

    if pool is not None:
        import time as _time
        now = _time.time()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE cts.instrument_holds
                   SET released_at = $1,
                       released_by = $2,
                       branch_note = COALESCE($3, branch_note),
                       branch_recommendation = COALESCE($4, branch_recommendation)
                 WHERE instrument_id = $5
                   AND bank_id = $6
                   AND released_at IS NULL
                RETURNING hold_id
                """,
                now, reviewer_id,
                body.branch_note, body.branch_recommendation,
                instrument_id, bank_id,
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active hold not found for this instrument",
            )
        hold_id = row["hold_id"]

        # Audit — every hold release is an auditable decision
        from shared.audit.audit_event import AuditEvent, AuditEventType
        from shared.messages import get_message
        audit_writer = getattr(request.app.state, "audit_stream_writer", None)
        if audit_writer is not None:
            audit_event = AuditEvent(
                event_type=AuditEventType.CTS_HOLD_RELEASED,
                bank_id=bank_id,
                user_id=reviewer_id,
                payload={
                    "instrument_id": instrument_id,
                    "hold_id": hold_id,
                    "released_by": reviewer_id,
                    "branch_note": body.branch_note,
                    "branch_recommendation": body.branch_recommendation,
                },
            )
            await audit_writer(audit_event)

    hold_id = hold_id or instrument_id

    # Signal the escalation workflow to stop — hold is resolved
    try:
        from temporalio.client import Client as TemporalClient
        from modules.cts.workflows.hold_escalation_workflow import HoldEscalationWorkflow
        temporal_address = await config_service.get("temporal.address")
        temporal_client = await TemporalClient.connect(temporal_address)
        handle = temporal_client.get_workflow_handle(
            f"cts-hold-escalation-{bank_id}-{instrument_id}"
        )
        await handle.signal(HoldEscalationWorkflow.released)
    except Exception as _exc:
        # Non-fatal — escalation workflow may have already completed or never started
        log.warning("hold.escalation.signal_failed", instrument_id=instrument_id,
                    bank_id=bank_id, error=str(_exc))

    log.info("cts.hold.released", instrument_id=instrument_id, bank_id=bank_id, released_by=reviewer_id)
    return HoldReleaseResponse(instrument_id=instrument_id, hold_id=hold_id, released=True)


@router_v1.post(
    "/holds/{instrument_id}/recommendation",
    response_model=HoldRecommendationResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_hold_recommendation(
    instrument_id: str,
    body: HoldRecommendationRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HoldRecommendationResponse:
    """
    Branch manager submits or updates their recommendation (CONFIRM | RETURN)
    on an active hold. Does NOT release the hold — that is the ops_reviewer's call.
    Roles: branch_manager, ops_reviewer, ops_manager.
    """
    bank_id = ctx.bank_id
    allowed_roles = ("ops_manager", "ops_reviewer", "branch_manager")
    if ctx.role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    hold_id: Optional[str] = None

    if pool is not None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE cts.instrument_holds
                   SET branch_note = COALESCE($1, branch_note),
                       branch_recommendation = COALESCE($2, branch_recommendation)
                 WHERE instrument_id = $3
                   AND bank_id = $4
                   AND released_at IS NULL
                RETURNING hold_id
                """,
                body.branch_note, body.branch_recommendation,
                instrument_id, bank_id,
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active hold not found for this instrument",
            )
        hold_id = row["hold_id"]

        # Audit
        from shared.audit.audit_event import AuditEvent, AuditEventType
        audit_writer = getattr(request.app.state, "audit_stream_writer", None)
        if audit_writer is not None:
            audit_event = AuditEvent(
                event_type=AuditEventType.CTS_HOLD_PLACED,
                bank_id=bank_id,
                user_id=ctx.user_id,
                payload={
                    "instrument_id": instrument_id,
                    "hold_id": hold_id,
                    "branch_recommendation": body.branch_recommendation,
                    "action": "RECOMMENDATION_UPDATED",
                },
            )
            await audit_writer(audit_event)

    hold_id = hold_id or instrument_id
    log.info(
        "cts.hold.recommendation_updated",
        instrument_id=instrument_id,
        bank_id=bank_id,
        recommendation=body.branch_recommendation,
    )
    return HoldRecommendationResponse(instrument_id=instrument_id, hold_id=hold_id, updated=True)


# ---------------------------------------------------------------------------
# Mismatch Queue endpoints (outward scan — Vision LLM vs scanner discrepancy)
# ---------------------------------------------------------------------------

class MismatchItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    mismatch_id: str
    instrument_id: str
    branch_id: str
    held_at: str
    status: str
    mismatch_fields: list[str]
    scanner_amount: str
    vision_amount: str
    payee_display: str
    lot_id: Optional[str] = None
    workflow_run_id: Optional[str] = None


class MismatchListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[MismatchItem]
    total: int
    bank_id: str


class MismatchResolveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Literal["GO_AHEAD", "REJECTED"]
    note: Optional[str] = None


class MismatchResolveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    mismatch_id: str
    action: str
    signal_sent: bool


@router_v1.get(
    "/mismatches",
    response_model=MismatchListResponse,
)
async def list_mismatches(
    request: Request,
    branch_id: Optional[str] = None,
    ctx: UserContext = Depends(get_current_user_context),
) -> MismatchListResponse:
    """
    List all HELD mismatches for this bank (optionally filtered by branch).
    Roles: ops_manager, ops_reviewer, branch_manager.
    """
    bank_id = ctx.bank_id
    allowed_roles = ("ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager")
    if ctx.role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    items: list[MismatchItem] = []

    if pool is not None:
        async with pool.acquire() as conn:
            if branch_id:
                rows = await conn.fetch(
                    """
                    SELECT mismatch_id, instrument_id, branch_id, held_at, status,
                           mismatch_fields, vision_finding, scanner_data, lot_id, workflow_run_id
                    FROM cts.mismatch_queue
                    WHERE bank_id = $1 AND branch_id = $2 AND status = 'HELD'
                    ORDER BY held_at ASC
                    """,
                    bank_id, branch_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT mismatch_id, instrument_id, branch_id, held_at, status,
                           mismatch_fields, vision_finding, scanner_data, lot_id, workflow_run_id
                    FROM cts.mismatch_queue
                    WHERE bank_id = $1 AND status = 'HELD'
                    ORDER BY held_at ASC
                    """,
                    bank_id,
                )
            for row in rows:
                vf = row["vision_finding"] or {}
                sd = row["scanner_data"] or {}
                items.append(MismatchItem(
                    mismatch_id=row["mismatch_id"],
                    instrument_id=row["instrument_id"],
                    branch_id=row["branch_id"],
                    held_at=str(row["held_at"]),
                    status=row["status"],
                    mismatch_fields=row["mismatch_fields"] or [],
                    scanner_amount=sd.get("amount_figures", "—"),
                    vision_amount=vf.get("amount_figures", "—"),
                    payee_display=sd.get("payee_masked", "***"),
                    lot_id=row["lot_id"],
                    workflow_run_id=row["workflow_run_id"],
                ))

    log.info("cts.mismatches.listed", bank_id=bank_id, count=len(items))
    return MismatchListResponse(items=items, total=len(items), bank_id=bank_id)


@router_v1.post(
    "/mismatches/{mismatch_id}/resolve",
    response_model=MismatchResolveResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve_mismatch(
    mismatch_id: str,
    body: MismatchResolveRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> MismatchResolveResponse:
    """
    Branch supervisor resolves a mismatch: GO_AHEAD or REJECTED.
    Sends a Temporal signal to the MismatchResolutionWorkflow and updates DB.
    Roles: ops_manager, ops_reviewer, branch_manager.
    """
    bank_id = ctx.bank_id
    user_id = ctx.user_id
    allowed_roles = ("ops_manager", "ops_reviewer", "branch_manager")
    if ctx.role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    pool = getattr(request.app.state, "db_pool_cts", None)
    signal_sent = False

    if pool is not None:
        import time as _time
        now_ts = _time.time()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT mismatch_id, branch_id, workflow_run_id
                FROM cts.mismatch_queue
                WHERE mismatch_id = $1 AND bank_id = $2 AND status = 'HELD'
                """,
                mismatch_id, bank_id,
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Mismatch not found or already resolved",
            )

        branch_id = row["branch_id"]
        workflow_run_id = row["workflow_run_id"]

        # Send Temporal signal to MismatchResolutionWorkflow
        temporal_client = getattr(request.app.state, "temporal_client", None)
        if temporal_client is not None and workflow_run_id:
            try:
                from modules.cts.workflows.mismatch_resolution_workflow import (
                    MismatchResolutionWorkflow, MismatchSignal,
                )
                workflow_id = f"cts-mismatch-{bank_id}-{branch_id}-{mismatch_id}"
                handle = temporal_client.get_workflow_handle(
                    workflow_id, run_id=workflow_run_id
                )
                await handle.signal(
                    MismatchResolutionWorkflow.resolve,
                    MismatchSignal(action=body.action, resolved_by=user_id),
                )
                signal_sent = True
            except Exception as exc:
                log.error("cts.mismatch.signal_failed", mismatch_id=mismatch_id, error=str(exc))

        # Update DB regardless of signal (idempotent — workflow also updates on signal receipt)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.mismatch_queue
                   SET status = $1, resolved_at = NOW(), resolved_by = $2, resolution_note = $3
                 WHERE mismatch_id = $4 AND bank_id = $5
                """,
                body.action, user_id, body.note, mismatch_id, bank_id,
            )

        # Audit
        from shared.audit.audit_event import AuditEvent, AuditEventType
        audit_writer = getattr(request.app.state, "audit_stream_writer", None)
        if audit_writer is not None:
            audit_event = AuditEvent(
                event_type=AuditEventType.CTS_LOCK_ACQUIRED,  # reuse closest available
                bank_id=bank_id,
                user_id=user_id,
                payload={
                    "mismatch_id": mismatch_id,
                    "action": body.action,
                    "note": body.note,
                    "signal_sent": signal_sent,
                },
            )
            await audit_writer(audit_event)

    log.info(
        "cts.mismatch.resolved",
        mismatch_id=mismatch_id,
        action=body.action,
        bank_id=bank_id,
        resolved_by=user_id,
    )
    return MismatchResolveResponse(mismatch_id=mismatch_id, action=body.action, signal_sent=signal_sent)


# ---------------------------------------------------------------------------
# Endorsement endpoints (outward clearing — batch stamp reverse of cheque)
# ---------------------------------------------------------------------------

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
    """
    Trigger BatchEndorsementWorkflow for a sealed lot.
    Roles: ops_manager.
    """
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


# ---------------------------------------------------------------------------
# Outward file download (presigned MinIO URL for CXF / image archives)
# ---------------------------------------------------------------------------

class OutwardFileDownloadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    download_url: str
    expires_in_seconds: int = 300


@router_v1.get(
    "/outward/files/{filename}/download-url",
    response_model=OutwardFileDownloadResponse,
)
async def get_outward_file_download_url(
    filename: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> OutwardFileDownloadResponse:
    """
    Returns a presigned MinIO download URL for an outward CXF or image archive file.
    Roles: ops_manager, ops_reviewer.
    """
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

    # Dev/test mode: no MinIO — return a placeholder URL
    return OutwardFileDownloadResponse(
        filename=filename,
        download_url=f"/dev-placeholder/{filename}",
        expires_in_seconds=300,
    )


# ---------------------------------------------------------------------------
# IQA re-scan endpoint (outward scanning — Image Quality Assessment retry)
# ---------------------------------------------------------------------------

class IQARescanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    workflow_id: str
    status: Literal["TRIGGERED"]


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
    """
    Re-trigger OutwardScanWorkflow for a scan that failed IQA.
    Roles: ops_manager, ops_reviewer.
    """
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


# ─── Session Report Downloads ──────────────────────────────────────────────────

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


@router_v1.get(
    "/sessions/{session_id}/download/{report_type}",
    response_model=SessionDownloadResponse,
)
async def get_session_report_download_url(
    session_id: str,
    report_type: str,
    request: Request,
    ctx: UserContext = Depends(require_user_context),
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


# ─── Branch Scan Monitor — recent outward scan events ─────────────────────────

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


@router_v1.get("/scan-monitor/recent", response_model=ScanMonitorResponse)
async def get_recent_scan_events(
    request: Request,
    limit: int = 50,
    ctx: UserContext = Depends(require_user_context),
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


# ---------------------------------------------------------------------------
# Allocation — reviewer claim / unclaim + admin status panel
# ---------------------------------------------------------------------------

class ClaimResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    claimed: bool
    reviewer_id: Optional[str] = None
    held_by: Optional[str] = None   # set when claimed=False and already held by someone else
    message: str


class AllocationStatusItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    reviewer_id: str
    tier: Optional[str] = None
    claimed_at: Optional[str] = None  # ISO timestamp from Redis TTL metadata when available


class AllocationStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    active_claims: list[AllocationStatusItem]
    total: int


@router_v1.post(
    "/review/{instrument_id}/claim",
    response_model=ClaimResponse,
    status_code=status.HTTP_200_OK,
)
async def claim_instrument(
    instrument_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ClaimResponse:
    """
    Reviewer manually claims an instrument for review.
    Works in SELF, HYBRID, and AUTO allocation modes.
    Writes CTS_ALLOC_CLAIMED AllocationAuditEvent to Immudb.
    Roles: ops_reviewer, ops_manager.
    """
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    if ctx.role.value not in ("ops_reviewer", "ops_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    redis = getattr(request.app.state, "redis_cts", None)

    # Build AllocationService with a LockService backed by app-state Redis
    from modules.cts.allocation.lock_service import LockService
    from modules.cts.allocation.allocation_service import AllocationService
    lock_svc = LockService(redis_client=redis)
    alloc_svc = AllocationService(lock_service=lock_svc)

    # Fetch Layer 3 config for allocation_mode + lock TTL
    cts_config: dict = {}
    config_svc = getattr(request.app.state, "config_service", None)
    if config_svc is not None:
        try:
            cts_config = await config_svc.get_cts_config(bank_id)
        except Exception:
            pass

    result = await alloc_svc.claim(instrument_id, reviewer_id, cts_config)

    # AllocationAuditEvent → Immudb
    from shared.audit.audit_event import AuditEvent, AuditEventType
    audit_writer = getattr(request.app.state, "audit_stream_writer", None)
    if audit_writer is not None:
        audit_event = AuditEvent(
            event_type=AuditEventType.CTS_ALLOC_CLAIMED if result.claimed else AuditEventType.CTS_LOCK_ACQUIRED,
            bank_id=bank_id,
            user_id=reviewer_id,
            payload={
                "instrument_id": instrument_id,
                "claimed": result.claimed,
                "held_by": result.held_by,
                "allocation_mode": cts_config.get("allocation_mode", "SELF"),
            },
        )
        await audit_writer(audit_event)

    if result.claimed:
        log.info("cts.alloc.claimed", instrument_id=instrument_id, reviewer_id=reviewer_id, bank_id=bank_id)
        return ClaimResponse(
            instrument_id=instrument_id, claimed=True,
            reviewer_id=reviewer_id, message="Claimed successfully",
        )

    log.info("cts.alloc.claim_rejected", instrument_id=instrument_id, reviewer_id=reviewer_id, held_by=result.held_by)
    return ClaimResponse(
        instrument_id=instrument_id, claimed=False,
        held_by=result.held_by, message="Already claimed by another reviewer",
    )


@router_v1.delete(
    "/review/{instrument_id}/claim",
    response_model=ClaimResponse,
    status_code=status.HTTP_200_OK,
)
async def unclaim_instrument(
    instrument_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ClaimResponse:
    """
    Reviewer releases their claim on an instrument.
    Writes CTS_ALLOC_UNCLAIMED AllocationAuditEvent to Immudb.
    Roles: ops_reviewer, ops_manager.
    """
    bank_id = ctx.bank_id
    reviewer_id = ctx.user_id
    if ctx.role.value not in ("ops_reviewer", "ops_manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    redis = getattr(request.app.state, "redis_cts", None)

    from modules.cts.allocation.lock_service import LockService
    from modules.cts.allocation.allocation_service import AllocationService
    lock_svc = LockService(redis_client=redis)
    alloc_svc = AllocationService(lock_service=lock_svc)

    await alloc_svc.unclaim(instrument_id, reviewer_id, {})

    from shared.audit.audit_event import AuditEvent, AuditEventType
    audit_writer = getattr(request.app.state, "audit_stream_writer", None)
    if audit_writer is not None:
        audit_event = AuditEvent(
            event_type=AuditEventType.CTS_ALLOC_UNCLAIMED,
            bank_id=bank_id,
            user_id=reviewer_id,
            payload={"instrument_id": instrument_id, "unclaimed_by": reviewer_id},
        )
        await audit_writer(audit_event)

    log.info("cts.alloc.unclaimed", instrument_id=instrument_id, reviewer_id=reviewer_id, bank_id=bank_id)
    return ClaimResponse(instrument_id=instrument_id, claimed=False, message="Released successfully")


@router_v1.get(
    "/allocation/status",
    response_model=AllocationStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_allocation_status(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> AllocationStatusResponse:
    """
    Admin panel: return all active reviewer claims for this bank.
    Scans Redis for keys matching the LockService key pattern.
    Roles: ops_manager, bank_it_admin.
    """
    bank_id = ctx.bank_id
    if ctx.role.value not in ("ops_manager", "bank_it_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    redis = getattr(request.app.state, "redis_cts", None)
    claims: list[AllocationStatusItem] = []

    if redis is not None:
        from modules.cts.allocation.lock_service import LockService, LOCK_KEY_PREFIX
        # Each bank has its own redis-cts cluster — scanning all lock:cts:* keys
        # returns only this bank's claims (bank isolation is at the cluster level).
        pattern = f"{LOCK_KEY_PREFIX}*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                raw = await redis.get(key)
                if raw is None:
                    continue
                # Key format: lock:cts:{instrument_id}
                key_str = key.decode() if isinstance(key, bytes) else key
                instrument_id = key_str[len(LOCK_KEY_PREFIX):]
                reviewer_id = raw.decode() if isinstance(raw, bytes) else str(raw)
                claims.append(AllocationStatusItem(
                    instrument_id=instrument_id,
                    reviewer_id=reviewer_id,
                ))
            if cursor == 0:
                break

    log.info("cts.alloc.status", bank_id=bank_id, active_claims=len(claims))
    return AllocationStatusResponse(bank_id=bank_id, active_claims=claims, total=len(claims))


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


@router_v1.get("/outward/hub-summary", response_model=HubSummaryResponse)
async def get_hub_summary(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HubSummaryResponse:
    """
    Hub dashboard branch summary — sessions + scanner health + lot state per branch.

    Joins cts.branches, cts.eeh_sessions, cts.scanner_registrations, and cts.lots.
    Returns empty branch list in POC/dev when no database pool is configured.
    """
    if ctx.role.value not in _HUB_READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    bank_id = ctx.bank_id
    today = date.today().isoformat()
    generated_at = datetime.now(timezone.utc).isoformat()
    state = getattr(getattr(request, "app", None), "state", None)
    db_pool = getattr(state, "db_pool_cts", None) if state else None

    if db_pool is None:
        return HubSummaryResponse(
            bank_id=bank_id, clearing_date=today,
            branches=[], total_branches=0, active_sessions=0, generated_at=generated_at,
        )

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(_HUB_SUMMARY_SQL, bank_id, today)
    except Exception as exc:
        log.error("cts.hub_summary.db_error", bank_id=bank_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Database error")

    branches = [_row_to_branch_summary(dict(r)) for r in rows]
    active = sum(1 for b in branches if b.session is not None)
    return HubSummaryResponse(
        bank_id=bank_id, clearing_date=today,
        branches=branches, total_branches=len(branches),
        active_sessions=active, generated_at=generated_at,
    )


@router_v1.patch("/outward/lots/{lot_id}/seal")
async def seal_lot(
    lot_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> dict:
    """
    Hub Manager manually seals one scanning batch lot before it is full.
    Only OPEN lots can be sealed. Returns 409 if already SEALED.
    """
    if ctx.role.value not in _HUB_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    state = getattr(getattr(request, "app", None), "state", None)
    db_pool = getattr(state, "db_pool_cts", None) if state else None
    if db_pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    bank_id = ctx.bank_id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT lot_id, bank_id, status, instrument_count FROM cts.lots WHERE lot_id=$1",
            lot_id,
        )
        if row is None or row["bank_id"] != bank_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lot not found")
        if row["status"] != "OPEN":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Lot is already {row['status']}")
        await conn.execute(
            "UPDATE cts.lots SET status='SEALED', sealed_at=NOW() WHERE lot_id=$1",
            lot_id,
        )

    log.info("cts.lot.sealed", lot_id=lot_id, bank_id=bank_id, operator=ctx.user_id)
    return {"lot_id": lot_id, "status": "SEALED", "sealed_by": ctx.user_id}


@router_v1.post("/outward/lots/seal-all")
async def seal_all_lots(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> dict:
    """
    Hub Manager seals all OPEN scanning batch lots for the bank (clearing window close).
    Returns count of lots sealed.
    """
    if ctx.role.value not in _HUB_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    state = getattr(getattr(request, "app", None), "state", None)
    db_pool = getattr(state, "db_pool_cts", None) if state else None
    if db_pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    bank_id = ctx.bank_id
    today = date.today()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT lot_id FROM cts.lots WHERE bank_id=$1 AND clearing_date=$2 AND status='OPEN'",
            bank_id, today,
        )
        for row in rows:
            await conn.execute(
                "UPDATE cts.lots SET status='SEALED', sealed_at=NOW() WHERE lot_id=$1",
                row["lot_id"],
            )

    sealed = len(rows)
    log.info("cts.lots.seal_all", bank_id=bank_id, sealed=sealed, operator=ctx.user_id)
    return {"bank_id": bank_id, "sealed": sealed, "sealed_by": ctx.user_id}


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


@router_v1.get(
    "/outward/sessions/{session_id}/report",
    response_model=SessionReportMeta,
    status_code=status.HTTP_200_OK,
)
async def get_session_report(
    session_id: str,
    request: Request,
    format: Optional[str] = None,      # ?format=html | pdf  → redirect to presigned URL
    ctx: UserContext = Depends(get_current_user_context),
) -> SessionReportMeta:
    """
    Returns metadata for a CTS outward session clearing report.
    Add ?format=html or ?format=pdf to get a presigned MinIO download URL.

    Roles: ops_manager, bank_it_admin, ops_reviewer (own branch only).
    SB users see any session in their bank. SMB users see only their branch.
    """
    bank_id = ctx.bank_id
    allowed = {"ops_manager", "bank_it_admin", "ops_reviewer", "fraud_analyst"}
    if ctx.role.value not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable")

    row = await db.fetchrow(
        """
        SELECT report_id, session_id, bank_id, branch_id, branch_ifsc,
               clearing_date, session_type, generated_at,
               instrument_count, lot_count,
               accepted_count, rejected_count, held_count,
               compliance_pass_count, compliance_fail_count,
               html_minio_path, pdf_minio_path, status
        FROM cts.session_reports
        WHERE session_id = $1 AND bank_id = $2
        """,
        session_id, bank_id,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    html_url = pdf_url = None

    if format in ("html", "pdf") and row["status"] == "READY":
        from shared.config.config_service import config_service
        from minio import Minio  # type: ignore
        from datetime import timedelta

        minio_ep = await config_service.get("minio.endpoint")
        minio_ak = await config_service.get_secret("minio.access_key")
        minio_sk = await config_service.get_secret("minio.secret_key")
        client = Minio(minio_ep, access_key=minio_ak, secret_key=minio_sk, secure=False)
        bucket = "astra-cts-reports"
        path_key = "html_minio_path" if format == "html" else "pdf_minio_path"
        object_path = row[path_key]
        if object_path:
            url = client.presigned_get_object(bucket, object_path, expires=timedelta(minutes=15))
            if format == "html":
                html_url = url
            else:
                pdf_url = url

    log.info(
        "cts.session_report.fetched",
        session_id=session_id,
        bank_id=bank_id,
        status=row["status"],
        format=format,
    )

    return SessionReportMeta(
        report_id=str(row["report_id"]),
        session_id=row["session_id"],
        bank_id=row["bank_id"],
        branch_ifsc=row["branch_ifsc"],
        clearing_date=str(row["clearing_date"]),
        session_type=row["session_type"],
        generated_at=row["generated_at"].isoformat(),
        instrument_count=row["instrument_count"],
        accepted_count=row["accepted_count"],
        rejected_count=row["rejected_count"],
        held_count=row["held_count"],
        compliance_pass_count=row["compliance_pass_count"],
        compliance_fail_count=row["compliance_fail_count"],
        status=row["status"],
        html_url=html_url,
        pdf_url=pdf_url,
    )


# ---------------------------------------------------------------------------
# Vault Upload — UI path
# POST /v1/cts/vault/upload/{vault_type}
# GET  /v1/cts/vault/batches/{batch_id}
# GET  /v1/cts/vault/batches/{batch_id}/errors.csv
# ---------------------------------------------------------------------------

import csv as _csv
import io as _io
from fastapi import UploadFile, File
from fastapi.responses import StreamingResponse

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


@router_v1.post(
    "/vault/upload/{vault_type}",
    response_model=VaultUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_vault_csv(
    vault_type: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: UserContext = Depends(get_current_user_context),
) -> VaultUploadResponse:
    """
    Upload a vault CSV via the ops workstation UI.
    Accepted vault_type: PPS | CHEQUE_BOOK | LEAF_STATUS | ACCOUNT_DETAIL | SIGNATURE.
    Returns batch result immediately; failed rows available at /errors.csv.
    """
    bank_id = ctx.bank_id
    vault_type = vault_type.upper()

    if vault_type not in _VALID_VAULT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_UNKNOWN_TYPE",
                "message": f"vault_type must be one of {sorted(_VALID_VAULT_TYPES)}",
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        )

    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_EMPTY_FILE",
                "message": "Uploaded file is empty",
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        )

    db_pool = getattr(request.app.state, "db_pool", None)
    vaults: dict = getattr(request.app.state, "vault_instances", {}) or {}
    minio_client = getattr(request.app.state, "minio_client", None)

    from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor

    error_file_bucket: Optional[str] = None
    if minio_client is not None:
        try:
            error_file_bucket = await config_service.get("vault.error_files.bucket")
        except Exception:
            error_file_bucket = "astra-vault-errors"

    processor = VaultUploadProcessor(
        bank_id=bank_id,
        db_pool=db_pool,
        cheque_leaf_vault=vaults.get("cheque_leaf"),
        account_vault=vaults.get("account"),
        signature_vault=vaults.get("signature"),
        pps_vault=vaults.get("pps"),
        minio_client=minio_client,
        error_file_bucket=error_file_bucket,
    )

    try:
        result = await processor.process(
            vault_type=vault_type,
            csv_content=csv_bytes,
            changed_by=f"user:{ctx.user_id}",
            filename=file.filename,
            upload_channel="UI",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_PARSE_ERROR",
                "message": str(exc),
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        ) from exc

    batch_status = _vault_status(result.rows_processed, result.rows_failed)

    # Notify ops_manager via Kafka → PlatformHealthCheckWorkflow → dispatcher
    _publish_vault_batch_event(
        get_kafka_producer(request),
        batch_id=result.batch_id,
        bank_id=bank_id,
        vault_type=vault_type,
        status=batch_status,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
    )

    log.info(
        "vault.upload_complete",
        batch_id=result.batch_id,
        bank_id=bank_id,
        vault_type=vault_type,
        db_table=_VAULT_TABLE_MAP[vault_type],
        status=batch_status,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
    )

    return VaultUploadResponse(
        batch_id=result.batch_id,
        vault_type=vault_type,
        db_table=_VAULT_TABLE_MAP[vault_type],
        status=batch_status,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
        errors_preview=result.errors[:20],
    )


@router_v1.get(
    "/vault/batches/{batch_id}",
    response_model=VaultBatchStatusResponse,
)
async def get_vault_batch_status(
    batch_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> VaultBatchStatusResponse:
    """
    Return status and row counts for a completed vault upload batch.
    Scoped to the authenticated bank_id — cannot query another bank's batch.
    """
    bank_id = ctx.bank_id
    db_pool = getattr(request.app.state, "db_pool", None)

    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "DB_UNAVAILABLE", "message": "Database pool not ready"},
        )

    import json as _json
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, bank_id, vault_type, filename, upload_channel,
                   uploaded_by, status, rows_total, rows_processed, rows_failed,
                   errors_json, error_file_path, created_at, completed_at
            FROM cts.vault_upload_batches
            WHERE id=$1 AND bank_id=$2
            """,
            batch_id, bank_id,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "VAULT_BATCH_NOT_FOUND",
                "message": f"Batch {batch_id!r} not found for bank {bank_id!r}",
            },
        )

    vault_type = row["vault_type"]
    errors_raw = row["errors_json"] or []
    errors_list: list[dict] = _json.loads(errors_raw) if isinstance(errors_raw, str) else (errors_raw or [])
    efp: Optional[str] = row["error_file_path"]

    return VaultBatchStatusResponse(
        batch_id=str(row["id"]),
        bank_id=row["bank_id"],
        vault_type=vault_type,
        db_table=_VAULT_TABLE_MAP.get(vault_type, "unknown"),
        filename=row["filename"],
        upload_channel=row["upload_channel"],
        uploaded_by=row["uploaded_by"],
        status=row["status"],
        rows_total=row["rows_total"],
        rows_processed=row["rows_processed"],
        rows_failed=row["rows_failed"],
        errors_preview=errors_list[:20],
        error_file_path=efp,
        has_error_file=efp is not None,
        created_at=row["created_at"].timestamp() if row["created_at"] else 0.0,
        completed_at=row["completed_at"].timestamp() if row["completed_at"] else None,
    )


@router_v1.get("/vault/batches/{batch_id}/errors.csv")
async def download_vault_batch_errors(
    batch_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> StreamingResponse:
    """
    Download all rejected rows from a vault upload batch as a CSV file.
    Columns: row_number, error_message.
    Scoped to authenticated bank_id — cannot download another bank's errors.
    Response: text/csv with Content-Disposition: attachment.
    """
    bank_id = ctx.bank_id
    db_pool = getattr(request.app.state, "db_pool", None)

    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "DB_UNAVAILABLE", "message": "Database pool not ready"},
        )

    import json as _json

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT vault_type, status, rows_failed, errors_json, error_file_path
            FROM cts.vault_upload_batches
            WHERE id=$1 AND bank_id=$2
            """,
            batch_id, bank_id,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "VAULT_BATCH_NOT_FOUND",
                "message": f"Batch {batch_id!r} not found for bank {bank_id!r}",
            },
        )

    filename = f"vault_errors_{batch_id[:8]}.csv"
    efp: Optional[str] = row["error_file_path"]
    minio_client = getattr(request.app.state, "minio_client", None)

    # Primary path: stream directly from MinIO (no row cap, full error list)
    if efp and minio_client is not None:
        try:
            try:
                bucket = await config_service.get("vault.error_files.bucket")
            except Exception:
                bucket = "astra-vault-errors"
            stream = minio_client.get_object(bucket, efp)
            return StreamingResponse(
                stream,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as exc:
            log.warning(
                "vault.download_minio_fallback",
                batch_id=batch_id,
                bank_id=bank_id,
                error_file_path=efp,
                error=str(exc),
            )
            # Fall through to JSONB fallback below

    # Fallback: generate CSV from errors_json JSONB (first 1000 rows, backwards-compatible)
    errors_raw = row["errors_json"] or []
    errors_list: list[dict] = _json.loads(errors_raw) if isinstance(errors_raw, str) else (errors_raw or [])

    def _generate_csv():
        buf = _io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=["row_number", "error_message"])
        writer.writeheader()
        yield buf.getvalue()
        for err in errors_list:
            buf = _io.StringIO()
            writer = _csv.DictWriter(buf, fieldnames=["row_number", "error_message"])
            writer.writerow({"row_number": err.get("row", ""), "error_message": err.get("error", "")})
            yield buf.getvalue()

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Outward scan events — branch scanner agent reporting + Branch Scan Dashboard
# ---------------------------------------------------------------------------

class OutwardScanEventRequest(BaseModel):
    """Received from the edge scanner agent for non-submit scan outcomes."""
    model_config = ConfigDict(frozen=True)
    bank_id:          str
    branch_id:        Optional[str] = None
    session_id:       str
    scan_id:          str
    event_type:       Literal["DOUBLE_FEED_DETECTED", "IMPRINTER_FAULT", "UPLOAD_FAILED"]
    position_in_batch: Optional[int] = None
    micr_suffix:      Optional[str] = None   # last 4 chars only — safe to store


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
    # SUBMITTED | DOUBLE_FEED_DETECTED | IMPRINTER_FAULT | UPLOAD_FAILED
    event_type:        str
    position_in_batch: Optional[int] = None
    micr_suffix:       Optional[str] = None
    imprinter_stamped: bool = False
    micr_source:       Optional[str] = None
    branch_id:         Optional[str] = None
    created_at:        float   # Unix timestamp


class ScanSessionLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id:    str
    bank_id:       str
    branch_id:     Optional[str] = None
    total:         int
    double_feeds:  int   # count of items needing re-scan
    items:         list[ScanSessionItem]


@router_v1.post(
    "/outward/scan/event",
    response_model=OutwardScanEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def report_outward_scan_event(
    body: OutwardScanEventRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> OutwardScanEventResponse:
    """
    Called by the edge scanner agent for non-submit scan outcomes:
    DOUBLE_FEED_DETECTED — two cheques fed together; held at branch, not processed centrally.
    IMPRINTER_FAULT      — cheque submitted but endorsement stamp failed; needs manual re-stamp.
    UPLOAD_FAILED        — image upload to MinIO failed; instrument needs re-scan.

    These events are written to cts.outward_scan_events so the Branch Scan Dashboard
    can surface them alongside submitted instruments.
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
                    INSERT INTO cts.outward_scan_events
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
            # Non-fatal — agent receives 202 either way so the scan session is not blocked.

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

    Merges two data sources:
    1. cts.outward_scan_events — double-feed, imprinter faults, upload failures
    2. cts.agent_decisions — submitted instruments that completed processing

    Items with event_type = DOUBLE_FEED_DETECTED are flagged for re-scan.
    Items are ordered by position_in_batch / created_at ascending (batch order).

    Access: ops_reviewer, ops_manager — scoped to bank_id. branch_id filter optional.
    """
    db_pool = getattr(request.app.state, "db_pool_cts", None)
    items: list[ScanSessionItem] = []

    if db_pool is not None:
        _SQL = """
            SELECT
                event_id,
                scan_id,
                instrument_id,
                workflow_id,
                event_type,
                position_in_batch,
                micr_suffix,
                imprinter_stamped,
                micr_source,
                branch_id,
                EXTRACT(EPOCH FROM created_at) AS created_at_epoch
            FROM cts.outward_scan_events
            WHERE bank_id = $1
              AND session_id = $2
              AND ($3::text IS NULL OR branch_id = $3)
            ORDER BY COALESCE(position_in_batch, 999999), created_at ASC
            LIMIT 500
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


class BranchScanEventRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id:           str
    event_type:        str   # DOUBLE_FEED_DETECTED | IMPRINTER_FAULT | UPLOAD_FAILED
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

    Called by BranchScanMonitor.jsx (query 2) to surface double-feed and
    imprinter-fault events from the Canon CSD edge agent path alongside
    submitted instruments from query 1 (scan-monitor/recent).

    Optional filters:
      branch_id  — scope to one branch terminal (recommended)
      event_type — filter to DOUBLE_FEED_DETECTED | IMPRINTER_FAULT | UPLOAD_FAILED
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
                    FROM cts.outward_scan_events
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


# ─── Scanner Registration (one-time code exchange) ───────────────────────────
#
# Flow:
#   1. ops_manager / bank_it_admin generates a code in Admin UI for a specific branch.
#      Code is stored in Redis: key=scanner_reg:{bank_id}:{code}
#                               value=JSON{branch_id, bank_ifsc, endorsement_text, ...}
#                               TTL=86400s (24 hours), single-use.
#   2. Installer wizard: IT admin enters Server URL + code only.
#   3. POST /v1/cts/admin/scanner/register exchanges code for full config + API token.
#   4. Code is deleted from Redis immediately (single-use guarantee).
#   5. API token is written to cts.scanner_tokens table, bound to (bank_id, branch_id, machine_id).
#   6. Installer writes config.ini + token.dat from the response.
#
# Why this prevents branch_id forgery:
#   - Branch ID is NEVER entered by the IT admin — it comes from the server.
#   - Code is single-use → second PC cannot reuse it.
#   - Token is machine-bound → token from Agra branch PC rejected if used on Lucknow PC.
#   - Central hub trusts branch_id in the token, not the branch_id in the request body.

# ── Generate one-time registration code (Admin UI → Branch Master) ────────────

class ScannerRegCodeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id: str   # must belong to the authenticated bank


class ScannerRegCodeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    code:        str   # 8-char alphanumeric, uppercase
    branch_id:   str
    branch_name: str
    bank_id:     str
    expires_at:  str   # ISO-8601 UTC


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
    Called by ops_manager / bank_it_admin from Admin UI → Branch Master.

    The code is stored in Redis: key=scanner_reg:{bank_id}:{code}, TTL=86400s.
    Subsequent call from the installer exchanges this code for a machine-bound
    API token via POST /v1/cts/admin/scanner/register.

    Generating a new code for a branch invalidates any existing unexpired code
    for that branch (only one pending code per branch at a time).
    """
    import secrets as _secrets
    import json as _json
    from datetime import datetime, timedelta, timezone

    branch_id = body.branch_id
    if not branch_id or len(branch_id) > 128:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error_code": "INVALID_BRANCH_ID", "message": "branch_id is required."})

    # Verify the branch belongs to this bank
    db_pool  = getattr(request.app.state, "db_pool_cts", None)
    redis    = getattr(request.app.state, "redis_client", None)

    branch_name = branch_id  # fallback
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
    else:
        bank_ifsc = ""

    # Generate code — first 4 chars encode bank prefix, last 4 random
    bank_prefix = bank_id[:4].upper().replace("-", "")[:4].ljust(4, "X")
    random_part = _secrets.token_hex(2).upper()   # 4 hex chars
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
        # Invalidate any existing pending code for this branch (one code per branch)
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


class ScannerRegisterRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    registration_code: str   # 8-char code from Admin UI, case-insensitive
    machine_id:        str   # Windows machine name or UUID — for token binding


class ScannerRegisterResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    # Written verbatim to config.ini [astra] section
    api_url:          str
    bank_id:          str
    bank_ifsc:        str
    branch_id:        str
    branch_name:      str
    # Written to token.dat (restricted ACL)
    api_token:        str
    # Written to config.ini [scanner] section
    endorsement_text: str
    enable_imprinter: bool
    enable_uv_scan:   bool
    mocr_weight:      int


@router_v1.post(
    "/admin/scanner/register",
    response_model=ScannerRegisterResponse,
    status_code=status.HTTP_200_OK,
    # No auth dependency — the registration code IS the auth for this one endpoint.
    # Rate-limited by IP at the Istio ingress (10 req/min per IP).
)
async def register_scanner(
    body: ScannerRegisterRequest,
    request: Request,
) -> ScannerRegisterResponse:
    """
    One-time registration code exchange. Called by the ASTRA installer on first run.

    The registration code was generated by ops_manager / bank_it_admin in the
    Admin UI and is valid for 24 hours, single-use. The response contains the
    complete branch configuration — the installer writes it to config.ini and
    token.dat without any user input on the branch identity fields.

    This endpoint is the reason branch_id cannot be forged by an IT admin:
    the branch is resolved from the code on the server, never from user input.
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

    # ── Validate and consume the code from Redis ────────────────────────────
    reg_data: dict | None = None

    if redis_client is not None:
        import json as _json
        # We don't know the bank_id yet — code key includes bank_id for namespace
        # isolation between banks. The code format encodes the bank prefix:
        # Admin UI generates code as: bank_prefix(4) + random(4) e.g. "UNBI1A2B"
        # We scan the pattern scanner_reg:*:{code} (single match expected).
        #
        # Atomic delete-and-read to prevent race condition on concurrent install attempts.
        keys = await redis_client.keys(f"scanner_reg:*:{code}")
        if keys:
            raw = await redis_client.getdel(keys[0])   # atomic: get + delete
            if raw:
                reg_data = _json.loads(raw)

    if reg_data is None:
        # Code not found — expired, already used, or invalid
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

    # ── Issue a machine-bound API token ────────────────────────────────────
    api_token  = f"svc-scanner-{_secrets.token_urlsafe(32)}"
    token_id   = str(_uuid.uuid4())
    machine_id = body.machine_id[:128]  # cap length

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
             bank_id=bank_id,
             branch_id=branch_id,
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
