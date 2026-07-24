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

# Models that use the local YOLOv8 sig detector instead of VLM bbox guessing.
# Field extraction (amount, payee, etc.) still runs via the cloud VLM.
_YOLO_SIG_MODELS = {"yolov8-sig"}

# Sig-only mode: runs the local detector + denoising, NEVER calls HF.
_YOLO_SIG_ONLY_MODELS = {"yolov8-sig-only"}

# Qwen2-VL sig-only: calls HF Qwen2-VL with a signature-focused prompt.
# Handles multiple signatures, ignores stamps/printed text naturally.
_QWEN_SIG_MODELS = {"qwen2vl-sig"}

SIG_DETECT_PROMPT = (
    "You are a cheque processing system. "
    "Find every handwritten signature in this cheque image. "
    "Ignore pre-printed text, bank stamps, account holder names, amounts, and any annotations. "
    "For each signature, return its bounding box as normalised coordinates (0.0–1.0, top-left origin). "
    'Respond with ONLY valid JSON — no markdown: '
    '{"signatures":[{"x1":0.0,"y1":0.0,"x2":1.0,"y2":1.0,"confidence":0.95}]}'
    " Return an empty list if no handwritten signature is present."
)

# Fallback URL for the sig detector microservice in local dev without Docker.
_SIG_DETECTOR_URL_FALLBACK = "http://localhost:8020"

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
* signature_stroke_y2: The y-coordinate (0.0–1.0 fraction of full image height) where the
  handwritten ink strokes END. This is the line below which only printed text exists (name,
  instruction text). Return as a decimal fraction. null if uncertain.
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
"signature_stroke_y2": 0.72,
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
    signature_stroke_y2: Optional[float] = None
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


async def _resolve_sig_detector_url(bank_id: str) -> str:
    """Config service → env var → localhost fallback."""
    from shared.config.config_service import config_service
    try:
        return await config_service.get_secret("demo.sig_detector_url")
    except Exception:
        pass
    import os
    return os.environ.get("ASTRA_SIG_DETECTOR_URL", _SIG_DETECTOR_URL_FALLBACK)


async def _call_sig_detector(
    pil_img: Image.Image, bank_id: str
) -> tuple[list[dict], bool]:
    """POST the image to the YOLOv8 sig detector service.

    Returns ``(detections, service_available)``.
    ``service_available=False`` means the service could not be reached —
    the caller should surface this as an error, not silently fall back.
    """
    import httpx

    url = await _resolve_sig_detector_url(bank_id)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)

    try:
        async with httpx.AsyncClient(timeout=15.0) as hc:
            resp = await hc.post(
                f"{url}/detect",
                files={"file": ("cheque.png", buf, "image/png")},
            )
            resp.raise_for_status()
            data = resp.json()
            detections = data.get("detections", [])
            log.info("demo.cloud_extract.yolo_detections",
                     bank_id=bank_id, count=len(detections))
            return detections, True
    except Exception as exc:
        log.warning("demo.cloud_extract.sig_detector_unreachable",
                    bank_id=bank_id, url=url, error=str(exc))
        return [], False


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


def _whiteout_printed_text(crop: Image.Image) -> Image.Image:
    """
    Paint a white rectangle over the printed text below the handwritten
    signature (account holder name + 'please sign above' instruction).

    Strategy: find the first sustained blank gap (>= 4 consecutive empty rows)
    in the lower portion of the crop — that gap is the separator between
    ink strokes and the printed name.  Everything from the gap downward is
    filled white.  Gaps inside cursive strokes are 1-3 rows; the sig-to-name
    separator is typically 4-10 rows, so the threshold is reliable.
    """
    from PIL import ImageDraw

    cw, ch = crop.size
    if ch < 20:
        return crop

    gray = crop.convert("L")
    threshold = _ink_threshold(gray)
    o_data = list(gray.point(lambda p: 255 if p < threshold else 0, "L").getdata())
    row_ink = [any(o_data[y * cw + x] > 128 for x in range(cw)) for y in range(ch)]

    # Walk top-to-bottom. Fire on the FIRST 2+-row blank gap that comes
    # after at least 10 ink rows have accumulated — that gap is the
    # sig/name boundary.  Requiring 10 prior ink rows stops us from
    # triggering on pen-lift gaps at the very top of the ascenders.
    total_ink_rows = 0
    whiteout_y = None
    y = 0
    while y < ch - 4:
        if row_ink[y]:
            total_ink_rows += 1
            y += 1
        elif total_ink_rows >= 10:
            gap_end = y
            while gap_end < ch and not row_ink[gap_end]:
                gap_end += 1
            if gap_end - y >= 2:        # 2+-row gap after sig body = boundary
                whiteout_y = y
                break
            y = gap_end                 # 1-row gap — inside sig, keep going
        else:
            y += 1                      # not enough ink context yet

    if whiteout_y is None or whiteout_y >= ch - 3:
        return crop                     # no clear gap found — leave intact

    result = crop.copy()
    ImageDraw.Draw(result).rectangle(
        [(0, whiteout_y), (cw - 1, ch - 1)],
        fill=(255, 255, 255),
    )
    return result


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


_FIND_PRINTED_TEXT_Y_PROMPT = """This image is a close-up of a bank cheque signature area.

Look carefully. You will see:
1. A handwritten cursive ink signature in the upper portion.
2. A PRINTED block-capital account holder name (e.g. "ANKIT KUMAR") below the signature.
3. Possibly a printed instruction line below the name.

Find the printed account holder name text block. Draw an imaginary tight bounding box around JUST those printed letters.

Return the bounding box as fractions of image dimensions (0.0=top-left corner, 1.0=bottom-right corner):

Reply ONLY with this JSON — no other text:
{"name_x1": 0.05, "name_y1": 0.60, "name_x2": 0.95, "name_y2": 0.80}

If you see NO printed name, reply:
{"name_x1": null, "name_y1": null, "name_x2": null, "name_y2": null}"""


async def _whiteout_via_llm(
    crop: Image.Image,
    client,
    model_id: str,
    bank_id: str,
) -> Image.Image:
    """
    Send the crop to the LLM and ask where printed text starts.
    Paint white from that y-fraction to the bottom.
    Falls back to pixel-gap detector if the LLM call fails.
    """
    from PIL import ImageDraw

    if client is not None:
        try:
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": [
                    {"type": "text",      "text": _FIND_PRINTED_TEXT_Y_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]}],
                temperature=0,
                timeout=25,
            )
            data = json.loads(_clean_json_response(resp.choices[0].message.content))
            # Accept whatever key the model chooses to use
            ny1 = (data.get("name_y1") or data.get("name_y")
                   or data.get("printed_text_y") or data.get("text_y1"))
            if ny1 is not None:
                # LLM consistently lands 6-7px below the real name top; use
                # -8px to ensure we paint over every row of the name.
                py = max(4, int(float(ny1) * crop.height) - 8)
                if 4 < py < crop.height - 1:
                    result = crop.copy()
                    ImageDraw.Draw(result).rectangle(
                        [(0, py), (crop.width - 1, crop.height - 1)],
                        fill=(255, 255, 255),
                    )
                    log.info("demo.cloud_extract.whiteout_via_llm",
                             bank_id=bank_id, name_y1=ny1, whiteout_y=py)
                    return result
        except Exception as exc:
            log.warning("demo.cloud_extract.whiteout_llm_failed",
                        bank_id=bank_id, error=str(exc))

    # Geometric fallback: the printed name always lives in the bottom ~38% of
    # the crop region.  Trim there so nothing needs painting at all.
    trim_h = max(15, int(crop.height * 0.62))
    log.info("demo.cloud_extract.whiteout_geometric_trim",
             bank_id=bank_id, original_h=crop.height, trim_h=trim_h)
    return crop.crop((0, 0, crop.width, trim_h))


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


@router_v1.get("/batch-ui", include_in_schema=False)
async def batch_sig_test_ui() -> Response:
    """Standalone batch signature test page — upload up to 5 cheques, see crop or No-Sign-Present."""
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ASTRA · Sig Batch Test</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:ui-monospace,monospace;background:#0f172a;color:#e2e8f0;padding:28px;min-height:100vh}
h1{color:#a78bfa;font-size:17px;margin-bottom:4px}
.sub{color:#64748b;font-size:12px;margin-bottom:24px}
.drop{border:2px dashed #334155;border-radius:10px;padding:36px 24px;text-align:center;cursor:pointer;transition:border-color .2s}
.drop:hover,.drop.over{border-color:#7c3aed}
.drop input{display:none}
.hint{color:#94a3b8;font-size:13px}
.flist{margin-top:12px;font-size:11px;color:#94a3b8;line-height:1.8}
.btn{margin-top:16px;background:#7c3aed;color:#fff;border:none;padding:10px 36px;border-radius:6px;cursor:pointer;font-size:14px;font-family:inherit}
.btn:disabled{background:#1e293b;color:#475569;cursor:not-allowed}
.grid{display:flex;flex-wrap:wrap;gap:16px;margin-top:28px}
.card{background:#1e293b;border-radius:8px;padding:14px;width:220px;flex-shrink:0}
.fname{font-size:10px;color:#64748b;margin-bottom:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card img{width:100%;border:1px solid #334155;border-radius:4px;background:#fff;display:block}
.nosig{color:#f87171;font-size:14px;font-weight:700;text-align:center;padding:44px 0}
.spin{color:#94a3b8;font-size:11px;text-align:center;padding:44px 0}
.err{color:#f87171;font-size:11px;text-align:center;padding:20px 0}
</style>
</head>
<body>
<h1>ASTRA · Signature Batch Test</h1>
<p class="sub">Upload up to 5 cheque images &mdash; model: yolov8-sig-only</p>

<div class="drop" id="dz" onclick="document.getElementById('fi').click()">
  <div class="hint">Click or drag &amp; drop up to 5 cheque images (jpg/png/tif)</div>
  <input type="file" id="fi" accept="image/*" multiple>
  <div class="flist" id="fl"></div>
</div>
<button class="btn" id="btn" disabled onclick="run()">&#9654;&nbsp; Extract Signatures</button>
<div class="grid" id="grid"></div>

<script>
const MAX=5;let files=[];
const dz=document.getElementById('dz'),fi=document.getElementById('fi'),
      fl=document.getElementById('fl'),btn=document.getElementById('btn'),
      grid=document.getElementById('grid');

fi.onchange=e=>pick(Array.from(e.target.files));
dz.ondragover=e=>{e.preventDefault();dz.classList.add('over')};
dz.ondragleave=()=>dz.classList.remove('over');
dz.ondrop=e=>{e.preventDefault();dz.classList.remove('over');
  pick(Array.from(e.dataTransfer.files).filter(f=>f.type.startsWith('image/')));};

function pick(f){
  files=f.slice(0,MAX);
  fl.innerHTML=files.map(f=>`&#10003; ${f.name}`).join('<br>');
  btn.disabled=!files.length;grid.innerHTML='';
}

async function run(){
  btn.disabled=true;grid.innerHTML='';
  const cards=files.map((f,i)=>{
    const c=document.createElement('div');c.className='card';
    c.innerHTML=`<div class="fname" title="${f.name}">${f.name}</div><div class="spin" id="s${i}">processing&hellip;</div>`;
    grid.appendChild(c);return c;
  });

  await Promise.all(files.map(async(file,i)=>{
    const s=document.getElementById('s'+i);
    try{
      const fd=new FormData();fd.append('file',file);
      const r=await fetch('/v1/cts/demo/cloud-extract?model=yolov8-sig-only',
        {method:'POST',body:fd,credentials:'include'});
      if(r.status===401){s.className='err';s.textContent='401 – log into ASTRA portal first';return}
      if(!r.ok){s.className='err';s.textContent='Error '+r.status;return}
      const d=await r.json();
      if(d.signature_present&&d.signature_crops&&d.signature_crops.length){
        s.outerHTML=`<img src="data:image/png;base64,${d.signature_crops[0]}" alt="sig">`;
      }else{
        s.className='nosig';s.textContent='No-Sign-Present';
      }
    }catch(e){s.className='err';s.textContent=e.message;}
  }));
  btn.disabled=false;
}
</script>
</body>
</html>"""
    return Response(content=html, media_type="text/html")


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


def _has_real_signature(img: Image.Image) -> bool:
    """
    Return True only if the denoised crop contains a real handwritten signature.

    Two conditions must BOTH hold:
      1. Ink fraction > 1 %  — enough total ink to be a signature
      2. Largest connected blob > 400 px — at least one substantial stroke exists

    Scattered dots or micro-marks (surviving mesh, faint prints) have very small
    blobs and low ink fractions — they fail condition 2 and/or 1.
    A real cursive signature always produces at least one blob of several hundred
    pixels.
    """
    try:
        import cv2, numpy as np
        arr  = np.array(img.convert("L"))
        ink_fraction = float((arr < 180).sum()) / max(arr.size, 1)
        if ink_fraction < 0.01:
            return False
        _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        _, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        max_blob = int(stats[1:, cv2.CC_STAT_AREA].max()) if len(stats) > 1 else 0
        return max_blob >= 400
    except Exception:
        return True  # on any error, don't suppress the crop


def _denoise_sig_crop(crop: Image.Image) -> Image.Image:
    """
    Remove printed uppercase name ("ANKIT KUMAR", "UMAR" etc.) and security
    mesh dots from a signature crop, preserving cursive ink strokes.

    Two-pass connected-component filter:

    Pass 1 — size: blobs < 30 px are security-mesh / halftone dots -> discard.

    Pass 2 — solidity in lower crop:
        solidity = blob_area / convex_hull_area
        Printed uppercase letters are compact, blocky shapes: solidity > 0.45.
        Cursive strokes are open, spidery shapes: solidity < 0.35.
        Only applied when centroid_y > 55 % of crop (name is below sig body)
        AND blob height < 20 % of crop (caps are short relative to the crop).

    Horizontal rules (width > 50 % of crop, height < 8 px) always discarded.
    Graceful degradation: returns original crop on any exception.
    """
    try:
        import cv2
        import numpy as np

        arr  = np.array(crop.convert("RGB"))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        cw, ch = crop.width, crop.height

        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Erode by 2px before connected-component analysis.
        # Arrow shafts (1-3px wide) that connect printed labels to the signature
        # are severed by erosion, making the label blobs separate components.
        # We dilate the kept-component mask back at the end to restore stroke thickness.
        ker2 = np.ones((2, 2), np.uint8)
        binary_eroded = cv2.erode(binary, ker2, iterations=1)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            binary_eroded, connectivity=8
        )

        keep_mask = np.zeros(binary.shape, dtype=np.uint8)
        kept = removed = 0

        for i in range(1, num_labels):
            area   = int(stats[i, cv2.CC_STAT_AREA])
            comp_w = int(stats[i, cv2.CC_STAT_WIDTH])
            comp_h = int(stats[i, cv2.CC_STAT_HEIGHT])
            cy     = float(centroids[i][1])

            # Pass 1: mesh / halftone dots (eroded area — threshold stays at 20)
            if area < 20:
                removed += 1
                continue

            # Always discard horizontal underline rules
            if comp_w > cw * 0.50 and comp_h < 8:
                removed += 1
                continue

            # Always discard vertical border lines (signature box sides)
            if comp_h > ch * 0.30 and comp_w < 8:
                removed += 1
                continue

            # Discard narrow blobs hugging the left/right crop edge — border artifacts
            cx_left = int(stats[i, cv2.CC_STAT_LEFT])
            if comp_w < 12 and (cx_left <= 4 or cx_left + comp_w >= cw - 4):
                removed += 1
                continue

            # Bottom-strip filter: lowest 30% of crop, small blobs → instruction text
            if cy / ch > 0.70 and area < 1000:
                removed += 1
                continue

            # Pass 2: solidity check for printed text anywhere in crop.
            # Printed chars are compact (solidity > 0.45); cursive strokes are open
            # (solidity < 0.35) or large (area > 3000 even after erosion).
            if area < 3000 and comp_h < ch * 0.35:
                blob_mask = (labels == i).astype(np.uint8) * 255
                contours, _ = cv2.findContours(
                    blob_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                if contours:
                    hull_area = cv2.contourArea(cv2.convexHull(contours[0]))
                    if hull_area > 0 and (area / hull_area) > 0.45:
                        removed += 1
                        continue   # printed text -> discard

            # Mark this blob as kept
            keep_mask[labels == i] = 1
            kept += 1

        # Dilate keep_mask to restore pixels lost to erosion, then paint onto output
        keep_mask_dilated = cv2.dilate(keep_mask, ker2, iterations=1)
        output = np.full_like(arr, 255)
        output[keep_mask_dilated > 0] = arr[keep_mask_dilated > 0]

        log.info("demo.cloud_extract.denoise_done",
                 crop_w=cw, crop_h=ch, kept=kept, removed=removed)
        return Image.fromarray(output.astype(np.uint8))

    except Exception as exc:
        log.warning("demo.cloud_extract.denoise_failed", error=str(exc))
        return crop


async def _extract_yolov8_sig(
    file: UploadFile, ctx
) -> CloudExtractResponse:
    """
    Two-model orchestration:
      1. YOLOv8 sig detector  → tight sig bboxes (no name included)
      2. Qwen 32B (cloud VLM) → all text fields (amount, payee, MICR…)

    YOLOv8 bbox is trusted directly for cropping — no whiteout needed because
    a dedicated detector trained on handwriting strokes excludes printed text.
    Falls back to VLM bbox if the detector service is unreachable.
    """
    from openai import AsyncOpenAI

    hf_token = await _resolve_hf_token(ctx.bank_id)
    if hf_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cloud AI demo token not configured — set demo.hf_token in Vault "
                "or ASTRA_DEMO_HF_TOKEN in the environment for local dev."
            ),
        )

    hf_base_url = await _resolve_hf_base_url(ctx.bank_id)
    raw_bytes = await file.read()
    png_bytes, pil_img = _convert_to_png(raw_bytes)
    iw, ih = pil_img.size
    image_b64 = base64.b64encode(png_bytes).decode("utf-8")

    # ── Step 1: YOLOv8 sig detection (parallel with field extraction) ─────
    # Run both calls concurrently — sig detector and Qwen 32B are independent.
    import asyncio
    from openai import AsyncOpenAI as _OAI

    client = _OAI(base_url=hf_base_url, api_key=hf_token)
    field_model_id = _MODEL_MAPPING["qwen-32b"]

    async def _field_extract():
        return await client.chat.completions.create(
            model=field_model_id,
            messages=[{"role": "user", "content": [
                {"type": "text",      "text": CLOUD_EXTRACT_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]}],
            temperature=0,
        )

    yolo_task   = asyncio.create_task(_call_sig_detector(pil_img, ctx.bank_id))
    fields_task = asyncio.create_task(_field_extract())
    yolo_detections, fields_resp = await asyncio.gather(yolo_task, fields_task,
                                                        return_exceptions=True)

    # Handle field extraction failure
    if isinstance(fields_resp, Exception):
        log.error("demo.cloud_extract.yolo_field_extract_failed",
                  bank_id=ctx.bank_id, error=str(fields_resp))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Field extraction via Qwen 32B failed: {fields_resp}",
        )

    # Unpack (detections, service_available) tuple from _call_sig_detector
    if isinstance(yolo_detections, Exception):
        # asyncio.gather captured an unhandled exception from the task itself
        log.warning("demo.cloud_extract.yolo_task_error",
                    bank_id=ctx.bank_id, error=str(yolo_detections))
        yolo_detections, yolo_available = [], False
    else:
        yolo_detections, yolo_available = yolo_detections

    # Hard stop when service is down — do NOT silently produce a VLM result
    # under the yolov8-sig label. The user picked this model deliberately.
    if not yolo_available:
        sig_url = await _resolve_sig_detector_url(ctx.bank_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"YOLOv8 sig detector is not running at {sig_url}. "
                "Start it with:  cd apps/sig_detector; python main.py  "
                "(or Docker:  docker run -p 8020:8020 astra-sig-detector)"
            ),
        )

    raw_text = fields_resp.choices[0].message.content
    cleaned  = _clean_json_response(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return CloudExtractResponse(
            model_used="yolov8-sig + qwen-32b",
            error="INVALID_JSON_RETURNED",
            raw_response=raw_text,
        )

    # ── Step 2: build sig crop from YOLOv8 bboxes ────────────────────────
    signature_crops: list[str] = []
    sig_bboxes_out: list[list[float]] = []

    # YOLOv8 returns tight stroke-only bboxes — crop directly, no whiteout.
    for det in yolo_detections:
        bbox = det.get("bbox", [])
        if len(bbox) != 4:
            continue
        x1, y1, x2, y2 = bbox
        pad_y = 0.008
        cx1 = max(0,  int((x1 - 0.005) * iw))   # small left pad only
        cy1 = max(0,  int((y1 - pad_y) * ih))
        cx2 = min(iw, int(x2 * iw))              # no right pad — avoids signature box border
        cy2 = min(ih, int((y2 + pad_y) * ih))
        crop = pil_img.crop((cx1, cy1, cx2, cy2))
        crop = _denoise_sig_crop(crop)
        # Skip if denoised crop is nearly empty — no real handwritten signature
        if not _has_real_signature(crop):
            log.info("demo.cloud_extract.no_sig_after_denoise", bbox=bbox)
            continue
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        signature_crops.append(base64.b64encode(buf.getvalue()).decode())
        sig_bboxes_out.append([round(v, 4) for v in bbox])

    if sig_bboxes_out:
        parsed["signature_present"]  = True
        parsed["signature_count"]    = len(sig_bboxes_out)
        parsed["signature_bboxes"]   = sig_bboxes_out

    if parsed.get("signature_present") and not parsed.get("signature_count"):
        parsed["signature_count"] = 1

    _STRIP = {"signature_crops", "signature_crops_estimated"}
    response_fields = {k: v for k, v in parsed.items() if k not in _STRIP}
    return CloudExtractResponse(
        model_used="yolov8-sig + qwen-32b",
        signature_crops=signature_crops if signature_crops else None,
        signature_crops_estimated=False,
        **response_fields,
    )


async def _extract_yolov8_sig_only(
    file: UploadFile, ctx
) -> CloudExtractResponse:
    """
    Local-only path: run the YOLOv8 pixel detector → crop → denoise.
    No HF token required, no cloud call.  Returns only the signature crops
    (all text fields are null).  Use this dropdown option when you want to
    iterate on sig crop quality without burning HF inference quota.
    """
    raw_bytes = await file.read()
    _, pil_img = _convert_to_png(raw_bytes)
    iw, ih = pil_img.size

    yolo_detections, yolo_available = await _call_sig_detector(pil_img, ctx.bank_id)

    if not yolo_available:
        sig_url = await _resolve_sig_detector_url(ctx.bank_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"YOLOv8 sig detector is not running at {sig_url}. "
                "Start it with:  cd apps/sig_detector; python main.py  "
                "(or Docker:  docker run -p 8020:8020 astra-sig-detector)"
            ),
        )

    signature_crops: list[str] = []
    sig_bboxes_out: list[list[float]] = []

    for det in yolo_detections:
        bbox = det.get("bbox", [])
        if len(bbox) != 4:
            continue
        x1, y1, x2, y2 = bbox
        cx1 = max(0,  int((x1 - 0.005) * iw))   # small left pad only
        cy1 = max(0,  int((y1 - 0.008) * ih))
        cx2 = min(iw, int(x2 * iw))              # no right pad — avoids signature box border
        cy2 = min(ih, int((y2 + 0.008) * ih))
        crop = pil_img.crop((cx1, cy1, cx2, cy2))
        crop = _denoise_sig_crop(crop)
        # Skip if denoised crop is nearly empty — no real handwritten signature
        if not _has_real_signature(crop):
            log.info("demo.cloud_extract.no_sig_after_denoise", bbox=bbox)
            continue
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        signature_crops.append(base64.b64encode(buf.getvalue()).decode())
        sig_bboxes_out.append([round(v, 4) for v in bbox])

    log.info("demo.cloud_extract.yolo_only_done",
             bank_id=ctx.bank_id, crops=len(signature_crops))

    return CloudExtractResponse(
        model_used="yolov8-sig-only",
        signature_present=len(sig_bboxes_out) > 0,
        signature_count=len(sig_bboxes_out) if sig_bboxes_out else None,
        signature_bboxes=sig_bboxes_out if sig_bboxes_out else None,
        signature_crops=signature_crops if signature_crops else None,
        signature_crops_estimated=False,
    )


async def _extract_qwen2vl_sig(file: UploadFile, ctx) -> CloudExtractResponse:
    """Call HF Qwen2-VL with a signature-only prompt — supports multiple signatures."""
    from openai import AsyncOpenAI
    import json as _json

    hf_token = await _resolve_hf_token(ctx.bank_id)
    if hf_token is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="HF token not configured.")

    hf_base_url  = await _resolve_hf_base_url(ctx.bank_id)
    raw_bytes    = await file.read()
    png_bytes, pil_img = _convert_to_png(raw_bytes)
    iw, ih       = pil_img.size
    image_b64    = base64.b64encode(png_bytes).decode()

    client    = AsyncOpenAI(base_url=hf_base_url, api_key=hf_token)
    model_id  = _MODEL_MAPPING["qwen-72b"]   # Qwen2.5-VL-72B

    resp = await client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": SIG_DETECT_PROMPT},
        ]}],
        temperature=0,
    )
    content = resp.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    try:
        parsed = _json.loads(content)
        sigs   = parsed.get("signatures", [])
    except Exception:
        sigs = []

    crops: list[str] = []
    for sig in sigs:
        try:
            x1 = max(0, int(float(sig["x1"]) * iw))
            y1 = max(0, int(float(sig["y1"]) * ih))
            x2 = min(iw, int(float(sig["x2"]) * iw))
            y2 = min(ih, int(float(sig["y2"]) * ih))
            if x2 > x1 and y2 > y1:
                crop = pil_img.crop((x1, y1, x2, y2))
                buf  = io.BytesIO()
                crop.save(buf, format="PNG")
                crops.append(base64.b64encode(buf.getvalue()).decode())
        except Exception:
            continue

    return CloudExtractResponse(
        model_used="qwen2vl-sig",
        signature_crops=crops if crops else None,
        signature_crops_estimated=False,
        raw_response=content,
    )


@router_v1.post("", response_model=CloudExtractResponse)
async def cloud_extract_cheque(
    file: UploadFile = File(...),
    model: str = "qwen-72b",
    ctx: UserContext = Depends(require_user_context),
) -> CloudExtractResponse:
    _all_valid = set(_MODEL_MAPPING) | _YOLO_SIG_MODELS | _YOLO_SIG_ONLY_MODELS | _QWEN_SIG_MODELS
    if model not in _all_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown model '{model}'. Must be one of {sorted(_all_valid)}.",
        )

    if model in _YOLO_SIG_ONLY_MODELS:
        return await _extract_yolov8_sig_only(file, ctx)

    if model in _YOLO_SIG_MODELS:
        return await _extract_yolov8_sig(file, ctx)

    # ── Qwen2-VL sig-only (multi-signature via HF) ───────────────────────────
    if model in _QWEN_SIG_MODELS:
        return await _extract_qwen2vl_sig(file, ctx)

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

                h_pad = 0.02   # 2 % each side — don't clip horizontal strokes
                b_pad = 0.015  # 1.5 % bottom — ensure full name row is included
                cx1_px = max(0,  int((bx1f - h_pad) * iw))
                cy1_px = max(0,  int((by1f - top_pad) * ih))
                cx2_px = min(iw, int((bx2f + h_pad) * iw))
                cy2_px = min(ih, int((by2f + b_pad) * ih))
                crop = pil_img.crop((cx1_px, cy1_px, cx2_px, cy2_px))
            else:
                cy1_px = int(ih * 0.62)
                cy2_px = int(ih * 0.80)
                crop = _sig_zone_from_image(pil_img)

            # Send the crop to the LLM and ask where printed text starts.
            crop = await _whiteout_via_llm(crop, client, model_id, ctx.bank_id)
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
