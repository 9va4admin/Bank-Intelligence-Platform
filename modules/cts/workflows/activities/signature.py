"""
Signature verification activity — Siamese network compares presented signature
against specimens stored in SignatureVault.

Vault miss (no specimens on file) triggers CBS fallback first:
  vault miss → CBS.get_signature_specimens() → store in vault → compare
  CBS empty / error → HUMAN_REVIEW with NO_SIGNATURE_IN_VAULT

Multiple signatures detected on cheque (sig_count > 1) → HUMAN_REVIEW
with MULTI_SIGNATURE_DETECTED (skip vault entirely in v1).

Vault error (Redis down) → HUMAN_REVIEW (no CBS attempt — Redis error ≠ specimen absent).
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
from temporalio import activity

log = structlog.get_logger()


class SignatureActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    account_number: str
    signature_image_url: str
    sig_count: int = 1               # number of ink signatures detected on cheque image
    smb_id: Optional[str] = None     # set when instrument drawn on an SMB customer


class SignatureActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                           # "PROCEED" | "HUMAN_REVIEW"
    match_score: Optional[float] = None
    miss_reason: Optional[str] = None
    degraded: bool = False
    cbs_fallback_used: bool = False        # True when CBS was queried to backfill vault miss


async def _fetch_via_proxy(smb_proxy, inp: "SignatureActivityInput"):
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


async def _try_cbs_fallback(
    inp: "SignatureActivityInput",
    vault,
    cbs_connector,
    model,
    min_match_score: float,
) -> "SignatureActivityResult":
    """
    Called only on VAULT_MISS (not VAULT_ERROR). Queries CBS for specimens,
    stores them in the vault, then runs comparison.
    Returns a SignatureActivityResult in all cases.
    """
    try:
        specimens = await cbs_connector.get_signature_specimens(
            inp.account_number, inp.bank_id
        )
    except Exception as exc:
        log.warning(
            "signature_activity.cbs_fallback_error",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="CBS_FALLBACK_ERROR",
            degraded=True,
        )

    if not specimens:
        log.info(
            "signature_activity.no_specimen_in_vault_or_cbs",
            instrument_id=inp.instrument_id,
            account_last4=inp.account_number[-4:],
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="NO_SIGNATURE_IN_VAULT",
        )

    # Store CBS-fetched specimens so subsequent cheques hit the vault instead
    await vault.store_signatures(inp.account_number, specimens)
    log.info(
        "signature_activity.cbs_specimens_stored",
        instrument_id=inp.instrument_id,
        account_last4=inp.account_number[-4:],
        specimen_count=len(specimens),
    )

    try:
        compare_result = await model.compare(inp.signature_image_url, specimens)
    except Exception as exc:
        log.warning(
            "signature_activity.model_unavailable_after_cbs",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
            cbs_fallback_used=True,
        )

    best_score = compare_result.get("best_match_score", 0.0)
    if best_score < min_match_score:
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            match_score=best_score,
            cbs_fallback_used=True,
        )

    return SignatureActivityResult(
        outcome="PROCEED",
        match_score=best_score,
        cbs_fallback_used=True,
    )


@activity.defn
async def verify_signature(
    inp: SignatureActivityInput,
    vault=None,
    model=None,
    min_match_score: Optional[float] = None,
    config_service=None,
    smb_proxy=None,
    cbs_connector=None,
) -> SignatureActivityResult:
    """
    Verify the signature on a cheque against vault specimens.

    Source priority:
      1. Multi-sig gate — if sig_count > 1, skip vault entirely → HUMAN_REVIEW
      2. smb_proxy (if provided AND inp.smb_id is set) — SMB CBS vault proxy MCP tool
      3. vault (local SignatureVault) — default for SB instruments
         └─ on VAULT_MISS + cbs_connector → CBS fallback

    Vault error (Redis down) does NOT trigger CBS fallback.
    min_match_score must come from config_service in production — never hardcoded.
    """
    if min_match_score is None:
        if config_service is not None:
            ai_config = await config_service.get_ai_config(inp.bank_id)
            min_match_score = ai_config["signature.min_match_score"]
        else:
            min_match_score = 0.80  # test-only fallback; production must inject config_service

    # Gate 1 — multiple ink signatures detected on the cheque image
    if inp.sig_count > 1:
        log.info(
            "signature_activity.multi_sig_detected",
            instrument_id=inp.instrument_id,
            sig_count=inp.sig_count,
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MULTI_SIGNATURE_DETECTED",
        )

    # Fetch specimens — SMB proxy or local vault
    if smb_proxy is not None and inp.smb_id:
        vault_result = await _fetch_via_proxy(smb_proxy, inp)
    else:
        vault_result = await vault.get_signatures(inp.account_number, inp.bank_id)

    if vault_result.outcome != "FOUND":
        # CBS fallback only on a clean VAULT_MISS (not infrastructure error)
        if (
            cbs_connector is not None
            and vault_result.miss_reason == "VAULT_MISS"
            and smb_proxy is None   # CBS fallback applies to SB instruments only
        ):
            return await _try_cbs_fallback(inp, vault, cbs_connector, model, min_match_score)

        log.info(
            "signature_activity.vault_miss",
            instrument_id=inp.instrument_id,
            miss_reason=vault_result.miss_reason,
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason=vault_result.miss_reason,
            # Proxy/infrastructure errors are degraded; normal vault misses are not
            degraded=vault_result.miss_reason in {"SMB_PROXY_UNAVAILABLE", "VAULT_ERROR"},
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
