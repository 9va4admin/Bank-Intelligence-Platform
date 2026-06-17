"""
EJ dispute matching activity: BGE-M3 embeddings for semantic claim-to-EJ matching.
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_DEFAULT_MIN_MATCH_SCORE = 0.80


class EJDisputeMatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    atm_id: str
    npci_claim_id: str
    claim_amount: float
    claim_timestamp: str
    claim_type: str


class EJDisputeMatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                            # "MATCHED" | "NO_MATCH" | "MATCH_FAILED"
    matched_canonical_hash: Optional[str] = None
    match_score: Optional[float] = None


async def match_dispute_to_ej(
    inp: EJDisputeMatchInput,
    *,
    embedder,
    vector_search,
    min_match_score: float = _DEFAULT_MIN_MATCH_SCORE,
) -> EJDisputeMatchResult:
    query = (
        f"ATM {inp.atm_id} {inp.claim_type} amount={inp.claim_amount} at {inp.claim_timestamp}"
    )

    try:
        embedding = await embedder.embed(query)
    except Exception as exc:
        log.warning("ej_dispute_match.embed_failed", claim_id=inp.npci_claim_id, error=str(exc))
        return EJDisputeMatchResult(outcome="MATCH_FAILED")

    try:
        results = await vector_search.search(
            embedding=embedding,
            bank_id=inp.bank_id,
            atm_id=inp.atm_id,
            limit=5,
        )
    except Exception as exc:
        log.warning("ej_dispute_match.search_failed", claim_id=inp.npci_claim_id, error=str(exc))
        return EJDisputeMatchResult(outcome="MATCH_FAILED")

    if not results:
        return EJDisputeMatchResult(outcome="NO_MATCH")

    best = results[0]
    score = best.get("score", 0.0)

    if score < min_match_score:
        return EJDisputeMatchResult(outcome="NO_MATCH", match_score=score)

    return EJDisputeMatchResult(
        outcome="MATCHED",
        matched_canonical_hash=best.get("canonical_hash"),
        match_score=score,
    )
