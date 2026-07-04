"""
Signature verification activity — Siamese network compares presented signature
against specimens stored in SignatureVault.

Vault miss (no specimens on file) → HUMAN_REVIEW (never auto-return).
Low match score → HUMAN_REVIEW.
Model unavailable → HUMAN_REVIEW (degraded).

SMB proxy routing (Phase 4):
  When smb_id is set on the input AND smb_proxy is provided, specimens are
  fetched from the SMB's own CBS via smb-cbs-vault-proxy MCP tool instead of
  the sponsor bank's local SignatureVault. The vault-miss invariant (miss →
  HUMAN_REVIEW) applies equally to proxy responses.
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
    smb_id: Optional[str] = None   # set when instrument drawn on an SMB customer


class SignatureActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                         # "PROCEED" | "HUMAN_REVIEW"
    match_score: Optional[float] = None
    miss_reason: Optional[str] = None
    degraded: bool = False


async def _fetch_via_proxy(smb_proxy, inp: SignatureActivityInput):
    """Fetch specimens from SMB CBS vault proxy. Proxy errors degrade to HUMAN_REVIEW."""
    from modules.cts.vaults.signature_vault import VaultResult
    try:
        return await smb_proxy.get_signature(inp.account_number, inp.bank_id, inp.smb_id)
    except Exception as exc:
        log.warning(
            "signature_activity.smb_proxy_unavailable",
            instrument_id=inp.instrument_id,
            smb_id=inp.smb_id,
            error=str(exc),
        )
        return VaultResult(
            outcome="HUMAN_REVIEW",
            specimens=[],
            miss_reason="SMB_PROXY_UNAVAILABLE",
        )


async def verify_signature(
    inp: SignatureActivityInput,
    vault=None,
    model=None,
    min_match_score: float = 0.80,
    smb_proxy=None,
) -> SignatureActivityResult:
    """
    Fetch specimens then compare against presented signature.

    Source priority:
      1. smb_proxy (if provided AND inp.smb_id is set) — SMB CBS vault proxy MCP tool
      2. vault (local SignatureVault) — default for SB instruments

    Vault miss and model failure both degrade to HUMAN_REVIEW.
    """
    if smb_proxy is not None and inp.smb_id:
        vault_result = await _fetch_via_proxy(smb_proxy, inp)
    else:
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
            # Proxy/infrastructure errors are degraded; normal vault misses are not
            degraded=vault_result.miss_reason == "SMB_PROXY_UNAVAILABLE",
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
