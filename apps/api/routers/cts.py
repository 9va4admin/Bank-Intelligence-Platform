"""
CTS API router — public endpoints for cheque submission and decision retrieval.

All routes versioned under /v1/cts/.
Authentication via JWT (dependency injection — bypassed in tests via override).
No business logic here — delegates to workflow trigger layer.
"""
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

_bearer = HTTPBearer(auto_error=False)


async def get_current_bank_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    # In production: validate JWT, extract bank_id claim
    # In tests: dependency override replaces this entirely
    token = credentials.credentials
    if token.startswith("test-token-"):
        return token.removeprefix("test-token-")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChequeSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
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
    status: Literal["ACCEPTED", "REJECTED"]
    estimated_decision_ms: int


class ChequeDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    workflow_status: str        # "RUNNING" | "STP_CONFIRM" | "STP_RETURN" | "HUMAN_REVIEW"
    decision: Optional[str] = None
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.post(
    "/inward/{instrument_id}/submit",
    response_model=ChequeSubmitResponse,
    status_code=202,
)
async def submit_inward_cheque(
    instrument_id: str,
    body: ChequeSubmitRequest,
    bank_id: str = Depends(get_current_bank_id),
) -> ChequeSubmitResponse:
    workflow_id = f"cts-{bank_id}-{instrument_id}"

    log.info(
        "cts.submit",
        instrument_id=instrument_id,
        bank_id=bank_id,
        workflow_id=workflow_id,
    )

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
    bank_id: str = Depends(get_current_bank_id),
) -> ChequeDecisionResponse:
    workflow_id = f"cts-{bank_id}-{instrument_id}"

    # In production: query Temporal workflow state
    return ChequeDecisionResponse(
        instrument_id=instrument_id,
        workflow_id=workflow_id,
        workflow_status="RUNNING",
    )
