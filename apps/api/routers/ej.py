"""
EJ API router — endpoints for EJ log submission and record retrieval.

All routes versioned under /v1/ej/.
No business logic — delegates to workflow triggers.
"""
import hashlib
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/ej", tags=["EJ v1"])

_bearer = HTTPBearer(auto_error=False)


async def get_current_bank_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    return "default-bank"  # in production: extract from JWT claims


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class EJLogSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_log: str
    atm_id: str
    bank_id: str
    source: str


class EJLogSubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    raw_log_hash: str
    status: Literal["ACCEPTED", "REJECTED"]


class EJCanonicalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    canonical_hash: str
    bank_id: str
    workflow_status: str
    canonical_record: Optional[dict[str, Any]] = None


class ATMHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    atm_id: str
    bank_id: str
    status: str             # "HEALTHY" | "DEGRADED" | "CRITICAL" | "UNKNOWN"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.post("/inward/log", response_model=EJLogSubmitResponse, status_code=202)
async def submit_ej_log(
    body: EJLogSubmitRequest,
    bank_id: str = Depends(get_current_bank_id),
) -> EJLogSubmitResponse:
    raw_log_hash = hashlib.sha256(body.raw_log.encode()).hexdigest()
    workflow_id = f"ej-normalise-{bank_id}-{raw_log_hash}"

    log.info("ej.submit", atm_id=body.atm_id, bank_id=bank_id, workflow_id=workflow_id)

    return EJLogSubmitResponse(
        workflow_id=workflow_id,
        raw_log_hash=raw_log_hash,
        status="ACCEPTED",
    )


@router_v1.get("/canonical/{canonical_hash}", response_model=EJCanonicalResponse)
async def get_canonical_record(
    canonical_hash: str,
    bank_id: str = Depends(get_current_bank_id),
) -> EJCanonicalResponse:
    # In production: query YugabyteDB ej schema
    return EJCanonicalResponse(
        canonical_hash=canonical_hash,
        bank_id=bank_id,
        workflow_status="NORMALISED",
    )


@router_v1.get("/atm/{atm_id}/health", response_model=ATMHealthResponse)
async def get_atm_health(
    atm_id: str,
    bank_id: str = Depends(get_current_bank_id),
) -> ATMHealthResponse:
    # In production: query EJ health signals from Redis / YugabyteDB time-series
    return ATMHealthResponse(
        atm_id=atm_id,
        bank_id=bank_id,
        status="HEALTHY",
    )
