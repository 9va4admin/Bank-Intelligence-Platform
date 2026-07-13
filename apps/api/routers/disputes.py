"""
Disputes API router — NPCI ATM dispute management with EJ matching and CCTV evidence.

All routes versioned under /v1/disputes/.
Read roles: ops_manager, fraud_analyst, compliance_officer.
Write roles (resolve, escalate, ingest): ops_manager, bank_it_admin, fraud_analyst
  — compliance_officer is read-only.

No PII in any response:
  - Account numbers masked to ****{last4}
  - Amounts as range buckets (never exact)
  - No customer names — ATM ID and dispute ID only
  - CCTV evidence: MinIO reference links only, never binary content
"""
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/disputes", tags=["Disputes v1"])

_READ_ROLES = {"ops_manager", "fraud_analyst", "compliance_officer", "bank_it_admin"}
_WRITE_ROLES = {"ops_manager", "fraud_analyst"}
_INGEST_ROLES = {"ops_manager", "bank_it_admin"}


async def get_current_user(
    ctx: UserContext = Depends(require_user_context),
) -> dict[str, Any]:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.
    Re-shaped to this router's existing dict-based downstream code.
    No token parsing, no test-token backdoor. ASTRA-01.
    """
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def require_read_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot access dispute routes",
        )
    return user


def require_write_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot modify disputes",
        )
    return user


def require_ingest_role(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _INGEST_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.get('role')}' cannot ingest NPCI claims",
        )
    return user


# ── Response models ──────────────────────────────────────────────────────────

class EJMatchSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    ej_canonical_id: str
    atm_id: str
    transaction_date: str
    match_confidence: float
    dispense_status: Optional[Literal["DISPENSED", "NOT_DISPENSED", "PARTIAL", "UNKNOWN"]] = None


class DisputeSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    dispute_id: str             # format: dispute-{bank_id}-{npci_claim_id}
    npci_claim_id: str
    atm_id: str
    claimed_amount_range: str   # range bucket — never exact amount
    claim_date: str
    resolution_status: Literal["OPEN", "AUTO_RESOLVED", "ESCALATED", "FILED_TO_NPCI", "CLOSED"]
    created_at: str


class DisputeDetail(BaseModel):
    model_config = ConfigDict(frozen=True)
    dispute_id: str
    npci_claim_id: str
    atm_id: str
    claimed_amount_range: str
    claim_date: str
    resolution_status: Literal["OPEN", "AUTO_RESOLVED", "ESCALATED", "FILED_TO_NPCI", "CLOSED"]
    ej_match: Optional[EJMatchSummary] = None
    cctv_evidence_count: int
    resolution_notes: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str


class DisputesListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    disputes: list[DisputeSummary]
    total: int
    limit: int
    next_cursor: Optional[str] = None


class DisputeResolveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    resolution: Literal["DISPENSED_CONFIRMED", "NOT_DISPENSED_CONFIRMED", "PARTIAL_DISPENSE"]
    notes: Optional[str] = None


class DisputeResolveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    dispute_id: str
    resolution_status: Literal["AUTO_RESOLVED", "CLOSED"]
    resolved_by: str
    resolved_at: str


class DisputeEscalateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    reason: str = Field(..., min_length=10)


class DisputeEscalateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    dispute_id: str
    resolution_status: Literal["ESCALATED", "FILED_TO_NPCI"]
    escalated_by: str
    escalated_at: str


class CCTVEvidenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: str
    atm_id: str
    camera_id: str
    clip_timestamp: str
    duration_seconds: int
    minio_reference: str        # MinIO object path — caller fetches via pre-signed URL separately
    # Never: binary clip content, raw file path, or customer biometric data


class EvidenceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    dispute_id: str
    evidence: list[CCTVEvidenceSummary]
    total: int


class DisputeIngestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    npci_claim_id: str
    atm_id: str
    claimed_amount_range: str   # caller must provide range bucket — never accept exact amount
    claim_date: str
    # account_number is intentionally NOT a field — enforces PII boundary at schema level


class DisputeIngestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    dispute_id: str
    npci_claim_id: str
    status: Literal["INGESTED", "DUPLICATE"]
    workflow_id: str            # DisputeResolutionWorkflow ID triggered
    ingested_at: str


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.get("", response_model=DisputesListResponse)
async def list_disputes(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    dispute_status: Optional[str] = Query(default=None),
    atm_id: Optional[str] = Query(default=None),
    user: dict = Depends(require_read_role),
) -> DisputesListResponse:
    bank_id = user["bank_id"]

    log.info("disputes.list", bank_id=bank_id, limit=limit,
             dispute_status=dispute_status, atm_id=atm_id)

    # In production: SELECT dispute_id, npci_claim_id, atm_id, claimed_amount_range,
    # claim_date, resolution_status, created_at FROM ej.dispute_cases
    # WHERE bank_id=? [AND resolution_status=?] [AND atm_id=?]
    # ORDER BY created_at DESC — cursor pagination on (created_at, dispute_id).
    return DisputesListResponse(
        disputes=[],
        total=0,
        limit=limit,
        next_cursor=None,
    )


@router_v1.get("/{dispute_id}", response_model=DisputeDetail)
async def get_dispute(
    dispute_id: str,
    user: dict = Depends(require_read_role),
) -> DisputeDetail:
    bank_id = user["bank_id"]

    log.info("disputes.get", bank_id=bank_id, dispute_id=dispute_id)

    # In production: SELECT explicit columns FROM ej.dispute_cases
    # JOIN ej.ej_canonical_records ON ej_match_id
    # WHERE dispute_id=? AND bank_id=?
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")


@router_v1.post("/{dispute_id}/resolve", response_model=DisputeResolveResponse)
async def resolve_dispute(
    dispute_id: str,
    body: DisputeResolveRequest,
    user: dict = Depends(require_write_role),
) -> DisputeResolveResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("disputes.resolve", bank_id=bank_id, dispute_id=dispute_id,
             resolution=body.resolution, resolved_by=user_id)

    # In production: verify dispute exists and is OPEN, update resolution_status,
    # write audit event to Immudb, trigger notification to relevant parties.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")


@router_v1.post("/{dispute_id}/escalate", response_model=DisputeEscalateResponse, status_code=202)
async def escalate_dispute(
    dispute_id: str,
    body: DisputeEscalateRequest,
    user: dict = Depends(require_write_role),
) -> DisputeEscalateResponse:
    bank_id = user["bank_id"]
    user_id = user["user_id"]

    log.info("disputes.escalate", bank_id=bank_id, dispute_id=dispute_id,
             escalated_by=user_id)

    # In production: trigger DisputeResolutionWorkflow signal → ESCALATED state,
    # package evidence bundle, file to NPCI, write audit event.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")


@router_v1.get("/{dispute_id}/evidence", response_model=EvidenceListResponse)
async def list_evidence(
    dispute_id: str,
    user: dict = Depends(require_read_role),
) -> EvidenceListResponse:
    bank_id = user["bank_id"]

    log.info("disputes.evidence", bank_id=bank_id, dispute_id=dispute_id)

    # In production: SELECT evidence_id, atm_id, camera_id, clip_timestamp,
    # duration_seconds, minio_reference FROM ej.cctv_evidences
    # WHERE dispute_id=? AND bank_id=?
    # Caller uses minio_reference to generate a pre-signed URL for viewing — never return binary.
    return EvidenceListResponse(
        dispute_id=dispute_id,
        evidence=[],
        total=0,
    )


@router_v1.post("/ingest", response_model=DisputeIngestResponse, status_code=202)
async def ingest_npci_claim(
    body: DisputeIngestRequest,
    user: dict = Depends(require_ingest_role),
) -> DisputeIngestResponse:
    bank_id = user["bank_id"]

    log.info("disputes.ingest", bank_id=bank_id, npci_claim_id=body.npci_claim_id,
             atm_id=body.atm_id, amount_range=body.claimed_amount_range)

    # In production: check idempotency (dispute-{bank_id}-{npci_claim_id}),
    # write to ej.dispute_cases, trigger DisputeResolutionWorkflow.
    dispute_id = f"dispute-{bank_id}-{body.npci_claim_id}"
    workflow_id = f"ej-dispute-{bank_id}-{body.npci_claim_id}"

    return DisputeIngestResponse(
        dispute_id=dispute_id,
        npci_claim_id=body.npci_claim_id,
        status="INGESTED",
        workflow_id=workflow_id,
        ingested_at=datetime.now(timezone.utc).isoformat(),
    )
