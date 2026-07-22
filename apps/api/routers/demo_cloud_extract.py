"""
Cloud AI cheque extraction — Miscellaneous / demo only.

DELIBERATE, TEMPORARY, EXPLICITLY-AUTHORIZED exception to
.claude/rules/ai-inference.md's "no cloud LLM APIs" rule and this
platform's Security Principle #7 ("Data Never Leaves Bank"). Added at the
user's direction to give live demos real (not simulated) AI extraction
ahead of an on-prem vLLM GPU deployment being available; the plan is to
swap the Hugging Face call below for a real CascadeOrchestrator/vLLM call
once GPU infra exists (see shared/ai/model_cascade.py for that pattern).

Never called by any production CTS clearing workflow — this router is
reachable only from the "Miscellaneous" nav section's Cloud AI Demo page,
clearly labelled in the UI as a temporary cloud-based demo. Still requires
the same authenticated session as every other route in this app; the
exception is scoped to "which model answers the extraction call", not to
"who can call this endpoint".

HF token is Vault-backed via config_service.get_secret() like every other
credential in this codebase — never hardcoded, never read from a .env or
Streamlit-secrets file (that's how ImageScanUtility/, the standalone
reference this prompt was adapted from, handles it, which is fine for a
throwaway local script but not for anything reachable from the real app).
"""
import base64
import io
import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from PIL import Image, ImageStat, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts/demo/cloud-extract", tags=["Demo — Cloud AI (temporary)"])

_HF_BASE_URL_FALLBACK = "https://router.huggingface.co/v1"

_MODEL_MAPPING = {
    "qwen-32b": "Qwen/Qwen3-VL-32B-Instruct:featherless-ai",
    # ovhcloud's hosting of this model is in HF's own inferenceProviderMapping
    # "error" state (confirmed via https://huggingface.co/api/models/Qwen/Qwen2.5-VL-72B-Instruct
    # ?expand[]=inferenceProviderMapping) -- featherless-ai is the only "live"
    # provider for it, not an account-authorization gap.
    "qwen-72b": "Qwen/Qwen2.5-VL-72B-Instruct:featherless-ai",
    "gemma-27b": "google/gemma-3-27b-it:featherless-ai",
}

# Adapted from ImageScanUtility/prompt.py (already validated against real
# cheque images in that standalone tool) — kept here as ASTRA's own prompt
# constant rather than importing across the reference-folder boundary,
# matching .claude/rules/ai-inference.md's "Prompt Engineering Standards".
CLOUD_EXTRACT_PROMPT = """You are an expert Indian Bank Cheque OCR and Validation Engine.

Your task is to extract cheque information with maximum accuracy and perform consistency checks between fields.

IMPORTANT INSTRUCTIONS:

1. Read the ENTIRE cheque carefully.
2. Extract all visible information exactly as written.
3. Preserve leading zeros in cheque numbers, account numbers, MICR codes, and other numeric identifiers.
4. If a field is not visible or cannot be determined confidently, return null.
5. Return ONLY valid JSON.
6. Do not return markdown, comments, explanations, confidence scores, or extra text.

FIELD EXTRACTION RULES

* bank_name: Full bank name printed on the cheque.
* ifsc_code: Extract IFSC code exactly (format XXXX0XXXXXX, e.g. SBIN0001234).
* date: Convert to DD/MM/YYYY format.
* payee_name: Full name written after "Pay".
* amount_words: Complete handwritten amount in words.
* amount_numeric: Numeric amount from the amount box. Preserve commas and decimals exactly as written.
* is_amount_matching: Compare amount_words and amount_numeric using semantic understanding — allow minor
  OCR mistakes and spelling variations (e.g. "One Thousnd Rupees Only" vs 1000 -> true). Only return false
  when the actual monetary values differ.
* account_number: Customer account number printed on the cheque. Preserve leading zeros.
* signature_present: true if a handwritten signature exists, false if the signature area is blank.
* signature_name: Printed account holder name near the signature area, if visible; else null.
* cheque_number: The 6-digit cheque number printed at the LEFT side of the MICR band. Preserve leading zeros.
* micr_code: The 9-digit MICR code printed in the MICR band. Preserve leading zeros.

SIGNATURE DETECTION RULES
* signature_bboxes: Locate every distinct HANDWRITTEN INK SIGNATURE on the cheque. For each, return its
  bounding box as [x1, y1, x2, y2] where each value is a decimal fraction of the image dimensions
  (0.0 = left/top edge, 1.0 = right/bottom edge). If no signatures found, return [].
  CRITICAL — the bbox must enclose ONLY the actual cursive ink strokes:
    - DO NOT include the printed account holder name below the signature (e.g. "ANKIT KUMAR")
    - DO NOT include "Please sign above" or any other printed instruction text
    - DO NOT include the horizontal signature line/rule
    - The box must end where the last ink stroke ends — stop BEFORE any printed text below
  Include ONLY the actual handwriting — not printed text, stamps, or blank areas.
* signature_count: Total number of distinct signatures detected (integer).
* signature_fraud_flags: Examine each signature area for tampering indicators. Include any of the
  following strings that apply:
    "OVERWRITTEN"   — ink written on top of existing ink or whiteout detected
    "SMUDGED"       — ink spread or blur suggesting wet-ink tampering
    "MULTIPLE_INKS" — visibly different ink colours across signature zones
    "FAINT_INK"     — unusually light stroke suggesting photocopied or printed signature
    "MISALIGNED"    — signature placed outside the designated signature box
  Return [] if none detected.

VALIDATION RULES
1. Never truncate cheque_number or micr_code.
2. Never remove leading zeros.
3. Never infer missing digits.
4. If unreadable, return null.

Return ONLY valid JSON:
{
"bank_name": "",
"date": "",
"payee_name": "",
"amount_words": "",
"amount_numeric": "",
"is_amount_matching": true,
"account_number": "",
"ifsc_code": "",
"cheque_number": "",
"micr_code": "",
"signature_present": true,
"signature_name": null,
"signature_count": 1,
"signature_bboxes": [[0.65, 0.70, 0.95, 0.95]],
"signature_fraud_flags": []
}
"""


class CloudExtractResponse(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())
    model_used: str
    bank_name: Optional[str] = None
    date: Optional[str] = None
    payee_name: Optional[str] = None
    amount_words: Optional[str] = None
    amount_numeric: Optional[str] = None
    is_amount_matching: Optional[bool] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    cheque_number: Optional[str] = None
    micr_code: Optional[str] = None
    signature_present: Optional[bool] = None
    signature_name: Optional[str] = None
    signature_count: Optional[int] = None
    signature_bboxes: Optional[list[list[float]]] = None
    signature_crops: Optional[list[str]] = None            # base64 PNG per detected signature, server-cropped
    signature_crops_estimated: Optional[bool] = None       # True when PIL ink-detect fallback was used
    signature_fraud_flags: Optional[list[str]] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None


async def _resolve_hf_base_url(bank_id: str) -> str:
    """Resolve Hugging Face Inference Router base URL.

    config_service first, ASTRA_DEMO_HF_BASE_URL env var second,
    hardcoded fallback last — matching _resolve_hf_token()'s pattern.
    """
    from shared.config.config_service import config_service
    try:
        return await config_service.get_secret("demo.hf_base_url")
    except Exception:
        pass
    import os
    return os.environ.get("ASTRA_DEMO_HF_BASE_URL", _HF_BASE_URL_FALLBACK)


async def _resolve_hf_token(bank_id: str) -> Optional[str]:
    """
    Vault first (the correct, real path — matches every other secret in
    this codebase). Falls back to the ASTRA_DEMO_HF_TOKEN environment
    variable only when Vault genuinely isn't reachable — this repo has no
    Vault running in bare local dev (see dev_auth_server.py's own
    no-Vault/DB/Redis design for the same constraint applied to auth).
    This is the one deliberate os.environ read in this already-exceptional
    file; every other secret access in the codebase goes through
    config_service exclusively, and this fallback never fires once a real
    Vault + demo.hf_token secret exists.
    """
    from shared.config.config_service import config_service

    try:
        return await config_service.get_secret("demo.hf_token")
    except Exception as exc:
        log.warning("demo.cloud_extract.vault_hf_token_unavailable", bank_id=bank_id, error=str(exc))

    import os
    env_token = os.environ.get("ASTRA_DEMO_HF_TOKEN")
    if env_token:
        log.info("demo.cloud_extract.using_env_hf_token_fallback", bank_id=bank_id)
        return env_token
    return None


def _clean_json_response(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _trim_crop_bottom(crop_img: Image.Image) -> Image.Image:
    """
    Remove printed text bands (account holder name, instruction lines) below
    the actual handwritten signature.

    Splits the crop into ink bands — runs of ink rows separated by a clear
    gap of empty rows. The FIRST (topmost) band is the signature; all bands
    below are printed text and are discarded.

    Gap size is fixed at 2 rows (works reliably at 96–300 DPI). Band minimum
    is 5 ink rows to skip tiny blips.

    Always returns a valid Image — wraps all logic in try/except so a bug
    here never prevents the crop from appearing in the UI.
    """
    try:
        cw, ch = crop_img.size
        if cw == 0 or ch == 0:
            return crop_img

        gray = crop_img.convert("L")
        stat = ImageStat.Stat(gray)
        bg_mean = stat.mean[0]
        threshold = max(40, min(220, bg_mean * 0.78))
        ink_mask = gray.point(lambda p: 255 if p < threshold else 0, "L")
        bbox = ink_mask.getbbox()
        if not bbox:
            return crop_img

        _, by1, _, by2 = bbox
        ink_data = list(ink_mask.getdata())

        gap_thresh = max(2, int(cw * 0.03))    # < 3% of width = near-empty row
        MIN_GAP = 2                              # 2 empty rows = band boundary
        MIN_BAND = 5                             # a real band has >= 5 ink rows

        bands = []          # list of (start_y, end_y)
        band_start = None
        band_ink_rows = 0
        gap_run = 0

        for y in range(by1, min(by2 + 1, ch)):
            row_count = sum(
                1 for x in range(cw) if ink_data[y * cw + x] > 128
            )
            if row_count > gap_thresh:
                if band_start is None:
                    band_start = y
                band_ink_rows += 1
                gap_run = 0
            else:
                gap_run += 1
                if band_start is not None and gap_run >= MIN_GAP:
                    if band_ink_rows >= MIN_BAND:
                        bands.append((band_start, y - gap_run))
                    band_start = None
                    band_ink_rows = 0

        if band_start is not None and band_ink_rows >= MIN_BAND:
            bands.append((band_start, by2))

        if len(bands) <= 1:
            return crop_img  # single band — can't trim safely

        sig_end = bands[0][1]
        pad = max(4, int(ch * 0.04))
        return crop_img.crop((0, 0, cw, min(ch, sig_end + pad)))

    except Exception:
        return crop_img  # if anything goes wrong, return original — never block crop


def _ink_detect_signature_crop(img: Image.Image) -> bytes:
    """
    Ink-detection fallback when the LLM confirms a signature but returns no
    bounding boxes (common with featherless-ai-hosted Qwen/Gemma variants).

    img must be in RGB mode (caller normalises before passing).
    Uses an adaptive threshold so it handles both white-background cheques
    and tinted (blue/pink) backgrounds — a fixed threshold of 180 fails on
    tinted cheques where ink and background are both below that level.
    Always returns a PNG — worst case is the full CTS-2010 signature zone.
    """
    w, h = img.size
    # CTS-2010 signature zone: right ~52%, rows 52–80% of height.
    # Stopping at 80% avoids the "Please sign above" instruction text which
    # sits between the name and the MICR band; the actual signature is always
    # fully within this window.
    zx1 = int(w * 0.45)
    zy1 = int(h * 0.52)
    zy2 = int(h * 0.80)
    zone = img.crop((zx1, zy1, w, zy2))

    gray = zone.convert("L")

    # Adaptive threshold — 22% darker than zone mean.
    # On a white cheque: bg_mean ≈ 235, threshold ≈ 183 → ink only.
    # On a blue cheque:  bg_mean ≈ 160, threshold ≈ 125 → ink only, not tint.
    stat = ImageStat.Stat(gray)
    bg_mean = stat.mean[0]
    threshold = max(40, min(220, bg_mean * 0.78))

    ink_mask = gray.point(lambda p: 255 if p < threshold else 0, "L")
    bbox = ink_mask.getbbox()

    if bbox:
        bx1, by1, bx2, by2 = bbox
        pad = max(8, int(min(zone.width, zone.height) * 0.05))
        raw_crop = zone.crop((
            max(0, bx1 - pad),
            max(0, by1 - pad),
            min(zone.width, bx2 + pad),
            min(zone.height, by2 + pad),
        ))
        crop = _trim_crop_bottom(raw_crop)
    else:
        crop = zone  # no ink cluster found — return full zone (very light scan)

    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


def _convert_to_png(raw_bytes: bytes) -> tuple[bytes, Image.Image]:
    """
    Normalises any Pillow-readable source to PNG, returning both the PNG
    bytes and the already-loaded RGB PIL image.

    Returning the PIL image avoids opening it a second time later in the
    request (re-opening can fail on some image modes / Windows PIL builds
    when the BytesIO wrapper is GC'd between calls).

    Scanned cheques are commonly TIFF — no mainstream browser can decode
    TIFF inside an <img> tag, and HF vision LLM providers may reject it too.
    Converting once server-side makes preview and LLM input identical.
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()                   # force full pixel load into memory now
        img = img.convert("RGB")     # normalise mode — handles P, RGBA, CMYK, etc.
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue(), img
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file isn't a readable image.",
        ) from exc


def _convert_to_png_bytes(raw_bytes: bytes) -> bytes:
    """Thin wrapper for the /preview endpoint which only needs the bytes."""
    png_bytes, _ = _convert_to_png(raw_bytes)
    return png_bytes


@router_v1.post("/preview")
async def cloud_extract_preview(
    file: UploadFile = File(...),
    ctx: UserContext = Depends(require_user_context),
) -> Response:
    raw_bytes = await file.read()
    png_bytes = _convert_to_png_bytes(raw_bytes)
    return Response(content=png_bytes, media_type="image/png")


@router_v1.post("", response_model=CloudExtractResponse)
async def cloud_extract_cheque(
    file: UploadFile = File(...),
    model: str = "qwen-72b",
    ctx: UserContext = Depends(require_user_context),
) -> CloudExtractResponse:
    if model not in _MODEL_MAPPING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown model '{model}'. Must be one of {list(_MODEL_MAPPING)}.",
        )

    from openai import AsyncOpenAI

    hf_token = await _resolve_hf_token(ctx.bank_id)
    if hf_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cloud AI demo token not configured — set demo.hf_token in Vault, "
                "or ASTRA_DEMO_HF_TOKEN in the environment for local dev without Vault."
            ),
        )

    hf_base_url = await _resolve_hf_base_url(ctx.bank_id)
    raw_bytes = await file.read()
    # _convert_to_png returns both PNG bytes (for LLM and preview) AND the
    # already-loaded RGB PIL image (reused below for crops — no second open).
    png_bytes, pil_img = _convert_to_png(raw_bytes)
    image_b64 = base64.b64encode(png_bytes).decode("utf-8")

    client = AsyncOpenAI(base_url=hf_base_url, api_key=hf_token)
    model_id = _MODEL_MAPPING[model]

    import openai as openai_module

    try:
        response = await client.chat.completions.create(
            model=model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": CLOUD_EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
            temperature=0,
        )
    except openai_module.APIStatusError as exc:
        # HF answered, but rejected the request — either an account/provider
        # authorization gap, or (as seen with ovhcloud + Qwen2.5-VL-72B) the
        # provider's own hosting of this model is degraded on HF's side.
        # Surface the real reason instead of a generic "unreachable".
        log.error(
            "demo.cloud_extract.hf_rejected",
            bank_id=ctx.bank_id, model=model, status_code=exc.response.status_code, error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hugging Face rejected the request for model '{model}': {exc.message}",
        ) from exc
    except Exception as exc:
        log.error("demo.cloud_extract.hf_call_failed", bank_id=ctx.bank_id, model=model, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cloud AI extraction failed — Hugging Face Inference Providers unreachable.",
        ) from exc

    raw_text = response.choices[0].message.content
    cleaned = _clean_json_response(raw_text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("demo.cloud_extract.invalid_json", bank_id=ctx.bank_id, model=model)
        return CloudExtractResponse(model_used=model, error="INVALID_JSON_RETURNED", raw_response=raw_text)

    # pil_img captured at upload time by _convert_to_png() — no second open needed.

    # Crop signature regions from LLM-returned bboxes (fractional 0.0–1.0).
    signature_crops: list[str] = []
    bboxes = parsed.get("signature_bboxes") or []
    if bboxes and pil_img is not None:
        try:
            w, h = pil_img.size
            for bbox in bboxes:
                if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                    continue
                x1_f, y1_f, x2_f, y2_f = bbox
                x1_f, y1_f = max(0.0, x1_f), max(0.0, y1_f)
                x2_f, y2_f = min(1.0, x2_f), min(1.0, y2_f)
                if x2_f <= x1_f or y2_f <= y1_f:
                    continue
                pad_px = max(4, int(min(w, h) * 0.01))
                x1 = max(0, int(x1_f * w) - pad_px)
                y1 = max(0, int(y1_f * h) - pad_px)
                x2 = min(w, int(x2_f * w) + pad_px)
                y2 = min(h, int(y2_f * h) + pad_px)
                crop = _trim_crop_bottom(pil_img.crop((x1, y1, x2, y2)))
                buf = io.BytesIO()
                crop.save(buf, format="PNG")
                signature_crops.append(base64.b64encode(buf.getvalue()).decode())
        except Exception as exc:
            log.warning("demo.cloud_extract.crop_failed", bank_id=ctx.bank_id, error=str(exc))

    # PIL ink-detection fallback — fires when the LLM confirmed a signature
    # but returned no bbox coords (featherless-ai-hosted models do this).
    # Adaptive threshold handles tinted cheques; always returns at least the
    # CTS-2010 signature zone so the UI always shows something.
    crops_estimated = False
    if not signature_crops and parsed.get("signature_present") == True and pil_img is not None:
        try:
            fb_bytes = _ink_detect_signature_crop(pil_img)
            signature_crops.append(base64.b64encode(fb_bytes).decode())
            crops_estimated = True
            log.info("demo.cloud_extract.ink_detect_fallback_used", bank_id=ctx.bank_id, model=model)
        except Exception as exc:
            log.warning("demo.cloud_extract.ink_detect_fallback_failed", bank_id=ctx.bank_id, error=str(exc))

    log.info(
        "demo.cloud_extract.completed",
        bank_id=ctx.bank_id,
        model=model,
        sig_count=parsed.get("signature_count", 0),
        crops_generated=len(signature_crops),
        crops_estimated=crops_estimated,
    )

    # Reconcile: some models return signature_present=True but forget to set
    # signature_count (or set it to 0). Trust the presence flag as a fallback
    # so the UI count is always consistent with what the model says about presence.
    if parsed.get("signature_present") == True and not parsed.get("signature_count"):
        parsed["signature_count"] = 1
        log.info(
            "demo.cloud_extract.sig_count_reconciled",
            bank_id=ctx.bank_id,
            model=model,
            reason="signature_present=True but signature_count missing/0 — set to 1",
        )

    # Strip fields we emit explicitly so they don't collide as duplicate kwargs.
    # signature_bboxes is kept — returned as-is from the model so the caller
    # can inspect whether the LLM returned coordinates (diagnostic visibility).
    _STRIP = {"signature_crops", "signature_crops_estimated"}
    response_fields = {k: v for k, v in parsed.items() if k not in _STRIP}
    return CloudExtractResponse(
        model_used=model,
        signature_crops=signature_crops if signature_crops else None,
        signature_crops_estimated=crops_estimated if crops_estimated else None,
        **response_fields,
    )
