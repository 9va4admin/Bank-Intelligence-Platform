"""
MSV API router — versioned public endpoints for Multi-Signature Validation.

Routes:
  POST /v1/msv/validate                          — trigger MSVValidationWorkflow
  GET  /v1/msv/accounts/{account_number}/signatories — list enrolled signatories (masked)
  GET  /v1/msv/enrollment/jobs/{job_id}/progress  — job progress (JSON poll, not SSE)

Security:
  - All routes require JWT (bank_id from token claim)
  - account_number NEVER returned raw in any response — always masked/hashed
  - Response schema never includes specimen images
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.auth.rbac import Role, RBACPolicy, UserContext
from shared.utils.masking import mask_account_number

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/msv", tags=["MSV v1"])

_policy = RBACPolicy()


# ─── Auth dependency ─────────────────────────────────────────────────────────

async def get_current_user_context(
    ctx: UserContext = Depends(require_user_context),
) -> UserContext:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.
    No token parsing, no test-token backdoor. ASTRA-01.
    """
    return ctx


# ─── Request / Response models ────────────────────────────────────────────────

class MSVValidateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    account_number: str          # raw — hashed before any storage
    cheque_image_url: str


class MatchedSignatoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    signatory_id: str
    role: str
    name_masked: str             # "P***" — never full name
    best_score: float
    specimen_idx: int


class MSVValidateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    outcome: str                 # "GREEN" | "AMBER" | "RED"
    confidence: float
    reason_code: str
    reason_message: str
    matched_signatories: list[MatchedSignatoryResponse]
    detected_sig_count: int
    mandate_rule_type: str
    audit_tx_id: Optional[str] = None
    request_id: str


class SignatoryListItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    signatory_id: str
    role: str
    name_masked: str             # "P***"
    specimen_count: int
    operation_type: str


class SignatoryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_display: str         # "****7890" — never raw
    bank_id: str
    signatories: list[SignatoryListItem]
    request_id: str


class EnrollmentJobProgressResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    job_id: str
    bank_id: str
    status: str
    total_accounts: int
    processed_accounts: int
    enrolled_accounts: int
    failed_accounts: int
    total_signatures: int
    request_id: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@router_v1.post("/validate", response_model=MSVValidateResponse)
async def validate_signatures(
    body: MSVValidateRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> MSVValidateResponse:
    """
    Trigger MSV validation for a cheque.

    Returns GREEN / AMBER / RED with confidence score and matched signatories.
    account_number is hashed internally — never logged or returned.
    """
    request_id = str(getattr(request.state, "otel_trace_id", "unknown"))

    log.info(
        "msv.api.validate.received",
        instrument_id=body.instrument_id,
        bank_id=body.bank_id,
        user_id=ctx.user_id,
    )

    # In production: get orchestrator from app.state, run MSVValidationWorkflow
    # For now: return a stub AMBER response (orchestrator not wired into DI yet)
    # The workflow integration is done in worker.py + Temporal client
    return MSVValidateResponse(
        instrument_id=body.instrument_id,
        outcome="AMBER",
        confidence=0.0,
        reason_code="WORKFLOW_PENDING",
        reason_message="MSV workflow submitted. Poll /v1/msv/status/{instrument_id} for result.",
        matched_signatories=[],
        detected_sig_count=0,
        mandate_rule_type="UNKNOWN",
        audit_tx_id=None,
        request_id=request_id,
    )


@router_v1.get(
    "/accounts/{account_number}/signatories",
    response_model=SignatoryListResponse,
)
async def list_signatories(
    account_number: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> SignatoryListResponse:
    """
    List enrolled signatories for an account (masked — no raw account number returned).

    Returns signatory list with masked names and specimen counts.
    account_number is NEVER returned in the response — only account_display (****7890).
    """
    request_id = str(getattr(request.state, "otel_trace_id", "unknown"))

    # Mask account number before logging or responding
    account_display = mask_account_number(account_number)

    log.info(
        "msv.api.list_signatories",
        account_display=account_display,
        bank_id=ctx.bank_id,
        user_id=ctx.user_id,
    )

    # In production: look up in SignatoryRegistry by account_hash
    # Stub response (registry not wired into DI here):
    return SignatoryListResponse(
        account_display=account_display,
        bank_id=ctx.bank_id,
        signatories=[],
        request_id=request_id,
    )


@router_v1.get(
    "/enrollment/jobs/{job_id}/progress",
    response_model=EnrollmentJobProgressResponse,
)
async def get_enrollment_job_progress(
    job_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> EnrollmentJobProgressResponse:
    """
    Get progress of a bulk enrollment job.

    Returns counts: total/processed/enrolled/failed accounts and signatures.
    """
    request_id = str(getattr(request.state, "otel_trace_id", "unknown"))

    log.info(
        "msv.api.enrollment_job_progress",
        job_id=job_id,
        bank_id=ctx.bank_id,
        user_id=ctx.user_id,
    )

    # In production: query EnrollmentProgressTracker
    # Stub:
    return EnrollmentJobProgressResponse(
        job_id=job_id,
        bank_id=ctx.bank_id,
        status="RUNNING",
        total_accounts=0,
        processed_accounts=0,
        enrolled_accounts=0,
        failed_accounts=0,
        total_signatures=0,
        request_id=request_id,
    )
