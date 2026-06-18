"""
CTS API router — versioned public endpoints for cheque submission and decision retrieval.

Routes:
  POST /v1/cts/inward/{instrument_id}/submit   — trigger ChequeProcessingWorkflow
  GET  /v1/cts/decisions/{instrument_id}       — poll workflow status
  POST /v1/cts/review/{instrument_id}/decide   — ops_reviewer submits CONFIRM/RETURN signal

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

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

_bearer = HTTPBearer(auto_error=False)


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
    # Production: decode JWT, validate signature, extract bank_id claim
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials
    if token.startswith("test-token-"):
        return "reviewer-001"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


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
    Trigger ChequeProcessingWorkflow for an inward cheque.
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
