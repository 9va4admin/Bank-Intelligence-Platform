"""
detect_signatures activity — Vision LLM detects ink signatures on a cheque image.

Used by both CTS pipelines with different downstream behaviour:

  Outward (presentee bank):
    PRESENT  → proceed to lot  (no vault lookup, no comparison)
    ABSENT   → CTS-2010 reject / SIGNATURE_ABSENT
    DEGRADED → proceed optimistically (don't block lot on AI failure)

  Inward (drawee bank):
    PRESENT, sig_count=1    → S-SVS (SignatureVault + Siamese compare)
    PRESENT, sig_count≥2   → M-SVS (per-signatory vault + mandate BRE)
    ABSENT                  → HUMAN_REVIEW / NO_SIGNATURE
    DEGRADED                → HUMAN_REVIEW (consistent with all AI degradation paths)
    fraud_flags non-empty   → HUMAN_REVIEW / SIGNATURE_FRAUD_SUSPECTED

Uses Qwen2-VL 7B on cts-vision-l1 queue (fast L1 — detection only;
72B forensic model reserved for full alteration analysis in alteration.py).

The activity is self-contained within modules/cts/ — no import from modules/msv/.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.detect_signatures")

_MODEL_NAME = "qwen2-vl-7b"
_QUEUE = "cts-vision-l1"
_TIMEOUT_SECONDS = 60

_DETECTION_PROMPT = """Examine this cheque image and locate all handwritten ink signatures.

Return JSON with exactly these fields:
{
  "signature_count": <integer — total distinct ink signatures found>,
  "signature_bboxes": [[x1, y1, x2, y2], ...],
  "signature_fraud_flags": [<string>, ...]
}

Rules:
- signature_count: count only genuine ink handwritten signatures, not printed text or stamps.
- signature_bboxes: one [x1, y1, x2, y2] per signature as decimal fractions of image size
  (0.0 = left/top, 1.0 = right/bottom). Empty array if count is 0.
- signature_fraud_flags: include any that apply —
    "OVERWRITTEN"   — ink written on top of existing ink or whiteout
    "SMUDGED"       — ink blur suggesting wet-ink tampering
    "MULTIPLE_INKS" — different ink colours across signature zones
    "FAINT_INK"     — stroke too light to be genuine (photocopied or printed)
    "MISALIGNED"    — signature placed outside the designated signature box
  Return [] if none detected.

Return ONLY valid JSON. No markdown, no explanation.
"""

# CTS-2010 signature block is a fixed, standardised zone (lower-right) --
# not something a vision model needs to search for across the whole
# cheque. Cropping to it deterministically first, then asking the model
# to count/classify ONLY within that small crop, is a strictly easier and
# more constrained task than open-ended whole-image detection: the model
# can no longer mistake handwriting elsewhere on the cheque (payee line,
# amount in words) for a signature, and the crop is small enough that
# printed captions ("For <Company>", "Authorised Signatory") are the only
# real source of confusion left to guard against explicitly.
_ZONE_DETECTION_PROMPT = """This image is a pre-cropped region from the lower-right
signature area of a bank cheque -- it has already been located, so do not look
for signatures anywhere else; only what is visible in this crop matters.

Count every distinct HANDWRITTEN CURSIVE INK signature in this crop.

Return JSON with exactly these fields:
{
  "signature_count": <integer>,
  "signature_bboxes": [[x1, y1, x2, y2], ...],
  "signature_fraud_flags": [<string>, ...]
}

Rules:
- Do NOT count any of the following as a signature, even if positioned where a
  signature would be expected:
    * Printed text, e.g. "For <Company Name>", "Authorised Signatory",
      "Please sign above", "Proprietor", "Partner", "Director", "Manager"
    * Bank stamps, seals, or rubber-stamp text
    * A printed account-holder name
  If the entire crop contains only printed text and no genuine ink strokes,
  return signature_count: 0 and an empty signature_bboxes array.
- signature_bboxes: [x1, y1, x2, y2] as decimal fractions of THIS CROPPED
  IMAGE (0.0-1.0) -- not the original full cheque.
- signature_fraud_flags: same categories as before (OVERWRITTEN, SMUDGED,
  MULTIPLE_INKS, FAINT_INK, MISALIGNED). Return [] if none apply.

Return ONLY valid JSON. No markdown, no explanation.
"""

# Must match modules/cts/preprocessing/zone_extractor.py's CTS_ZONES["signature"]
# -- kept as a local constant too since detect_signatures.py is documented as
# self-contained within modules/cts/ (no cross-import requirement, but same
# canonical coordinates).
_SIGNATURE_ZONE = (0.52, 0.55, 1.00, 0.90)


def _remap_bbox_to_full_image(bbox: list[float], zone: tuple[float, float, float, float]) -> list[float]:
    """Convert a bbox expressed as a fraction of the CROPPED zone image back
    into a fraction of the full original cheque image."""
    zx1, zy1, zx2, zy2 = zone
    bx1, by1, bx2, by2 = bbox
    zw, zh = zx2 - zx1, zy2 - zy1
    return [zx1 + bx1 * zw, zy1 + by1 * zh, zx1 + bx2 * zw, zy1 + by2 * zh]


def _refine_bbox_to_ink(zone_png: bytes, bbox: list[float]) -> list[float]:
    """Grow a vision-model bbox (fraction of the zone crop) to the full
    extent of the real connected ink component(s) it overlaps.

    Real, demonstrated gap found by manual review + systematic measurement
    across 19 real cheques (2026-09-18/19): the vision model correctly
    identifies WHICH ink is the signature (vs. printed captions), but its
    bbox coordinates are frequently undersized -- LLM visual grounding is
    not pixel-precise the way a trained detector is. 5 of 19 cheques had a
    bbox missing real ink by more than 25% of the bbox's own size on at
    least one side; 915526's bbox (54x26px) was smaller than the real
    signature by ~30px on every side. Coarse localisation from the vision
    model + deterministic boundary refinement from real pixel data is a
    standard combination -- use the model for WHERE, use connected-
    component analysis for the PRECISE extent once we're already looking
    at approximately the right place.

    Only grows the bbox (never shrinks below the model's own estimate) --
    if the model's box already fully contains the ink, or ink detection
    fails for any reason, returns the original bbox unchanged.
    """
    try:
        import io as _io
        import cv2
        import numpy as np
        from PIL import Image as _Image

        zone_img = _Image.open(_io.BytesIO(zone_png)).convert("L")
        zw, zh = zone_img.size
        bx1, by1, bx2, by2 = bbox
        px1, py1 = int(bx1 * zw), int(by1 * zh)
        px2, py2 = int(bx2 * zw), int(by2 * zh)

        gray = np.array(zone_img)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

        # A little tolerance around the model's box -- ink touching but not
        # strictly inside it (the exact failure mode found: the box sits
        # just short of the real stroke) should still count as the same
        # component.
        tol = 3
        tx1, ty1 = max(0, px1 - tol), max(0, py1 - tol)
        tx2, ty2 = min(zw, px2 + tol), min(zh, py2 + tol)
        overlap_labels = set(np.unique(labels[ty1:ty2, tx1:tx2]))
        overlap_labels.discard(0)
        if not overlap_labels:
            return bbox

        mask = np.isin(labels, list(overlap_labels))
        ys, xs = np.where(mask)
        # Union with the model's own box -- refinement only ever grows it.
        real_x1 = min(int(xs.min()), px1)
        real_y1 = min(int(ys.min()), py1)
        real_x2 = max(int(xs.max()) + 1, px2)
        real_y2 = max(int(ys.max()) + 1, py2)

        # Safety check found by direct visual review: when the model's own
        # box sits mostly on a printed caption rather than the real ink
        # (a worse failure than merely undersized -- 168376, 673677), the
        # "nearest overlapping component" is the caption's own text blob,
        # and growing to it produces a thin, wide strip -- a printed
        # single text line, not a genuine handwritten signature in this
        # dataset. Reject the growth in that case and fall back to the
        # model's original box rather than confidently expand onto the
        # wrong ink.
        rh, rw = real_y2 - real_y1, real_x2 - real_x1
        if rh < 20 and rw / max(rh, 1) > 5:
            return bbox

        return [real_x1 / zw, real_y1 / zh, real_x2 / zw, real_y2 / zh]
    except Exception:
        return bbox


async def _detect_via_hf_cloud(
    inp: DetectSignaturesInput,
    config_service: Any,
    zone_png: bytes,
) -> Optional["DetectSignaturesResult"]:
    """
    Real HF-cloud vision fallback (config-gated, off by default — see
    shared/ai/hf_cloud_fallback.py), tried before the pixel-analysis
    fallback when the on-prem vLLM cluster is unreachable. In real bank
    deployments this tier does not apply (CLAUDE.md: zero cloud
    dependencies) — a bank without on-prem GPU falls straight to
    _detect_via_sig_detector. This exists to validate the zone-crop +
    vision-model approach against real cheques while no GPU cluster is
    available in this dev environment; the eventual production
    replacement for this tier is the bank's own on-prem vLLM cluster,
    which vllm_client already serves above.
    """
    from shared.ai.hf_cloud_fallback import call_hf_vision, cloud_fallback_enabled

    if not await cloud_fallback_enabled(config_service, inp.bank_id):
        return None

    content = await call_hf_vision(config_service, zone_png, _ZONE_DETECTION_PROMPT)
    if content is None:
        return None

    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
    except Exception as exc:
        log.warning("detect_signatures.hf_cloud_invalid_json", instrument_id=inp.instrument_id, error=str(exc))
        return None

    sig_count = int(parsed.get("signature_count", 0))
    fraud_flags = list(parsed.get("signature_fraud_flags", []))
    sig_bboxes = [
        _remap_bbox_to_full_image(
            _refine_bbox_to_ink(zone_png, [float(v) for v in bbox]), _SIGNATURE_ZONE
        )
        for bbox in (parsed.get("signature_bboxes") or [])
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4
    ]

    log.info(
        "detect_signatures.hf_cloud_used",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        sig_count=sig_count,
    )

    return DetectSignaturesResult(
        outcome="PRESENT" if sig_count > 0 else "ABSENT",
        sig_count=sig_count,
        sig_bboxes=sig_bboxes,
        fraud_flags=fraud_flags,
        degraded=False,
    )


async def _crop_signature_zone(image_url: str) -> Optional[bytes]:
    """Fetch the full cheque image and crop to the deterministic CTS-2010
    signature zone. Returns PNG bytes, or None on any fetch/decode failure
    (caller falls back to whole-image detection unchanged)."""
    try:
        from io import BytesIO
        from PIL import Image
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        iw, ih = img.size
        x1f, y1f, x2f, y2f = _SIGNATURE_ZONE
        x1, y1 = max(0, int(x1f * iw)), max(0, int(y1f * ih))
        x2, y2 = min(iw, int(x2f * iw)), min(ih, int(y2f * ih))
        crop = img.crop((x1, y1, x2, y2))
        buf = BytesIO()
        crop.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:
        log.warning("detect_signatures.zone_crop_failed", error=str(exc))
        return None


class DetectSignaturesInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    image_url: str


async def _detect_via_sig_detector(
    inp: DetectSignaturesInput,
    config_service: Any,
) -> Optional["DetectSignaturesResult"]:
    """
    Real fallback via apps/sig_detector — a standalone service that never
    depends on vLLM (pixel-analysis mode works with zero model weights;
    YOLOv8 mode is used automatically if SIG_DETECTOR_LOCAL_PATH is set on
    that service). Used when the Qwen2-VL vision cascade is unreachable, so
    signature presence/bbox detection doesn't go fully blind just because
    the GPU cluster is down — matches how the real outward pipeline already
    treats signature *presence* as independently checkable from OCR.

    Returns None (never raises) if the service itself is unreachable —
    caller falls through to the existing DEGRADED outcome unchanged.
    """
    try:
        url = await config_service.get("services.sig_detector.url")
    except Exception:
        return None
    if not url:
        return None

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            img_resp = await client.get(inp.image_url)
            img_resp.raise_for_status()
            det_resp = await client.post(
                f"{url}/detect",
                files={"file": ("cheque.jpg", img_resp.content, "image/jpeg")},
            )
            det_resp.raise_for_status()
            data = det_resp.json()
    except Exception as exc:
        log.warning(
            "detect_signatures.sig_detector_unavailable",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return None

    detections = data.get("detections", [])

    # sig_detector's /detect always returns already-fractional [0,1] bboxes
    # (pixel mode divides by image dims before returning; YOLO mode uses
    # ultralytics' .xyxyn) — do not re-divide by image_size here.
    sig_bboxes = [
        [float(v) for v in d["bbox"]]
        for d in detections
        if isinstance(d.get("bbox"), list) and len(d["bbox"]) == 4
    ]
    sig_count = len(sig_bboxes)
    mode = data.get("mode", "pixel")

    log.info(
        "detect_signatures.sig_detector_used",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        sig_count=sig_count,
        mode=mode,
    )

    # Real, demonstrated failure rate found by manual review of actual KBL
    # cheques 2026-09-18: the pixel-analysis heuristic (the only mode that
    # runs without real trained weights) produced a false positive on a
    # blank/unsigned cheque, and a mislocated bbox that missed the real
    # signature entirely, on 2 of ~8 cheques spot-checked. Its sig_count/
    # sig_bboxes are still returned for visual reference (the digest crop),
    # but outcome/degraded must never claim this is a trustworthy PRESENT/
    # ABSENT signal — treat it exactly like any other AI-unavailable path
    # so downstream decision logic doesn't silently trust a wrong answer.
    # YOLOv8 mode (real trained weights) would not have this caveat if
    # SIG_DETECTOR_LOCAL_PATH is ever configured on that service.
    is_heuristic_only = mode == "pixel"

    return DetectSignaturesResult(
        outcome="DEGRADED" if is_heuristic_only else ("PRESENT" if sig_count > 0 else "ABSENT"),
        sig_count=sig_count,
        sig_bboxes=sig_bboxes,
        fraud_flags=[],   # pixel/yolo modes detect presence only, not ink-fraud patterns
        degraded=is_heuristic_only,
    )


class DetectSignaturesResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "PRESENT" | "ABSENT" | "DEGRADED"
    sig_count: int
    sig_bboxes: list[list[float]]       # fractional [x1,y1,x2,y2] per detected signature
    fraud_flags: list[str]
    degraded: bool = False


@activity.defn
async def detect_signatures(
    inp: DetectSignaturesInput,
    vllm_client=None,
    config_service: Any = None,
) -> DetectSignaturesResult:
    """
    Detect the number and fraud indicators of ink signatures on a cheque image.

    Returns DetectSignaturesResult in all cases — never raises.
    Callers own the routing decision based on outcome and sig_count.
    """
    with tracer.start_as_current_span("cts.detect_signatures") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        span.set_attribute("model", _MODEL_NAME)
        span.set_attribute("queue", _QUEUE)

        if vllm_client is None:
            log.warning(
                "detect_signatures.no_client",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            )
            if config_service is not None:
                zone_png = await _crop_signature_zone(inp.image_url)
                if zone_png is not None:
                    hf_result = await _detect_via_hf_cloud(inp, config_service, zone_png)
                    if hf_result is not None:
                        span.set_attribute("degraded", False)
                        span.set_attribute("fallback", "hf_cloud_zone_crop")
                        return hf_result
                fallback = await _detect_via_sig_detector(inp, config_service)
                if fallback is not None:
                    span.set_attribute("degraded", fallback.degraded)
                    span.set_attribute("fallback", "sig_detector")
                    return fallback
            span.set_attribute("degraded", True)
            return DetectSignaturesResult(
                outcome="DEGRADED", sig_count=0, sig_bboxes=[], fraud_flags=[], degraded=True
            )

        # Crop to the deterministic CTS-2010 signature zone first (see
        # _crop_signature_zone / _ZONE_DETECTION_PROMPT docstrings): a
        # strictly easier, more constrained task for the vision model than
        # searching the whole cheque. Falls back to whole-image detection
        # with the original prompt if the crop itself fails for any reason.
        zone_png = await _crop_signature_zone(inp.image_url)
        if zone_png is not None:
            import base64
            image_content = {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64.b64encode(zone_png).decode()}"},
            }
            prompt = _ZONE_DETECTION_PROMPT
        else:
            image_content = {"type": "image_url", "image_url": {"url": inp.image_url}}
            prompt = _DETECTION_PROMPT

        try:
            response = await vllm_client.chat.completions.create(
                model=_MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [
                        image_content,
                        {"type": "text", "text": prompt},
                    ],
                }],
                extra_body={"queue": _QUEUE},
                timeout=_TIMEOUT_SECONDS,
            )

            raw = response.choices[0].message.content
            parsed = json.loads(raw)

        except json.JSONDecodeError as exc:
            log.warning(
                "detect_signatures.invalid_json",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            span.set_attribute("degraded", True)
            return DetectSignaturesResult(
                outcome="DEGRADED", sig_count=0, sig_bboxes=[], fraud_flags=[], degraded=True
            )
        except Exception as exc:
            log.warning(
                "detect_signatures.vllm_unavailable",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            if config_service is not None:
                fallback = await _detect_via_sig_detector(inp, config_service)
                if fallback is not None:
                    span.set_attribute("degraded", fallback.degraded)
                    span.set_attribute("fallback", "sig_detector")
                    return fallback
            span.set_attribute("degraded", True)
            return DetectSignaturesResult(
                outcome="DEGRADED", sig_count=0, sig_bboxes=[], fraud_flags=[], degraded=True
            )

        sig_count = int(parsed.get("signature_count", 0))
        fraud_flags = list(parsed.get("signature_fraud_flags", []))
        # Validate and normalise bboxes — LLM occasionally returns malformed entries
        sig_bboxes = [
            [float(v) for v in bbox]
            for bbox in (parsed.get("signature_bboxes") or [])
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4
        ]
        if zone_png is not None:
            # Model saw only the cropped zone — bboxes are fractions of that
            # crop. Refine to the real ink extent (see _refine_bbox_to_ink)
            # before remapping back to full-cheque-image fractions.
            sig_bboxes = [
                _remap_bbox_to_full_image(_refine_bbox_to_ink(zone_png, b), _SIGNATURE_ZONE)
                for b in sig_bboxes
            ]
        outcome = "PRESENT" if sig_count > 0 else "ABSENT"

        span.set_attribute("sig_count", sig_count)
        span.set_attribute("bbox_count", len(sig_bboxes))
        span.set_attribute("fraud_flag_count", len(fraud_flags))

        log.info(
            "detect_signatures.complete",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            sig_count=sig_count,
            bbox_count=len(sig_bboxes),
            outcome=outcome,
            fraud_flags=fraud_flags,
        )

        return DetectSignaturesResult(
            outcome=outcome,
            sig_count=sig_count,
            sig_bboxes=sig_bboxes,
            fraud_flags=fraud_flags,
            degraded=False,
        )
