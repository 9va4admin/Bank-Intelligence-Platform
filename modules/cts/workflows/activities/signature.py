"""
Signature verification activity — Siamese network compares presented signature
against specimens stored in SignatureVault.

Vault miss (no specimens on file) → HUMAN_REVIEW (never auto-return).
Low match score → HUMAN_REVIEW.
Model unavailable → HUMAN_REVIEW (degraded).
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class SignatureActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    account_number: str
    signature_image_url: str


class SignatureActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                         # "PROCEED" | "HUMAN_REVIEW"
    match_score: Optional[float] = None
    miss_reason: Optional[str] = None
    degraded: bool = False


async def verify_signature(
    inp: SignatureActivityInput,
    vault=None,
    model=None,
    min_match_score: float = 0.80,
) -> SignatureActivityResult:
    """
    Fetch specimens from vault, compare against presented signature.
    Vault miss and model failure both degrade to HUMAN_REVIEW.
    """
    vault_result = await vault.get_signatures(inp.account_number, inp.bank_id)

    if vault_result.outcome != "FOUND":
        log.info(
            "signature_activity.vault_miss",
            instrument_id=inp.instrument_id,
            miss_reason=vault_result.miss_reason,
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason=vault_result.miss_reason,
        )

    try:
        compare_result = await model.compare(inp.signature_image_url, vault_result.specimens)
    except Exception as exc:
        log.warning(
            "signature_activity.model_unavailable",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
        )

    best_score = compare_result.get("best_match_score", 0.0)

    if best_score < min_match_score:
        log.info(
            "signature_activity.low_match",
            instrument_id=inp.instrument_id,
            score=best_score,
            threshold=min_match_score,
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            match_score=best_score,
        )

    return SignatureActivityResult(
        outcome="PROCEED",
        match_score=best_score,
    )
