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


def _ink_threshold(gray_img: Image.Image) -> int:
    """
    Returns an intensity threshold that isolates actual dark ink strokes from
    both white backgrounds AND security printing patterns (the grey checkered/
    lattice patterns on CTS-2010 cheques).

    Uses the 10th-percentile pixel intensity + a small buffer.  The darkest
    ~10% of pixels in the signature zone are actual ink strokes; the threshold
    lands just above that range, so the security pattern (which is lighter than
    pen ink) is excluded.

    Clamped to [50, 100] — never so tight that light ink is missed, never so
    loose that the security pattern registers as ink.
    """
    data = sorted(gray_img.getdata())
    n = len(data)
    if n == 0:
        return 80
    p10 = data[max(0, n // 10)]
    return max(50, min(100, p10 + 28))


def _find_sig_region_by_span(
    zone: Image.Image,
) -> Optional[tuple[int, int, int, int]]:
    """
    Locate the handwritten signature within a zone image.

    THREE-LAYER STRATEGY
    --------------------
    Layer 1 — horizontal rule detection:
        The printed underline in the cheque's signature box spans ≥ 70 % of the
        zone width (it goes edge-to-edge of the signature field).  Cursive strokes
        span 28–65 % typically.  The first row that hits the 70 % threshold is
        treated as the separator between the signature (above) and the printed
        account-holder name (below).  All rows at or below that rule are ignored.

    Layer 2 — span filter:
        Rows with ink spanning 28–70 % of zone width are "sig candidate rows";
        rows narrower than 28 % (individual printed characters) are ignored.

    Layer 3 — topmost qualifying cluster:
        Candidate rows above the rule are clustered (MAX_GAP=2).  The topmost
        cluster with ≥ 3 rows is selected — the signature always appears above
        the printed name in this zone, so "topmost" beats "largest".

    If no horizontal rule is found, layers 2 and 3 still apply to all candidate
    rows, with the topmost cluster selected.

    Always returns a valid tuple or None — never throws.
    """
    try:
        from PIL import ImageFilter

        zw, zh = zone.size
        if zw < 20 or zh < 20:
            return None

        gray = zone.convert("L")
        threshold = _ink_threshold(gray)
        ink_mask = gray.point(lambda p: 255 if p < threshold else 0, "L")
        # Eroded mask: removes 1-px noise; pen strokes (3-8 px) survive.
        # Do NOT use it for rule detection — MinFilter(3) destroys thin printed
        # rules (1-2 px), causing rule detection to silently fail.
        eroded = ink_mask.filter(ImageFilter.MinFilter(3))
        orig_data = list(ink_mask.getdata())   # rule detection: thin line survives
        e_data    = list(eroded.getdata())      # sig candidate rows: noise removed

        MIN_SPAN  = max(8, int(zw * 0.28))   # min span for a sig candidate row
        RULE_SPAN = int(zw * 0.70)            # min span to classify a row as the printed rule
        RULE_FILL = 0.35                       # min fill ratio: real rule is dense, cursive is sparse
        MAX_GAP   = 2                          # max gap rows allowed inside one cluster
        MIN_ROWS  = 3                          # minimum rows for a cluster to qualify

        # Pass 1: locate the first horizontal rule using the ORIGINAL (non-eroded) mask.
        first_rule_y: Optional[int] = None
        for y in range(zh):
            ink_xs = [x for x in range(zw) if orig_data[y * zw + x] > 128]
            if not ink_xs:
                continue
            span = max(ink_xs) - min(ink_xs)
            fill = len(ink_xs) / span if span > 0 else 0
            # Wide AND dense → printed horizontal rule (not a sparse cursive stroke).
            if span >= RULE_SPAN and fill >= RULE_FILL:
                first_rule_y = y
                break

        # Pass 2: collect sig candidate rows from eroded mask, stopping at the rule.
        sig_rows: list[tuple[int, int, int]] = []
        y_limit = first_rule_y if first_rule_y is not None else zh
        for y in range(y_limit):
            ink_xs = [x for x in range(zw) if e_data[y * zw + x] > 128]
            if not ink_xs:
                continue
            span = max(ink_xs) - min(ink_xs)
            if span >= MIN_SPAN:
                sig_rows.append((y, min(ink_xs), max(ink_xs)))

        if not sig_rows:
            return None

        # Cluster consecutive sig rows (MAX_GAP allows internal cursive stroke gaps).
        clusters: list[list[tuple[int, int, int]]] = []
        cur: list[tuple[int, int, int]] = [sig_rows[0]]
        for i in range(1, len(sig_rows)):
            if sig_rows[i][0] - sig_rows[i - 1][0] <= MAX_GAP:
                cur.append(sig_rows[i])
            else:
                clusters.append(cur)
                cur = [sig_rows[i]]
        clusters.append(cur)

        # Topmost qualifying cluster = the signature (it appears above the name).
        qualifying = [c for c in clusters if len(c) >= MIN_ROWS]
        best = qualifying[0] if qualifying else max(clusters, key=len)

        return (
            min(r[1] for r in best),  # x1
            min(r[0] for r in best),  # y1
            max(r[2] for r in best),  # x2
            max(r[0] for r in best),  # y2
        )

    except Exception:
        return None


def _sig_zone_from_image(img: Image.Image) -> Image.Image:
    """
    Pre-crop the full cheque to the rough signature zone.

    The only assumption required: on any Indian CTS-2010 cheque the signature
    is in the lower-right quadrant.  This is a coarse, generous crop — we are
    NOT trying to isolate the signature here, just narrow the field of view so
    the focused LLM call sees fewer distracting elements.
    """
    w, h = img.size
    return img.crop((int(w * 0.40), int(h * 0.48), w, int(h * 0.82)))


_SIG_FOCUS_PROMPT = """This image is the signature area of an Indian bank cheque.
It may contain handwritten ink strokes AND printed text (account name, "Please sign above", a horizontal line, bank labels).

Return ONLY this JSON — no other text:
{"bbox": [x1, y1, x2, y2]}

x1 y1 x2 y2 are decimal fractions of THIS image (0.0 = left/top edge, 1.0 = right/bottom edge).
Box ONLY the cursive handwritten ink strokes a human hand drew.
Exclude all printed text, horizontal rules, and blank space.
If no handwritten signature is visible return: {"bbox": []}"""


async def _focused_sig_crop(
    zone: Image.Image,
    client,
    model_id: str,
    bank_id: str,
) -> Image.Image:
    """
    Extract the handwritten signature from the pre-cropped zone.

    PRIMARY — span classifier:  clusters rows where ink sweeps ≥ 28 % of zone
    width (cursive strokes), with MAX_GAP=2.  The gap between the signature
    underline and the printed account-holder name below is typically 4-6 rows,
    which exceeds MAX_GAP, so the two split into separate clusters and the
    largest cluster wins — the signature.  This is the reliable path.

    FALLBACK — focused LLM call:  used only when the span classifier finds
    nothing (e.g. a compact or unusually faint signature that falls below the
    span threshold).  The LLM receives only the zone image and is asked to
    locate the handwritten strokes.

    Always returns a valid Image — never throws.
    """
    zw, zh = zone.size

    # PRIMARY: span-based cluster analysis
    span_bbox = _find_sig_region_by_span(zone)
    if span_bbox:
        bx1, by1, bx2, by2 = span_bbox
        pad_h = max(6, int(zw * 0.04))
        log.info("demo.cloud_extract.span_classifier_used", bank_id=bank_id,
                 bx1=bx1, by1=by1, bx2=bx2, by2=by2)
        return zone.crop((
            max(0, bx1 - pad_h), max(0, by1 - 4),
            min(zw, bx2 + pad_h), min(zh, by2 + 4),
        ))

    # FALLBACK: focused LLM call when span classifier finds nothing
    try:
        buf = io.BytesIO()
        zone.save(buf, format="PNG")
        zone_b64 = base64.b64encode(buf.getvalue()).decode()

        resp = await client.chat.completions.create(
            model=model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _SIG_FOCUS_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{zone_b64}"}},
                ],
            }],
            temperature=0,
            timeout=30,
        )

        raw = resp.choices[0].message.content
        cleaned = _clean_json_response(raw)
        data = json.loads(cleaned)
        bbox = data.get("bbox") or []

        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            log.warning("demo.cloud_extract.focused_sig_no_bbox", bank_id=bank_id)
            return zone

        x1_f, y1_f, x2_f, y2_f = [float(v) for v in bbox]
        if x2_f <= x1_f or y2_f <= y1_f or x1_f < 0 or y1_f < 0:
            log.warning("demo.cloud_extract.focused_sig_invalid_bbox", bank_id=bank_id, bbox=bbox)
            return zone

        pad = max(4, int(min(zw, zh) * 0.03))
        x1 = max(0, int(x1_f * zw) - pad)
        y1 = max(0, int(y1_f * zh) - pad)
        x2 = min(zw, int(x2_f * zw) + pad)
        y2 = min(zh, int(y2_f * zh) + pad)
        log.info("demo.cloud_extract.focused_llm_used", bank_id=bank_id,
                 x1_f=round(x1_f, 3), y1_f=round(y1_f, 3), x2_f=round(x2_f, 3), y2_f=round(y2_f, 3))
        return zone.crop((x1, y1, x2, y2))

    except Exception as exc:
        log.warning("demo.cloud_extract.focused_sig_failed", bank_id=bank_id, error=str(exc))
        return zone


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

    # When the LLM confirms a signature exists, make a second focused call with
    # only the pre-cropped signature zone.  The Vision model sees a simple image
    # (3-4 elements) and identifies the handwritten strokes directly — no
    # computer-vision math needed.  The span classifier is the fallback inside
    # _focused_sig_crop if the second call fails.
    signature_crops: list[str] = []
    crops_estimated = False
    if parsed.get("signature_present") == True and pil_img is not None:
        try:
            zone = _sig_zone_from_image(pil_img)
            crop = await _focused_sig_crop(zone, client, model_id, ctx.bank_id)
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            signature_crops.append(base64.b64encode(buf.getvalue()).decode())
        except Exception as exc:
            log.warning("demo.cloud_extract.sig_crop_failed", bank_id=ctx.bank_id, error=str(exc))

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
