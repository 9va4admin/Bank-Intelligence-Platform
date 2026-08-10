"""
Signature verification activity — per-signatory embedding comparison.

Handles 1 or N detected ink signatures on a cheque uniformly:

  1. Embed every detected signature bbox from the cheque image.
  2. Load all authorised signatories and their specimens from SignatureVault.
  3. For each signatory: best cosine score across ALL their specimens vs
     ALL detected ink signatures on the cheque. Multiple specimens per
     signatory give the signatory the best chance to match.
  4. Apply mandate BRE:
       ANY_ONE       — PROCEED if at least 1 signatory matched (retail default)
       ALL_REQUIRED  — PROCEED only if every registered signatory matched
       QUORUM_N      — PROCEED if N signatories matched
  5. Return enriched SignatureActivityResult with per-signatory breakdown.

Vault miss (no specimens for any signatory) → CBS fallback:
  get_signatory_data() → per-signatory embed → store in vault → compare.
  Falls back to flat get_signature_specimens() when get_signatory_data() raises
  NotImplementedError (older CBS adapters).

SMB proxy path: flat list from proxy treated as single PRIMARY signatory.

Vault error or model unavailable → HUMAN_REVIEW (degraded). Never raises.
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


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class SignatureActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    account_number: str
    signature_image_url: str        # full cheque image URL (MinIO); cropped per bbox
    sig_count: int = 1              # total ink signatures detected on cheque image
    sig_bboxes: list[list[float]] = []  # fractional [x1,y1,x2,y2] per detected sig
    smb_id: Optional[str] = None   # set when instrument drawn on an SMB customer


class SignatoryVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)
    signatory_id: str
    best_score: float               # highest cosine across all specimens × all detected sigs
    specimen_index: Optional[int] = None    # vault specimen index that gave best_score
    verdict: str                    # "MATCHED" | "NO_MATCH" | "NO_SPECIMENS"


class SignatureActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                                    # "PROCEED" | "HUMAN_REVIEW"
    match_score: Optional[float] = None             # highest score across all signatories
    miss_reason: Optional[str] = None
    degraded: bool = False
    cbs_fallback_used: bool = False
    per_signatory: list[SignatoryVerdict] = []       # one entry per account signatory
    mandate_rule: Optional[str] = None               # rule that was applied
    signatories_matched: int = 0                     # count that cleared threshold
    signatories_required: int = 1                    # per mandate BRE


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _apply_morphological_normalisation(crop: "any") -> "any":
    """
    Otsu binarisation + morphological thinning on a PIL signature crop.

    Improves cosine similarity accuracy by removing scanner background noise
    and reducing ink strokes to single-pixel width. Falls back to the original
    crop if opencv or numpy is unavailable.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image as _PIL
    except ImportError:
        return crop

    try:
        gray = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        try:
            thinned = cv2.ximgproc.thinning(binary, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN)
        except AttributeError:
            thinned = binary
        rgb_arr = cv2.cvtColor(cv2.bitwise_not(thinned), cv2.COLOR_GRAY2RGB)
        return _PIL.fromarray(rgb_arr)
    except Exception:
        return crop


def _sync_crop_signature(image_url: str, bbox: list[float]) -> bytes:
    """Download full cheque image and crop to the signature bbox, with padding."""
    import urllib.request
    from PIL import Image as _PIL

    with urllib.request.urlopen(image_url, timeout=10) as resp:  # noqa: S310
        raw = resp.read()
    img = _PIL.open(_io.BytesIO(raw))
    img.load()
    img = img.convert("RGB")
    w, h = img.size

    if bbox:
        x1_f, y1_f, x2_f, y2_f = bbox
        pad = max(6, int(min(w, h) * 0.02))
        crop = img.crop((
            max(0, int(x1_f * w) - pad),
            max(0, int(y1_f * h) - pad),
            min(w, int(x2_f * w) + pad),
            min(h, int(y2_f * h) + pad),
        ))
    else:
        crop = img  # no bbox → full image

    crop = _apply_morphological_normalisation(crop)
    buf = _io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


async def _crop_signature_region(image_url: str, bbox: list[float]) -> Optional[bytes]:
    """Async wrapper — download + crop, return PNG bytes. Returns None on failure."""
    try:
        return await asyncio.to_thread(_sync_crop_signature, image_url, bbox)
    except Exception as exc:
        log.warning("signature_activity.crop_failed", image_url=image_url[:60], error=str(exc))
        return None


async def _embed_image(
    image_url_or_bytes, bbox: list[float], embedding_model, bank_id: str
) -> Optional[list[float]]:
    """Crop the signature region then embed it. Returns None on any failure."""
    if isinstance(image_url_or_bytes, bytes):
        crop_bytes = image_url_or_bytes
    else:
        crop_bytes = await _crop_signature_region(image_url_or_bytes, bbox)

    if crop_bytes is None:
        return None

    try:
        return await embedding_model.embed(crop_bytes, bank_id=bank_id)
    except EmbeddingModelUnavailableError as exc:
        log.warning("signature_activity.embed_failed", bank_id=bank_id, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Mandate BRE helper
# ---------------------------------------------------------------------------

def _mandate_required_count(mandate_rule: str, total_signatories: int) -> int:
    """Resolve mandate rule to a required-count integer."""
    if mandate_rule == "ALL_REQUIRED":
        return total_signatories
    if mandate_rule.startswith("QUORUM_"):
        try:
            return int(mandate_rule.split("_")[1])
        except (IndexError, ValueError):
            return 1
    return 1  # ANY_ONE or unknown → default 1


# ---------------------------------------------------------------------------
# SMB proxy helper
# ---------------------------------------------------------------------------

async def _fetch_via_proxy(smb_proxy, inp: SignatureActivityInput):
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


# ---------------------------------------------------------------------------
# CBS fallback helper
# ---------------------------------------------------------------------------

async def _cbs_signatory_fallback(
    inp: SignatureActivityInput,
    vault,
    cbs_connector,
    embedding_model,
) -> tuple[dict[str, list[list[float]]], bool]:
    """
    Fetch specimens from CBS on vault miss.

    Priority:
      1. get_signatory_data() → per-signatory specimens + store per-signatory
      2. get_signature_specimens() flat fallback → stored as PRIMARY

    Returns (specimens_by_signatory, cbs_fallback_used).
    On CBS error returns ({}, True) — caller treats empty dict as HUMAN_REVIEW.
    """
    # Try structured per-signatory CBS method first
    try:
        signatory_list = await cbs_connector.get_signatory_data(
            inp.account_number, inp.bank_id
        )
    except NotImplementedError:
        signatory_list = None  # older CBS adapter — fall through to flat method
    except Exception as exc:
        log.warning(
            "signature_activity.cbs_signatory_data_error",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return {}, True

    if signatory_list is not None:
        if not signatory_list:
            return {}, True

        specimens_by_sig: dict[str, list[list[float]]] = {}
        for sig_data in signatory_list:
            sig_embeddings: list[list[float]] = []
            for raw_img in sig_data.specimen_images:
                try:
                    emb = await embedding_model.embed(raw_img, bank_id=inp.bank_id)
                    sig_embeddings.append(emb)
                except EmbeddingModelUnavailableError:
                    log.warning(
                        "signature_activity.cbs_specimen_embed_failed",
                        instrument_id=inp.instrument_id,
                        signatory_id=sig_data.signatory_id,
                    )

            if sig_embeddings:
                await vault.store_embeddings(
                    inp.account_number,
                    sig_embeddings,
                    signatory_id=sig_data.signatory_id,
                    source="CBS_FALLBACK",
                )
                specimens_by_sig[sig_data.signatory_id] = sig_embeddings

        if specimens_by_sig:
            log.info(
                "signature_activity.cbs_signatory_fallback_complete",
                instrument_id=inp.instrument_id,
                account_last4=inp.account_number[-4:],
                signatories_loaded=len(specimens_by_sig),
            )
        return specimens_by_sig, True

    # Flat fallback for CBS adapters that don't implement get_signatory_data()
    try:
        raw_specimens = await cbs_connector.get_signature_specimens(
            inp.account_number, inp.bank_id
        )
    except Exception as exc:
        log.warning(
            "signature_activity.cbs_flat_fallback_error",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return {}, True

    if not raw_specimens:
        return {}, True

    embeddings: list[list[float]] = []
    for raw in raw_specimens:
        try:
            emb = await embedding_model.embed(raw, bank_id=inp.bank_id)
            embeddings.append(emb)
        except EmbeddingModelUnavailableError:
            log.warning(
                "signature_activity.cbs_flat_specimen_embed_failed",
                instrument_id=inp.instrument_id,
            )

    if embeddings:
        await vault.store_embeddings(
            inp.account_number, embeddings, signatory_id="PRIMARY", source="CBS_FALLBACK"
        )
        log.info(
            "signature_activity.cbs_flat_fallback_complete",
            instrument_id=inp.instrument_id,
            account_last4=inp.account_number[-4:],
            specimen_count=len(embeddings),
        )
        return {"PRIMARY": embeddings}, True

    return {}, True


# ---------------------------------------------------------------------------
# Main activity
# ---------------------------------------------------------------------------

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
    Verify ink signature(s) on a cheque against all registered account signatories.

    Works uniformly for cheques with 1 detected sig and cheques with N detected sigs.
    The mandate rule (ANY_ONE / ALL_REQUIRED / QUORUM_N) determines the overall outcome.

    Source priority:
      SMB proxy (if smb_id set)  → flat list treated as PRIMARY signatory, ANY_ONE mandate
      SignatureVault              → per-signatory specimens, mandate from account_signatories
        └─ vault miss + CBS      → embed per signatory from CBS, store, compare

    Vault error or model unavailable → HUMAN_REVIEW (degraded=True). Never raises.
    """
    ai_config = await config_service.get_ai_config(inp.bank_id)
    min_match_score: float = ai_config["ai.signature.min_match_score"]

    # Step 1 — need embedding model first; fail fast if absent
    if embedding_model is None:
        log.warning(
            "verify_signature.no_embedding_model",
            instrument_id=inp.instrument_id,
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
        )

    # Step 2 — embed all detected ink signatures on the cheque
    bboxes = inp.sig_bboxes if inp.sig_bboxes else [[]]  # empty → full image
    cheque_vectors: list[list[float]] = []
    for bbox in bboxes:
        vec = await _embed_image(inp.signature_image_url, bbox, embedding_model, inp.bank_id)
        if vec is not None:
            cheque_vectors.append(vec)

    if not cheque_vectors:
        log.warning(
            "verify_signature.all_crops_failed",
            instrument_id=inp.instrument_id,
            bbox_count=len(bboxes),
        )
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            miss_reason="MODEL_UNAVAILABLE",
            degraded=True,
        )

    # Step 3 — load signatory specimens
    cbs_fallback_used = False
    mandate_rule = "ANY_ONE"

    if smb_proxy is not None and inp.smb_id:
        # SMB proxy path: flat result wrapped as PRIMARY
        vault_result = await _fetch_via_proxy(smb_proxy, inp)
        if vault_result.outcome != "FOUND":
            return SignatureActivityResult(
                outcome="HUMAN_REVIEW",
                miss_reason=vault_result.miss_reason,
                degraded=vault_result.miss_reason == "SMB_PROXY_UNAVAILABLE",
            )
        specimens_by_sig = {"PRIMARY": vault_result.embeddings}
        # ANY_ONE is the only sensible mandate for an SMB proxy result
    else:
        specimens_by_sig = await vault.get_specimens_by_signatory(
            inp.account_number, inp.bank_id
        )
        mandate_rule = await vault.get_mandate_rule(inp.account_number, inp.bank_id)

        if not specimens_by_sig:
            if cbs_connector is not None:
                specimens_by_sig, cbs_fallback_used = await _cbs_signatory_fallback(
                    inp, vault, cbs_connector, embedding_model
                )

        if not specimens_by_sig:
            log.info(
                "verify_signature.no_specimens",
                instrument_id=inp.instrument_id,
                account_last4=inp.account_number[-4:],
                cbs_fallback_used=cbs_fallback_used,
            )
            return SignatureActivityResult(
                outcome="HUMAN_REVIEW",
                miss_reason="NO_SIGNATURE_IN_VAULT",
                cbs_fallback_used=cbs_fallback_used,
                degraded=cbs_fallback_used,  # CBS was tried but empty/errored
            )

    # Step 4 — per-signatory match
    # For each signatory: find the highest cosine score across
    #   ALL their vault specimens × ALL detected ink sigs on the cheque.
    per_signatory: list[SignatoryVerdict] = []

    for sig_id, specimens in specimens_by_sig.items():
        if not specimens:
            per_signatory.append(SignatoryVerdict(
                signatory_id=sig_id,
                best_score=0.0,
                specimen_index=None,
                verdict="NO_SPECIMENS",
            ))
            continue

        best_score = 0.0
        best_spec_idx: Optional[int] = None

        for spec_idx, spec_vec in enumerate(specimens):
            for chq_vec in cheque_vectors:
                score = cosine_similarity(chq_vec, spec_vec)
                if score > best_score:
                    best_score = score
                    best_spec_idx = spec_idx

        verdict = "MATCHED" if best_score >= min_match_score else "NO_MATCH"
        per_signatory.append(SignatoryVerdict(
            signatory_id=sig_id,
            best_score=round(best_score, 6),
            specimen_index=best_spec_idx if verdict == "MATCHED" else None,
            verdict=verdict,
        ))

    # Step 5 — mandate BRE
    matched_count = sum(1 for r in per_signatory if r.verdict == "MATCHED")
    total_count = len(per_signatory)
    required = _mandate_required_count(mandate_rule, total_count)
    overall_score = max((r.best_score for r in per_signatory), default=0.0)

    log.info(
        "verify_signature.result",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        mandate_rule=mandate_rule,
        signatories_total=total_count,
        signatories_matched=matched_count,
        signatories_required=required,
        overall_score=overall_score,
        detected_sigs=len(cheque_vectors),
    )

    if matched_count < required:
        return SignatureActivityResult(
            outcome="HUMAN_REVIEW",
            match_score=overall_score,
            per_signatory=per_signatory,
            mandate_rule=mandate_rule,
            signatories_matched=matched_count,
            signatories_required=required,
            cbs_fallback_used=cbs_fallback_used,
        )

    return SignatureActivityResult(
        outcome="PROCEED",
        match_score=overall_score,
        per_signatory=per_signatory,
        mandate_rule=mandate_rule,
        signatories_matched=matched_count,
        signatories_required=required,
        cbs_fallback_used=cbs_fallback_used,
    )
