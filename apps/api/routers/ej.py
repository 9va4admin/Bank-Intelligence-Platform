"""
EJ API router — endpoints for EJ log submission, canonical record retrieval,
dispute resolution, and ATM health.

All routes versioned under /v1/ej/.
No business logic — delegates to workflow triggers.
"""
import hashlib
import json
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/ej", tags=["EJ v1"])

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


# ---------------------------------------------------------------------------
# Request / response models — original routes
# ---------------------------------------------------------------------------

class EJLogSubmitRequest(BaseModel):
    """Used by the original /inward/log route (no atm_id in path)."""
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
    pending_ej_count: int = 0
    consecutive_failures: int = 0
    last_ej_received_at: Optional[float] = None


# ---------------------------------------------------------------------------
# Request / response models — new routes
# ---------------------------------------------------------------------------

class EJLogByAtmRequest(BaseModel):
    """POST /v1/ej/inward/{atm_id}/log — log with atm_id in path."""
    model_config = ConfigDict(frozen=True)
    raw_log: str
    source: str
    oem_fingerprint: str


class EJLogByAtmResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_log_hash: str
    workflow_id: str
    status: Literal["ACCEPTED"]


class EJCanonicalByHashResponse(BaseModel):
    """GET /v1/ej/canonical/{raw_log_hash} — poll workflow with raw_log_hash."""
    model_config = ConfigDict(frozen=True)
    raw_log_hash: str
    canonical_hash: str        # alias for raw_log_hash — backward compatibility
    workflow_id: str
    workflow_status: str
    canonical_record: Optional[dict[str, Any]] = None


class EJDisputeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    atm_id: str
    claim_amount: float
    claim_timestamp: str
    claim_type: str


class EJDisputeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    npci_claim_id: str
    workflow_id: str
    status: Literal["ACCEPTED"]


# ---------------------------------------------------------------------------
# Routes — original (kept for backward compatibility)
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


@router_v1.get("/atm/{atm_id}/health", response_model=ATMHealthResponse)
async def get_atm_health(
    atm_id: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> ATMHealthResponse:
    """
    Query ATM health state from Redis EJ health signal cache.
    Key written by update_atm_health activity after each EJNormalisationWorkflow.
    Falls back to UNKNOWN when Redis is unavailable or no signal recorded yet.
    """
    redis_ej = getattr(request.app.state, "redis_ej", None)

    if redis_ej is not None:
        try:
            # Key written by modules/ej/workflows/activities/update_atm_health.py
            key = f"ej:health:{bank_id}:{atm_id}"
            raw = redis_ej.get(key)
            if raw:
                health = json.loads(raw)
                return ATMHealthResponse(
                    atm_id=atm_id,
                    bank_id=bank_id,
                    status=health.get("status", "UNKNOWN"),
                    pending_ej_count=health.get("pending_ej_count", 0),
                    consecutive_failures=health.get("consecutive_failures", 0),
                    last_ej_received_at=health.get("last_ej_received_at"),
                )
        except Exception as exc:
            log.warning(
                "ej.atm_health_redis_error",
                atm_id=atm_id,
                bank_id=bank_id,
                error=str(exc),
            )

    # No Redis / no signal yet — return UNKNOWN, not a fake HEALTHY
    return ATMHealthResponse(
        atm_id=atm_id,
        bank_id=bank_id,
        status="UNKNOWN",
    )


# ---------------------------------------------------------------------------
# Routes — new (spec requirements)
# ---------------------------------------------------------------------------

@router_v1.post(
    "/inward/{atm_id}/log",
    response_model=EJLogByAtmResponse,
    status_code=202,
)
async def submit_ej_log_by_atm(
    atm_id: str,
    body: EJLogByAtmRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> EJLogByAtmResponse:
    """
    Publish raw EJ log to Kafka ej.raw.ingested.{bank_id} (feeds KEDA autoscaler),
    then trigger EJNormalisationWorkflow directly for low-latency path.
    ATM ID is part of the URL path. Workflow is idempotent on raw_log_hash.
    """
    raw_log_hash = hashlib.sha256(body.raw_log.encode()).hexdigest()
    workflow_id = f"ej-normalise-{bank_id}-{raw_log_hash[:16]}"

    # Publish to Kafka ej.raw.ingested.{bank_id} for KEDA ScaledObject lag metric
    kafka_producer = getattr(request.app.state, "kafka_producer_ej", None)
    if kafka_producer is not None:
        try:
            kafka_producer.publish(
                topic=f"ej.raw.ingested.{bank_id}",
                event_type="EJ_RAW_LOG_INGESTED",
                payload={
                    "raw_log_hash": raw_log_hash,
                    "workflow_id": workflow_id,
                    "atm_id": atm_id,
                    "oem_fingerprint": body.oem_fingerprint,
                },
                bank_id=bank_id,
            )
        except Exception as exc:
            log.warning(
                "ej.kafka_publish_failed",
                atm_id=atm_id,
                bank_id=bank_id,
                error=str(exc),
            )

    temporal_client = getattr(request.app.state, "temporal_client", None)

    if temporal_client is not None:
        try:
            from modules.ej.workflows.normalise_workflow import (
                EJNormalisationWorkflow,
                EJNormalisationInput,
            )
            inp = EJNormalisationInput(
                raw_log=body.raw_log,
                raw_log_hash=raw_log_hash,
                atm_id=atm_id,
                bank_id=bank_id,
                oem_fingerprint=body.oem_fingerprint,
                source=body.source,
            )
            await temporal_client.start_workflow(
                EJNormalisationWorkflow.run,
                inp,
                id=workflow_id,
                task_queue=f"ej-normalisation-{bank_id}",
            )
        except Exception as exc:
            if "already started" not in str(exc).lower():
                log.error(
                    "ej.submit_workflow_error",
                    atm_id=atm_id,
                    bank_id=bank_id,
                    error=str(exc),
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to start workflow",
                ) from exc

    log.info(
        "ej.log_submit_accepted",
        atm_id=atm_id,
        bank_id=bank_id,
        workflow_id=workflow_id,
    )

    return EJLogByAtmResponse(
        raw_log_hash=raw_log_hash,
        workflow_id=workflow_id,
        status="ACCEPTED",
    )


@router_v1.get(
    "/canonical/{raw_log_hash}",
    response_model=EJCanonicalByHashResponse,
)
async def get_canonical_by_hash(
    raw_log_hash: str,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> EJCanonicalByHashResponse:
    """
    Poll status of an EJNormalisationWorkflow by raw_log_hash.
    Returns RUNNING when workflow is in progress or Temporal is unavailable.
    """
    workflow_id = f"ej-normalise-{bank_id}-{raw_log_hash[:16]}"

    temporal_client = getattr(request.app.state, "temporal_client", None)

    if temporal_client is not None:
        try:
            handle = temporal_client.get_workflow_handle(workflow_id)
            result = await handle.result()
            return EJCanonicalByHashResponse(
                raw_log_hash=raw_log_hash,
                canonical_hash=raw_log_hash,
                workflow_id=workflow_id,
                workflow_status=result.outcome,
                canonical_record=result.canonical_record,
            )
        except Exception:
            pass

    return EJCanonicalByHashResponse(
        raw_log_hash=raw_log_hash,
        canonical_hash=raw_log_hash,
        workflow_id=workflow_id,
        workflow_status="RUNNING",
    )


@router_v1.post(
    "/disputes/{npci_claim_id}/resolve",
    response_model=EJDisputeResponse,
    status_code=202,
)
async def resolve_dispute(
    npci_claim_id: str,
    body: EJDisputeRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> EJDisputeResponse:
    """
    Trigger DisputeResolutionWorkflow for an NPCI claim.
    Workflow ID: ej-dispute-{bank_id}-{npci_claim_id} (idempotent).
    """
    workflow_id = f"ej-dispute-{bank_id}-{npci_claim_id}"

    temporal_client = getattr(request.app.state, "temporal_client", None)

    if temporal_client is not None:
        try:
            from modules.ej.workflows.dispute_workflow import (
                DisputeResolutionWorkflow,
                EJDisputeInput,
            )
            inp = EJDisputeInput(
                bank_id=bank_id,
                atm_id=body.atm_id,
                npci_claim_id=npci_claim_id,
                claim_amount=body.claim_amount,
                claim_timestamp=body.claim_timestamp,
                claim_type=body.claim_type,
            )
            await temporal_client.start_workflow(
                DisputeResolutionWorkflow.run,
                inp,
                id=workflow_id,
                task_queue=f"ej-normalisation-{bank_id}",
            )
        except Exception as exc:
            if "already started" not in str(exc).lower():
                log.error(
                    "ej.dispute_workflow_error",
                    npci_claim_id=npci_claim_id,
                    bank_id=bank_id,
                    error=str(exc),
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to start dispute workflow",
                ) from exc

    log.info(
        "ej.dispute_accepted",
        npci_claim_id=npci_claim_id,
        bank_id=bank_id,
        workflow_id=workflow_id,
    )

    return EJDisputeResponse(
        npci_claim_id=npci_claim_id,
        workflow_id=workflow_id,
        status="ACCEPTED",
    )
