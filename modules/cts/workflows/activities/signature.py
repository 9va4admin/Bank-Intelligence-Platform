"""
Signature verification activity — embedding-based comparison.

Flow:
  1. Crop the signature region from the cheque image (MinIO URL → PNG bytes)
  2. Embed the crop: SignatureEmbeddingModel → 512-dim vector (in-memory, not stored)
  3. Fetch stored embeddings from SignatureVault (Redis → YugabyteDB fallback)
  4. Cosine similarity: cheque vector vs each stored specimen vector → best score
  5. Score >= threshold → PROCEED; below → HUMAN_REVIEW

Vault miss (no specimens on file) triggers CBS fallback first:
  vault miss → CBS.get_signature_specimens() → embed → store in vault → compare
  CBS empty / error → HUMAN_REVIEW with NO_SIGNATURE_IN_VAULT

Multiple signatures detected on cheque (sig_count > 1) → HUMAN_REVIEW
with MULTI_SIGNATURE_DETECTED.

Vault error (Redis + DB down) → HUMAN_REVIEW.
Embedding model unavailable → HUMAN_REVIEW (degraded).

SMB proxy routing (Phase 4):
  When smb_id is set on the input AND smb_proxy is provided, specimens are
  fetched from the SMB's own CBS via smb-cbs-vault-proxy MCP tool instead of
  the sponsor bank's local SignatureVault. The vault-miss invariant (miss →
  HUMAN_REVIEW) applies equally to proxy responses.
"""
from __future__ import annotations

import asyncio
import io as _io
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.ai.signature_embedding import EmbeddingModelUnavailableError, cosine_similarity

log = structlog.get_logger()


class SignatureActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    account_number: str
    signature_image_url: str       # full cheque image URL (MinIO); cropped before embedding
    sig_count: int = 1             # number of ink signatures detected on cheque image
    sig_bboxes: list[list[float]] = []  # fractional [x1,y1,x2,y2] from detect_signatures
    smb_id: Optional[str] = None   # set when instrument drawn on an SMB customer


class SignatureActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                           # "PROCEED" | "HUMAN_REVIEW"
    match_score: Optional[float] = None
    miss_reason: Optional[str] = None
    degraded: bool = False
    cbs_fallback_used: bool = False        # True when CBS was queried to backfill vault miss


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
    """Async wrapper — download cheque from MinIO, crop to signature bbox, return PNG bytes."""
    try:
        return await asyncio.to_thread(_sync_crop_signature, image_url, bbox)
    except Exception as exc:
        log.warning("signature_activity.sig_crop_failed", image_url=image_url[:60], error=str(exc))
        return None


async def _embed_image(image_url_or_bytes, bbox: list[float], embedding_model, bank_id: str) -> Optional[list[float]]:
    """
    Crop the signature region then embed it.  Returns None if cropping or
    embedding fails — caller falls back to HUMAN_REVIEW on None.
    """
    if isinstance(image_url_or_bytes, bytes):
        crop_bytes = image_url_or_bytes
    else:
        if bbox:
            crop_bytes = await _crop_signature_region(image_url_or_bytes, bbox)
        else:
            # No bbox — try to download full image
            try:
                import urllib.request
                with urllib.request.urlopen(image_url_or_bytes, timeout=10) as resp:  # noqa: S310
                    crop_bytes = resp.read()
            except Exception as exc:
                log.warning("signature_activity.image_download_failed", error=str(exc))
                return None

    if crop_bytes is None:
        return None

    try:
        return await embedding_model.embed(crop_bytes, bank_id=bank_id)
    except EmbeddingModelUnavailableError as exc:
        log.warning("signature_activity.embed_failed", bank_id=bank_id, error=str(exc))
        return None


def _best_cosine_score(cheque_vector: list[float], vault_embeddings: list[list[float]]) -> float:
    """Highest cosine similarity between the cheque vector and any vault specimen."""
    if not vault_embeddings:
        return 0.0
    return max(cosine_similarity(cheque_vector, stored) for stored in vault_embeddings)


async def _fetch_via_proxy(smb_proxy, inp: "SignatureActivityInput"):
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
        return VaultResult(outcome="HUMAN_REVIEW", embeddings=[], miss_reason="SMB_PROXY_UNAVAILABLE")


async def _try_cbs_fallback(
    inp: "SignatureActivityInput",
    vault,
    cbs_connector,
    embedding_model,
    min_match_score: float,
) -> "SignatureActivityResult":
    """
    Called only on VAULT_MISS (not VAULT_ERROR). Queries CBS for raw specimen
    images, embeds them, stores in vault, then runs cosine comparison.
    """
    try:
        raw_specimens: list[bytes] = await cbs_connector.get_signature_specimens(
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

    if not raw_specimens:
        log.info(
            "signature_activity.no_specimen_in_vault_or_cbs",
            instrument_id=inp.instrument_id,
            account_last4=inp.account_number[-4:],
        )
        return SignatureActivityResult(outcome="HUMAN_REVIEW", miss_reason="NO_SIGNATURE_IN_VAULT")

    # Embed all CBS specimens
    specimen_embeddings: list[list[float]] = []
    for raw in raw_specimens:
        try:
            emb = await embedding_model.embed(raw, bank_id=inp.bank_id)
            specimen_embeddings.append(emb)
        except EmbeddingModelUnavailableError:
            log.warning("signature_activity.cbs_specimen_embed_failed", instrument_id=inp.instrument_id)

    if not specimen_embeddings:
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
            cbs_fallback_used=True,
        )

    # Store embeddings in vault (YugabyteDB + Redis)
    await vault.store_embeddings(inp.account_number, specimen_embeddings, source="CBS_FALLBACK")
    log.info(
        "signature_activity.cbs_specimens_embedded_and_stored",
        instrument_id=inp.instrument_id,
        account_last4=inp.account_number[-4:],
        specimen_count=len(specimen_embeddings),
    )

    # Embed cheque crop and compare
    cheque_vector = await _embed_image(
        inp.signature_image_url, inp.sig_bboxes[0] if inp.sig_bboxes else [],
        embedding_model, inp.bank_id,
    )
    if cheque_vector is None:
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
            cbs_fallback_used=True,
        )

    best_score = _best_cosine_score(cheque_vector, specimen_embeddings)
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
    embedding_model=None,
    smb_proxy=None,
    cbs_connector=None,
) -> SignatureActivityResult:
    """
    Verify the signature on a cheque against vault embeddings.

    Source priority:
      1. Multi-sig gate — if sig_count > 1, skip vault entirely → HUMAN_REVIEW
      2. smb_proxy (if provided AND inp.smb_id is set) — SMB CBS vault proxy MCP tool
      3. vault (local SignatureVault) — default for SB instruments
         └─ on VAULT_MISS + cbs_connector → CBS fallback → embed → store → compare

    Vault error (Redis + DB down) does NOT trigger CBS fallback.
    Embedding model unavailable → HUMAN_REVIEW (degraded).
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

    # Fetch stored embeddings — SMB proxy or local vault
    if smb_proxy is not None and inp.smb_id:
        vault_result = await _fetch_via_proxy(smb_proxy, inp)
    else:
        vault_result = await vault.get_signatures(inp.account_number, inp.bank_id)

    if vault_result.outcome != "FOUND":
        # CBS fallback only on a clean VAULT_MISS (not infrastructure error)
        if (
            cbs_connector is not None
            and embedding_model is not None
            and vault_result.miss_reason == "VAULT_MISS"
            and smb_proxy is None
        ):
            return await _try_cbs_fallback(inp, vault, cbs_connector, embedding_model, min_match_score)

        log.info(
            "signature_activity.vault_miss",
            instrument_id=inp.instrument_id,
            miss_reason=vault_result.miss_reason,
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason=vault_result.miss_reason,
            degraded=vault_result.miss_reason in {"SMB_PROXY_UNAVAILABLE", "VAULT_ERROR"},
        )

    # Embedding model unavailable — degrade gracefully
    if embedding_model is None:
        log.warning(
            "signature_activity.no_embedding_model",
            instrument_id=inp.instrument_id,
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
        )

    # Embed the cheque crop
    bbox = inp.sig_bboxes[0] if inp.sig_bboxes else []
    cheque_vector = await _embed_image(inp.signature_image_url, bbox, embedding_model, inp.bank_id)

    if cheque_vector is None:
        log.warning("signature_activity.embed_cheque_failed", instrument_id=inp.instrument_id)
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
        )

    # Cosine similarity: cheque vector vs each stored specimen
    best_score = _best_cosine_score(cheque_vector, vault_result.embeddings)

    if best_score < min_match_score:
        log.info(
            "signature_activity.low_match",
            instrument_id=inp.instrument_id,
            score=best_score,
            threshold=min_match_score,
        )
        return SignatureActivityResult(outcome="HUMAN_REVIEW", match_score=best_score)

    log.info(
        "signature_activity.match_accepted",
        instrument_id=inp.instrument_id,
        score=best_score,
        threshold=min_match_score,
    )
    return SignatureActivityResult(outcome="PROCEED", match_score=best_score)
