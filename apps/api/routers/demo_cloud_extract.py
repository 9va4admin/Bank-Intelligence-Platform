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
    Locate handwritten signature strokes, excluding printed block-capital text
    (account-holder name) below the signature. Three independent guards:

    Guard 1 — rule detection (original mask):
        A horizontal rule separating the sig area from the name shows as a
        long contiguous ink band covering ≥ 75 % of zone width. Detected in
        the original (non-eroded) mask because thin rules are erased by erosion.
        Sets a hard y_limit above which we only search.

    Guard 2 — ink run count (original mask):
        Each horizontal scan line through "ANKIT KUMAR" (10 caps) crosses
        12–18 distinct ink segments. A scan line through cursive strokes crosses
        1–5. Rows with > MAX_RUNS (6) are excluded before clustering.
        Uses the ORIGINAL mask — erosion can merge adjacent letter strokes and
        artificially lower the run count for printed text.

    Guard 3 — span check (eroded mask):
        Still done on the eroded mask to filter out thin horizontal rule
        lines that were not caught by Guard 1 (e.g. partial or broken rules).

    All three are independent: any one alone should exclude the name; all
    three together give robust coverage.
    """
    try:
        from PIL import ImageFilter

        zw, zh = zone.size
        if zw < 20 or zh < 20:
            return None

        gray = zone.convert("L")
        threshold = _ink_threshold(gray)

        # Original ink mask (all ink pixels present)
        ink_mask = gray.point(lambda p: 255 if p < threshold else 0, "L")
        o_data = list(ink_mask.getdata())

        # Eroded mask (thin strokes and rule lines shrink away)
        eroded = ink_mask.filter(ImageFilter.MinFilter(3))
        e_data = list(eroded.getdata())

        MIN_SPAN = max(8, int(zw * 0.28))
        MAX_RUNS = 6     # cursive: 1-5 runs/row; block caps: 12-18 runs/row
        MAX_GAP  = 2
        MIN_ROWS = 2     # relaxed: run filter may thin the qualifying cluster

        # ── Guard 1: find topmost horizontal rule in ORIGINAL mask ───────────
        # A rule = any row where the longest contiguous ink run ≥ 75 % of zone.
        RULE_FRAC  = 0.75
        RULE_MIN_W = int(zw * RULE_FRAC)
        y_limit    = zh           # no rule found → search full zone
        for y in range(zh):
            row_ink = [x for x in range(zw) if o_data[y * zw + x] > 128]
            if not row_ink:
                continue
            max_run = cur_run = 1
            for i in range(1, len(row_ink)):
                if row_ink[i] - row_ink[i - 1] == 1:
                    cur_run += 1
                    if cur_run > max_run:
                        max_run = cur_run
                else:
                    cur_run = 1
            if max_run >= RULE_MIN_W:
                y_limit = y     # cut here: everything below is name territory
                break

        # ── Guards 2 + 3: collect signature rows ─────────────────────────────
        sig_rows: list[tuple[int, int, int]] = []
        for y in range(y_limit):
            # Guard 3: eroded span (filters thin rules and isolated noise)
            e_xs = [x for x in range(zw) if e_data[y * zw + x] > 128]
            if not e_xs:
                continue
            span = max(e_xs) - min(e_xs)
            if span < MIN_SPAN:
                continue

            # Guard 2: ink run count on ORIGINAL mask (gap > 3 px = new run)
            o_xs = [x for x in range(zw) if o_data[y * zw + x] > 128]
            if not o_xs:
                continue
            runs = 1
            for i in range(1, len(o_xs)):
                if o_xs[i] - o_xs[i - 1] > 3:
                    runs += 1
            if runs > MAX_RUNS:
                continue    # 12-18 runs → printed block capitals, not handwriting

            sig_rows.append((y, min(e_xs), max(e_xs)))

        if not sig_rows:
            return None

        # ── Cluster and return topmost qualifying cluster ─────────────────────
        clusters: list[list[tuple[int, int, int]]] = []
        cur: list[tuple[int, int, int]] = [sig_rows[0]]
        for i in range(1, len(sig_rows)):
            if sig_rows[i][0] - sig_rows[i - 1][0] <= MAX_GAP:
                cur.append(sig_rows[i])
            else:
                clusters.append(cur)
                cur = [sig_rows[i]]
        clusters.append(cur)

        qualifying = [c for c in clusters if len(c) >= MIN_ROWS]
        best = qualifying[0] if qualifying else max(clusters, key=len)

        return (
            min(r[1] for r in best),
            min(r[0] for r in best),
            max(r[2] for r in best),
            max(r[0] for r in best),
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
    # 62-80 % height: starts below the amount-in-figures box (which sits at
    # ~48-60 % on most CTS-2010 cheques) and ends above the MICR band.
    return img.crop((int(w * 0.40), int(h * 0.62), w, int(h * 0.80)))


_SIG_HANDWRITING_BBOX_PROMPT = """This image is the signature area of an Indian bank cheque.
It contains handwritten cursive pen strokes AND may also contain pre-printed block
capital text (account holder name such as "ANKIT KUMAR").

Your task: return the bounding box of ONLY the handwritten cursive pen strokes.
Do NOT include any printed or typed text in the bounding box.

Coordinates are fractions of this image's size:
  0.0, 0.0 = top-left corner
  1.0, 1.0 = bottom-right corner

Respond with ONLY this JSON — no other text:
{"sig_x1": 0.02, "sig_y1": 0.05, "sig_x2": 0.55, "sig_y2": 0.90}

If you cannot reliably separate handwriting from printed text, respond:
{"sig_x1": null, "sig_y1": null, "sig_x2": null, "sig_y2": null}"""


async def _focused_sig_crop(
    zone: Image.Image,
    client,
    model_id: str,
    bank_id: str,
) -> Image.Image:
    """
    Ask the LLM to locate ONLY the handwritten strokes within the (now tight,
    clean) zone built from the main extraction's signature_bboxes.  The model
    sees just the sig area — no amount box, no payee field — and returns the
    exact bbox of the cursive pen marks excluding any printed name.

    Span classifier is the fallback when the LLM call fails or returns null.
    Never throws.
    """
    zw, zh = zone.size

    # ── Primary: LLM handwriting bbox ───────────────────────────────────────
    if client is not None:
        try:
            buf = io.BytesIO()
            zone.save(buf, format="PNG")
            zone_b64 = base64.b64encode(buf.getvalue()).decode()

            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text",      "text": _SIG_HANDWRITING_BBOX_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{zone_b64}"}},
                    ],
                }],
                temperature=0,
                timeout=30,
            )
            raw  = resp.choices[0].message.content
            data = json.loads(_clean_json_response(raw))

            sx1 = data.get("sig_x1")
            sy1 = data.get("sig_y1")
            sx2 = data.get("sig_x2")
            sy2 = data.get("sig_y2")

            if sx1 is not None and sy1 is not None and sx2 is not None and sy2 is not None:
                lbx1 = int(float(sx1) * zw)
                lby1 = int(float(sy1) * zh)
                lbx2 = int(float(sx2) * zw)
                lby2 = int(float(sy2) * zh)
                # Sanity: bbox must be non-degenerate
                if lbx2 > lbx1 + 5 and lby2 > lby1 + 3:
                    log.info("demo.cloud_extract.sig_bbox_from_llm",
                             bank_id=bank_id,
                             bbox=[round(float(sx1),3), round(float(sy1),3),
                                   round(float(sx2),3), round(float(sy2),3)])
                    return zone.crop((
                        max(0, lbx1), max(0, lby1),
                        min(zw, lbx2), min(zh, lby2),
                    ))
        except Exception as exc:
            log.warning("demo.cloud_extract.sig_bbox_llm_failed",
                        bank_id=bank_id, error=str(exc))

    # ── Fallback: span classifier ────────────────────────────────────────────
    span_bbox = _find_sig_region_by_span(zone)
    if span_bbox:
        bx1, by1, bx2, by2 = span_bbox
        pad_h = max(6, int(zw * 0.04))
        return zone.crop((
            max(0, bx1 - pad_h), max(0, by1 - 4),
            min(zw, bx2 + pad_h), min(zh, by2 + 4),
        ))

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


@router_v1.post("/debug-zone")
async def cloud_extract_debug_zone(
    file: UploadFile = File(...),
    ctx: UserContext = Depends(require_user_context),
) -> Response:
    """Return the raw sig zone crop — no processing — so we can see what the
    algorithm is working with before any classifier or LLM call runs."""
    raw_bytes = await file.read()
    _, pil_img = _convert_to_png(raw_bytes)
    zone = _sig_zone_from_image(pil_img)
    buf = io.BytesIO()
    zone.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router_v1.post("/debug-ink")
async def cloud_extract_debug_ink(
    file: UploadFile = File(...),
    ctx: UserContext = Depends(require_user_context),
) -> dict:
    """
    Return per-row ink statistics for the signature zone so thresholds in
    _find_sig_region_by_span can be tuned against real pixel data.

    Response fields:
      zone_size         — [width, height] of the cropped zone in pixels
      rule_detected_at  — row y where a horizontal rule was found, or null
      rows              — one entry per zone row that has ANY ink after
                          thresholding, with:
            y           — row index (0 = top of zone)
            eroded_span — max(x) - min(x) of eroded ink pixels (Guard 3)
            orig_runs   — number of distinct ink runs in original mask (Guard 2)
            orig_ink_px — total ink pixels in original mask on this row
            orig_span   — span of original ink pixels
            orig_density— orig_ink_px / orig_span (0-1)
            verdict     — "SIG" (would be included) or "SKIP" (filtered out)
      sig_bbox          — [x1,y1,x2,y2] that _find_sig_region_by_span returns,
                          or null if nothing qualified
    """
    from PIL import ImageFilter

    raw_bytes = await file.read()
    _, pil_img = _convert_to_png(raw_bytes)
    zone = _sig_zone_from_image(pil_img)
    zw, zh = zone.size

    gray = zone.convert("L")
    threshold = _ink_threshold(gray)
    ink_mask = gray.point(lambda p: 255 if p < threshold else 0, "L")
    o_data = list(ink_mask.getdata())
    eroded = ink_mask.filter(ImageFilter.MinFilter(3))
    e_data = list(eroded.getdata())

    MIN_SPAN  = max(8, int(zw * 0.28))
    MAX_RUNS  = 6
    RULE_FRAC = 0.75
    RULE_MIN_W = int(zw * RULE_FRAC)

    # Guard 1: rule detection
    rule_y: Optional[int] = None
    for y in range(zh):
        row_ink = [x for x in range(zw) if o_data[y * zw + x] > 128]
        if not row_ink:
            continue
        max_run = cur_run = 1
        for i in range(1, len(row_ink)):
            if row_ink[i] - row_ink[i - 1] == 1:
                cur_run += 1
                if cur_run > max_run:
                    max_run = cur_run
            else:
                cur_run = 1
        if max_run >= RULE_MIN_W:
            rule_y = y
            break
    y_limit = rule_y if rule_y is not None else zh

    # Per-row statistics
    row_stats = []
    for y in range(zh):
        o_xs = [x for x in range(zw) if o_data[y * zw + x] > 128]
        e_xs = [x for x in range(zw) if e_data[y * zw + x] > 128]
        if not o_xs and not e_xs:
            continue  # completely empty row — omit from output

        eroded_span = (max(e_xs) - min(e_xs)) if e_xs else 0
        orig_span   = (max(o_xs) - min(o_xs)) if o_xs else 0
        orig_ink_px = len(o_xs)
        orig_density = round(orig_ink_px / orig_span, 3) if orig_span > 0 else 0.0

        runs = 0
        if o_xs:
            runs = 1
            for i in range(1, len(o_xs)):
                if o_xs[i] - o_xs[i - 1] > 3:
                    runs += 1

        # Reproduce Guard logic to assign verdict
        if y >= y_limit:
            verdict = "BELOW_RULE"
        elif eroded_span < MIN_SPAN:
            verdict = "SKIP_SPAN"
        elif runs > MAX_RUNS:
            verdict = "SKIP_RUNS"
        else:
            verdict = "SIG"

        row_stats.append({
            "y": y,
            "eroded_span": eroded_span,
            "orig_runs": runs,
            "orig_ink_px": orig_ink_px,
            "orig_span": orig_span,
            "orig_density": orig_density,
            "verdict": verdict,
        })

    sig_bbox = _find_sig_region_by_span(zone)

    return {
        "zone_size": [zw, zh],
        "ink_threshold": threshold,
        "min_span": MIN_SPAN,
        "max_runs": MAX_RUNS,
        "rule_detected_at": rule_y,
        "rows": row_stats,
        "sig_bbox": list(sig_bbox) if sig_bbox else None,
    }


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

    # When the LLM confirms a signature exists, build the tightest possible
    # zone from the LLM's own signature_bboxes (preferred) so _focused_sig_crop
    # sees only the sig area with no surrounding cheque fields.  Fall back to
    # _sig_zone_from_image when no bbox is available.
    signature_crops: list[str] = []
    crops_estimated = False
    if parsed.get("signature_present") == True and pil_img is not None:
        try:
            sig_bboxes = parsed.get("signature_bboxes") or []
            iw, ih = pil_img.size
            if sig_bboxes and len(sig_bboxes[0]) == 4:
                bx1f, by1f, bx2f, by2f = sig_bboxes[0]
                bbox_h_frac = by2f - by1f

                # LLM anchors its bbox to the middle/body of the strokes and
                # consistently misses the ascenders at the top.  Pad upward by
                # at least half the bbox height so the full signature is visible.
                top_pad = max(0.04, bbox_h_frac * 0.5)

                cx1 = max(0,  int(bx1f * iw))
                cy1 = max(0,  int((by1f - top_pad) * ih))
                cx2 = min(iw, int(bx2f * iw))
                cy2 = min(ih, int(by2f * ih))
                crop = pil_img.crop((cx1, cy1, cx2, cy2))
            else:
                crop = _sig_zone_from_image(pil_img)
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
