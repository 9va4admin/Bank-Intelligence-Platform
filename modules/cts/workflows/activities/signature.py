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
import asyncio
import io as _io
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
    signature_image_url: str          # full cheque image URL (MinIO); cropped before Siamese compare
    sig_count: int = 1               # number of ink signatures detected on cheque image
    sig_bboxes: list[list[float]] = []  # fractional [x1,y1,x2,y2] from detect_signatures
    smb_id: Optional[str] = None     # set when instrument drawn on an SMB customer


def _sync_crop_signature(image_url: str, bbox: list[float]) -> bytes:
    """Download full cheque image and crop to the signature bbox.

    Sync helper — called via asyncio.to_thread so the event loop stays free.
    Returns PNG bytes of the cropped signature region with a small padding border.
    """
    import urllib.request
    from PIL import Image as _PIL

    with urllib.request.urlopen(image_url, timeout=10) as resp:  # noqa: S310
        raw = resp.read()
    img = _PIL.open(_io.BytesIO(raw))
    img.load()
    img = img.convert("RGB")
    w, h = img.size
    x1_f, y1_f, x2_f, y2_f = bbox
    pad = max(6, int(min(w, h) * 0.02))
    crop = img.crop((
        max(0, int(x1_f * w) - pad),
        max(0, int(y1_f * h) - pad),
        min(w, int(x2_f * w) + pad),
        min(h, int(y2_f * h) + pad),
    ))
    buf = _io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


async def _crop_signature_region(image_url: str, bbox: list[float]) -> Optional[bytes]:
    """Async wrapper — download cheque from MinIO, crop to signature bbox, return PNG bytes.

    Returns None on any failure so callers fall back to the full-image URL.
    """
    try:
        return await asyncio.to_thread(_sync_crop_signature, image_url, bbox)
    except Exception as exc:
        log.warning("signature_activity.sig_crop_failed", image_url=image_url[:60], error=str(exc))
        return None


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

    # Crop before compare — same logic as the main verify_signature path
    sig_input = inp.signature_image_url
    if inp.sig_bboxes and model is not None:
        crop_bytes = await _crop_signature_region(inp.signature_image_url, inp.sig_bboxes[0])
        if crop_bytes is not None:
            sig_input = crop_bytes

    try:
        compare_result = await model.compare(sig_input, specimens)
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
    vault,
    config_service,
    model=None,
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
    """
    ai_config = await config_service.get_ai_config(inp.bank_id)
    min_match_score = ai_config["ai.signature.min_match_score"]

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

    # Crop signature region before Siamese comparison.
    # detect_signatures returns fractional bboxes; we download the full cheque
    # from MinIO and crop to the exact ink area so the Siamese model sees a
    # tight signature crop, not a 300dpi full-cheque image.
    sig_input = inp.signature_image_url  # default: full URL (falls back if crop fails)
    if inp.sig_bboxes and model is not None:
        crop_bytes = await _crop_signature_region(inp.signature_image_url, inp.sig_bboxes[0])
        if crop_bytes is not None:
            sig_input = crop_bytes   # bytes accepted alongside URL by Siamese model
            log.info(
                "signature_activity.using_cropped_region",
                instrument_id=inp.instrument_id,
                bbox=inp.sig_bboxes[0],
            )

    try:
        compare_result = await model.compare(sig_input, vault_result.specimens)
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
