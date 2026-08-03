"""
IFSC validator activity — confirm the instrument's IFSC is in the bank's registry.

Inward (drawee) pipeline use-case:
  NGCH presentment arrives with an IFSC. We check it belongs to us (our bank_id,
  optionally scoped to an SMB we sponsor). If the IFSC is unknown or inactive we
  route to HUMAN_REVIEW before burning CBS/PPS/signature resources.

Outcomes:
  PROCEED       — IFSC found and ACTIVE in registry
  HUMAN_REVIEW  — IFSC not found / INACTIVE / PENDING / registry unavailable
    reason=IFSC_NOT_IN_REGISTRY     → return_reason_code=36 (WRONGLY_DELIVERED)
    reason=IFSC_BRANCH_INACTIVE     → branch closed / effective_till passed
    reason=IFSC_NOT_YET_APPROVED    → entry exists but still PENDING maker-checker
    reason=IFSC_REGISTRY_UNAVAILABLE → DB down (degraded=True, never blocks clearing)

Graceful degradation:
  Registry down → HUMAN_REVIEW with degraded=True.
  This is consistent with the VAULT_MISS invariant:
  "never block clearing on infrastructure failure — route to human eyes."
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()


class IFSCValidatorInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    ifsc_to_validate: str    # IFSC from NGCH presentment metadata
    smb_id: Optional[str] = None  # set when instrument tagged to a sub-member bank


class IFSCValidatorResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                           # "PROCEED" | "HUMAN_REVIEW"
    reason: Optional[str] = None
    return_reason_code: Optional[str] = None  # "36" on WRONGLY_DELIVERED
    degraded: bool = False


@activity.defn
async def validate_ifsc(
    inp: IFSCValidatorInput,
    repo=None,
) -> IFSCValidatorResult:
    """
    Verify the IFSC is registered and active for this bank (and optionally SMB).

    Never raises — degrades to HUMAN_REVIEW on any infrastructure failure.
    """
    if repo is None:
        log.warning(
            "ifsc_validator.no_repo",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )
        return IFSCValidatorResult(
            outcome="HUMAN_REVIEW",
            reason="IFSC_REGISTRY_UNAVAILABLE",
            degraded=True,
        )

    try:
        entry = await repo.lookup_ifsc(
            inp.bank_id,
            inp.ifsc_to_validate,
            smb_id=inp.smb_id,
            active_only=False,  # fetch any status so we can give a specific reason
        )
    except Exception as exc:
        log.warning(
            "ifsc_validator.registry_error",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return IFSCValidatorResult(
            outcome="HUMAN_REVIEW",
            reason="IFSC_REGISTRY_UNAVAILABLE",
            degraded=True,
        )

    if entry is None:
        log.info(
            "ifsc_validator.not_found",
            instrument_id=inp.instrument_id,
            ifsc=inp.ifsc_to_validate,
            bank_id=inp.bank_id,
        )
        return IFSCValidatorResult(
            outcome="HUMAN_REVIEW",
            reason="IFSC_NOT_IN_REGISTRY",
            return_reason_code="36",  # URRBCH 36: WRONGLY_DELIVERED
        )

    if entry.status == "PENDING":
        log.info(
            "ifsc_validator.pending_entry",
            instrument_id=inp.instrument_id,
            ifsc=inp.ifsc_to_validate,
            bank_id=inp.bank_id,
        )
        return IFSCValidatorResult(
            outcome="HUMAN_REVIEW",
            reason="IFSC_NOT_YET_APPROVED",
        )

    if entry.status == "INACTIVE" or not entry.is_active:
        log.info(
            "ifsc_validator.inactive_branch",
            instrument_id=inp.instrument_id,
            ifsc=inp.ifsc_to_validate,
            bank_id=inp.bank_id,
        )
        return IFSCValidatorResult(
            outcome="HUMAN_REVIEW",
            reason="IFSC_BRANCH_INACTIVE",
        )

    log.info(
        "ifsc_validator.verified",
        instrument_id=inp.instrument_id,
        ifsc=inp.ifsc_to_validate,
        bank_id=inp.bank_id,
        bank_type=entry.bank_type,
    )
    return IFSCValidatorResult(outcome="PROCEED")
