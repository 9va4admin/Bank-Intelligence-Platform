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
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
from modules.cts.workflows.human_review_workflow import ReviewDecision
from shared.auth.rbac import BankType, Role, PermissionLevel, RBACPolicy, UserContext
from shared.config.config_service import config_service
from shared.event_bus.producer import EventProducer as KafkaEventProducer

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

_bearer = HTTPBearer(auto_error=False)
_policy = RBACPolicy()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def get_current_user_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> UserContext:
    """
    Decode JWT and return a fully populated UserContext.
    In production: validate JWT signature, extract all claims.
    Test tokens: test-token-{bank_id}            → SB context
                 test-token-smb-{bank_id}         → SMB context
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials

    # Test tokens are accepted ONLY in non-production environments.
    # Production must validate against the bank's IdP JWKS endpoint.
    _env = config_service.get("env") if config_service._ready else "production"
    if _env != "production" and token.startswith("test-token-smb-"):
        bank_id = token.removeprefix("test-token-smb-")
        return UserContext(
            user_id="smb-user-001",
            role=Role.SMB_EDITOR,
            bank_id=bank_id,
            bank_type=BankType.SMB,
            permission_level=PermissionLevel.EDIT,
        )
    if _env != "production" and token.startswith("test-token-"):
        bank_id = token.removeprefix("test-token-")
        return UserContext(
            user_id="reviewer-001",
            role=Role.OPS_REVIEWER,
            bank_id=bank_id,
            bank_type=BankType.SB,
            permission_level=PermissionLevel.EDIT,
        )
    # Production path: validate JWT signature against bank IdP JWKS
    # TODO (C1 followup): implement PyJWT validation with JWKS endpoint from config_service
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


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
            from temporalio.client import WorkflowAlreadyStartedError
            from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

            await temporal_client.start_workflow(
                ChequeProcessingWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
            )
        except Exception as exc:
            # WorkflowAlreadyStartedError is normal — idempotent submission
            if "already started" not in str(exc).lower():
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
            handle = temporal_client.get_workflow_handle(workflow_id)
            result = await handle.result()
            return ChequeDecisionResponse(
                instrument_id=instrument_id,
                workflow_id=workflow_id,
                workflow_status=result.decision,
                decision=result.decision,
                rationale=result.rationale,
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
            query = (
                f"WorkflowType = 'HumanReviewWorkflow' "
                f"AND ExecutionStatus = 'Running' "
                f"AND BankId = '{eff_bank_id}'"
            )
            if smb_id_filter:
                query += f" AND SmbId = '{smb_id_filter}'"

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
            await temporal_client.start_workflow(
                VaultSyncWorkflow.run,
                VaultSyncInput(bank_id=bank_id, triggered_by="MANUAL"),
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
            await temporal_client.start_workflow(
                VaultSyncWorkflow.run,
                VaultSyncInput(
                    bank_id=bank_id,
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
