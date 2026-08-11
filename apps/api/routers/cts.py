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

    workflow_input = ChequeWorkflowInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        image_url=body.image_url,
        account_number=body.account_number,
        cheque_number=body.cheque_number,
        presented_amount=body.presented_amount,
        presented_payee=body.presented_payee,
        iet_deadline=body.iet_deadline,
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
            from temporalio.exceptions import WorkflowAlreadyStartedError
            from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

            await temporal_client.start_workflow(
                ChequeProcessingWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Schedule does not belong to your bank")
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Schedule does not belong to your bank")
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Schedule does not belong to your bank")
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
        pu_id=body.pu_id,
        branch_id=body.branch_id,
    )

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from temporalio.exceptions import WorkflowAlreadyStartedError
            await temporal_client.start_workflow(
                OutwardScanWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
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
                    WHERE branch_id = $1 AND status = 'HELD'
                    ORDER BY held_at ASC
                    """,
                    branch_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT mq.mismatch_id, mq.instrument_id, mq.branch_id, mq.held_at,
                           mq.status, mq.mismatch_fields, mq.vision_finding, mq.scanner_data,
                           mq.lot_id, mq.workflow_run_id
                    FROM cts.mismatch_queue mq
                    JOIN cts.cheque_instruments ci
                        ON mq.instrument_id = ci.instrument_id::TEXT
                        AND ci.bank_id = $1
                    WHERE mq.status = 'HELD'
                    ORDER BY mq.held_at ASC
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
                WHERE mismatch_id = $1 AND status = 'HELD'
                """,
                mismatch_id,
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
                 WHERE mismatch_id = $4
                """,
                body.action, user_id, body.note, mismatch_id,
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
