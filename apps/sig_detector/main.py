"""
ASTRA Signature Detector — microservice.

Two modes (selected automatically):
  1. YOLOv8 (optional): set SIG_DETECTOR_LOCAL_PATH to a local .pt file.
     Download the weights from HuggingFace manually and point here.
  2. Pixel-analysis (default, zero dependencies): uses PIL + numpy to find
     the signature region via ink-row profiling and gap detection.
     Works immediately with no model download.

The pixel-analysis mode finds the signature by:
  - Cropping to the standard CTS-2010 signature zone (lower-right)
  - Building a per-row ink-density profile
  - Finding the largest blank gap in that profile (gap = boundary between
    cursive sig strokes above and printed "ANKIT KUMAR" text below)
  - Returning the tight bbox of ink above that gap

Port: 8020 (local dev). In K8s: astra-sig-detector in astra-cts-{bank_id}.
"""
from __future__ import annotations

import base64
import io
import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env.local", override=False)
except ImportError:
    pass

if not os.environ.get("HF_TOKEN") and os.environ.get("ASTRA_DEMO_HF_TOKEN"):
    os.environ["HF_TOKEN"] = os.environ["ASTRA_DEMO_HF_TOKEN"]

import numpy as np
import structlog
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

app = FastAPI(
    title="ASTRA Signature Detector",
    docs_url="/docs" if os.environ.get("ENV", "production") == "development" else None,
    redoc_url=None,
)

_yolo_model = None
_mode: str = "pixel"
_vision_url: str = ""           # vLLM endpoint for Qwen2-VL mode
_immudb_client = None           # shared.audit.ImmudbClient, set at startup if IMMUDB_HOST set


@app.on_event("startup")
async def _startup() -> None:
    global _yolo_model, _mode, _vision_url, _immudb_client

    vision_url = os.environ.get("SIG_DETECTOR_VISION_URL", "").strip()
    if vision_url:
        _vision_url = vision_url
        _mode = "qwen2vl"
        log.info("sig_detector.ready", mode="qwen2vl", url=vision_url)
    else:
        local_path = os.environ.get("SIG_DETECTOR_LOCAL_PATH", "").strip()
        if local_path:
            try:
                from ultralytics import YOLO
                _yolo_model = YOLO(local_path)
                _mode = "yolov8"
                log.info("sig_detector.ready", mode="yolov8", model=local_path)
            except Exception as exc:
                log.warning("sig_detector.yolo_load_failed", path=local_path, error=str(exc))
                log.info("sig_detector.ready", mode="pixel")
        else:
            log.info("sig_detector.ready", mode="pixel")

    # ImmuDB — optional; /inspect still runs without it, immudb_tx_id stays null
    immudb_host = os.environ.get("IMMUDB_HOST", "").strip()
    if immudb_host:
        try:
            import sys, pathlib
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
            from shared.audit.immudb_client import ImmudbClient as _SDK
            _immudb_client = _SDK()
            _immudb_client.connect(
                host=immudb_host,
                port=int(os.environ.get("IMMUDB_PORT", "3322")),
                bank_id=os.environ.get("IMMUDB_BANK_ID", "demo"),
                collection="cts_events",
                username=os.environ.get("IMMUDB_USER", "immudb"),
                password=os.environ.get("IMMUDB_PASS", ""),
            )
            log.info("sig_detector.immudb.connected", host=immudb_host)
        except Exception as exc:
            log.warning("sig_detector.immudb.unavailable", error=str(exc))
            _immudb_client = None


# ── Pixel-based detector ──────────────────────────────────────────────────────

def _ink_threshold(arr: np.ndarray) -> int:
    """
    3rd-percentile intensity + 45, clamped to [60, 185].

    p3 anchors to the darkest 3% of zone pixels (actual ink strokes).
    Adding 45 lifts the threshold to catch light blue pen ink (gray 150-175).
    The upper clamp of 185 prevents a nearly-blank zone from classifying
    most of the background as ink.

    Natural Canara Bank protection: dense diagonal security print drives p3
    down to ~50-80 → threshold = 95-125 → security print (gray 120-150)
    falls ABOVE the threshold and is excluded automatically.
    Axis Bank (mostly white zone): p3 ≈ 140 → threshold = 185 → blue ink
    (gray 150-175) is included.
    """
    p3 = int(np.percentile(arr.flatten(), 3))
    return max(60, min(185, p3 + 45))


def _smooth_profile(profile: np.ndarray, window: int = 5) -> np.ndarray:
    kernel = np.ones(window) / window
    return np.convolve(profile, kernel, mode="same")


def _trim_left(rows: list[tuple], zw: int) -> int:
    """
    Robust left boundary for the signature cluster.

    Background noise (border lines, scattered watermark text) creates rows
    with very small left_x values that pull min(left_x) to the zone edge.
    We look for the largest gap in the sorted left_x distribution:
    if it exceeds 15 % of the zone width we treat everything LEFT of that
    gap as noise and start the bbox from the right side of the gap.
    """
    lefts = sorted(r[1] for r in rows)
    if len(lefts) < 4:
        return lefts[0]
    gap_thresh = int(zw * 0.15)
    max_gap = gap_idx = 0
    for i in range(len(lefts) - 1):
        g = lefts[i + 1] - lefts[i]
        if g > max_gap:
            max_gap, gap_idx = g, i + 1
    return lefts[gap_idx] if max_gap > gap_thresh else lefts[0]


def _trim_right(rows: list[tuple], zw: int) -> int:
    """
    Robust right boundary for the signature cluster.

    Barcode stripes (e.g. Axis Bank 1D barcode at zone right edge) create rows
    with right_x ≈ zone_width that pull max(right_x) to the zone boundary.
    We look for the largest gap in the sorted right_x distribution:
    if it exceeds 15 % of the zone width AND falls in the right half of the
    distribution, everything to the RIGHT of that gap is noise.
    """
    rights = sorted(r[2] for r in rows)
    if len(rights) < 4:
        return rights[-1]
    gap_thresh = int(zw * 0.15)
    max_gap = max_gap_idx = 0
    for i in range(len(rights) - 1):
        g = rights[i + 1] - rights[i]
        if g > max_gap:
            max_gap, max_gap_idx = g, i + 1
    if max_gap > gap_thresh and max_gap_idx > len(rights) // 2:
        return rights[max_gap_idx - 1]
    return rights[-1]


# ── Instrument Passport models ────────────────────────────────────────────────

class CheckStatus(str, Enum):
    PASS          = "PASS"
    FAIL          = "FAIL"
    DETECTED      = "DETECTED"
    NOT_DETECTED  = "NOT_DETECTED"
    INCONCLUSIVE  = "INCONCLUSIVE"
    SKIPPED       = "SKIPPED"


class GuardResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    guard: str
    rows_rejected: int
    description: str


class PixelAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)
    ink_mask_mode: str                      # "absolute" | "local-contrast"
    abs_ink_density: float                  # fraction of zone classified as ink in abs mode
    total_rows_with_ink: int
    qualifying_rows: int
    guard_results: list[GuardResult]        # one entry per guard A-E
    clusters_found: int
    head_trim_applied: bool
    head_trim_reason: Optional[str] = None
    signature_detected: bool
    bbox: Optional[list[float]] = None     # normalised [x1,y1,x2,y2]
    confidence: float = 0.0


class VisionCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    status: CheckStatus
    confidence: float = 0.0
    affected_fields: list[str] = []
    detail: Optional[str] = None


class VisionAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())
    checks: list[VisionCheck]
    overall_tamper_risk: float = 0.0
    physical_anomaly_score: float = 0.0
    model_used: str = ""
    degraded: bool = False


class SummaryCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    check: str
    status: CheckStatus
    confidence: float = 0.0
    detail: Optional[str] = None


class InstrumentPassport(BaseModel):
    model_config = ConfigDict(frozen=True)
    passport_id: str
    instrument_id: str
    bank_id: str
    timestamp: str
    pixel_analysis: PixelAnalysis
    vision_analysis: Optional[VisionAnalysis] = None
    summary: list[SummaryCheck]
    overall_status: str                    # "CLEAN" | "SUSPECT" | "REVIEW_REQUIRED"
    immudb_tx_id: Optional[int] = None
    immudb_key: Optional[str] = None


# ── Detailed pixel analysis (returns stats alongside detections) ──────────────

def _detect_pixel_detailed(img: Image.Image) -> tuple[list[dict], PixelAnalysis]:
    """
    Identical logic to _detect_pixel but also returns per-guard rejection counts
    and full analysis metadata for the Instrument Passport.
    """
    from PIL import ImageFilter

    iw, ih = img.size
    zy1 = int(ih * 0.55); zy2 = int(ih * 0.90)
    zx1 = int(iw * 0.52); zx2 = iw
    zone = img.crop((zx1, zy1, zx2, zy2))
    zw, zh = zone.size

    gray_raw = np.array(zone.convert("L"))
    abs_thr  = _ink_threshold(gray_raw)
    ink_abs  = (gray_raw < abs_thr).astype(np.uint8)
    abs_ink_density = float(ink_abs.mean())
    _use_local_contrast = abs_ink_density > 0.05
    if _use_local_contrast:
        blurred = np.array(zone.convert("L").filter(ImageFilter.GaussianBlur(radius=15)))
        ink = ((blurred.astype(int) - gray_raw.astype(int)) > 35).astype(np.uint8)
        ink_mask_mode = "local-contrast"
    else:
        ink = ink_abs
        ink_mask_mode = "absolute"

    total_rows_with_ink = int((ink.sum(axis=1) > 0).sum())

    MIN_SPAN         = max(8, int(zw * 0.05))
    MAX_DENSITY      = 0.40
    MAX_RUNS         = 15
    MERGE_GAP        = 10
    MIN_ROWS         = 2
    MIN_SPAN_DENSITY = 0.05 if _use_local_contrast else 0.08
    RIGHT_FRINGE     = max(4, int(zw * 0.08))

    reject_a = reject_b = reject_c = reject_d = reject_e = 0
    sig_rows: list[tuple] = []

    for y in range(zh):
        o_xs = np.where(ink[y])[0]
        if len(o_xs) == 0:
            continue
        span = int(o_xs[-1]) - int(o_xs[0])
        if span < MIN_SPAN:
            reject_a += 1; continue
        density = len(o_xs) / zw
        if density > MAX_DENSITY:
            reject_b += 1; continue
        runs = 1
        for i in range(1, len(o_xs)):
            if int(o_xs[i]) - int(o_xs[i - 1]) > 3: runs += 1
        if runs > MAX_RUNS:
            reject_c += 1; continue
        span_density = len(o_xs) / (span + 1)
        if span_density < MIN_SPAN_DENSITY:
            reject_d += 1; continue
        fringe_boundary = zw - RIGHT_FRINGE
        o_xs_core = o_xs[o_xs < fringe_boundary]
        if len(o_xs_core) == 0:
            reject_e += 1; continue
        sig_rows.append((y, int(o_xs[0]), int(o_xs_core[-1]), span_density))

    guard_results = [
        GuardResult(guard="A", rows_rejected=reject_a,
                    description=f"span < {MIN_SPAN}px — isolated dots/specks"),
        GuardResult(guard="B", rows_rejected=reject_b,
                    description="density > 40% — solid horizontal rule lines"),
        GuardResult(guard="C", rows_rejected=reject_c,
                    description="runs > 15 — security-print diagonal patterns"),
        GuardResult(guard="D", rows_rejected=reject_d,
                    description=f"span-density < {MIN_SPAN_DENSITY:.0%} — sparse rubber-stamp rows"),
        GuardResult(guard="E", rows_rejected=reject_e,
                    description="right-fringe only — barcode stripe rows"),
    ]

    def _make_analysis(sig_det: bool, bbox: Optional[list[float]],
                       clusters: int, head_trim: bool,
                       trim_reason: Optional[str]) -> PixelAnalysis:
        return PixelAnalysis(
            ink_mask_mode=ink_mask_mode,
            abs_ink_density=round(abs_ink_density, 4),
            total_rows_with_ink=total_rows_with_ink,
            qualifying_rows=len(sig_rows),
            guard_results=guard_results,
            clusters_found=clusters,
            head_trim_applied=head_trim,
            head_trim_reason=trim_reason,
            signature_detected=sig_det,
            bbox=bbox,
            confidence=0.80 if sig_det else 0.0,
        )

    if not sig_rows:
        return [], _make_analysis(False, None, 0, False, None)

    clusters: list[list[tuple]] = []
    cur: list[tuple] = [sig_rows[0]]
    for i in range(1, len(sig_rows)):
        if sig_rows[i][0] - sig_rows[i - 1][0] <= MERGE_GAP:
            cur.append(sig_rows[i])
        else:
            clusters.append(cur); cur = [sig_rows[i]]
    clusters.append(cur)

    qualifying = [c for c in clusters if len(c) >= MIN_ROWS]
    if not qualifying:
        qualifying = [max(clusters, key=len)]
    best = max(qualifying, key=len)

    TIGHT_GAP = 1
    head_trim_applied = False
    head_trim_reason: Optional[str] = None
    if len(best) > 10:
        sub_clusters: list[list[tuple]] = []
        sub_cur: list[tuple] = [best[0]]
        for i in range(1, len(best)):
            if best[i][0] - best[i - 1][0] <= TIGHT_GAP:
                sub_cur.append(best[i])
            else:
                sub_clusters.append(sub_cur); sub_cur = [best[i]]
        sub_clusters.append(sub_cur)
        if len(sub_clusters) >= 2:
            head = sub_clusters[0]
            tail_rows = sum(len(s) for s in sub_clusters[1:])
            if tail_rows > 0:
                gap = sub_clusters[1][0][0] - head[-1][0]
                ratio = len(head) / tail_rows
                head_avg_sd = sum(r[3] for r in head) / len(head)
                first_tail_len = len(sub_clusters[1])
                if (gap <= 3 and len(head) >= 10
                        and ratio < 0.25 and head_avg_sd > 0.28
                        and first_tail_len > len(head) * 1.5):
                    best = [r for s in sub_clusters[1:] for r in s]
                    head_trim_applied = True
                    head_trim_reason = (
                        f"small-gap annotation stripped: head={len(head)} rows, "
                        f"ratio={ratio:.1%}, avg_sd={head_avg_sd:.2f}, gap={gap}px"
                    )
                elif gap > 3 and len(head) < 5:
                    best = [r for s in sub_clusters[1:] for r in s]
                    head_trim_applied = True
                    head_trim_reason = (
                        f"large-gap orphan fragment dropped: head={len(head)} rows, gap={gap}px"
                    )

    left   = _trim_left(best, zw)
    right  = _trim_right(best, zw)
    top    = min(r[0] for r in best)
    bottom = max(r[0] for r in best) + 1

    if bottom - top < 2 or right - left < 8:
        return [], _make_analysis(False, None, len(clusters), head_trim_applied, head_trim_reason)

    abs_x1 = (zx1 + left)   / iw
    abs_y1 = (zy1 + top)    / ih
    abs_x2 = (zx1 + right)  / iw
    abs_y2 = (zy1 + bottom) / ih
    bbox   = [round(abs_x1,4), round(abs_y1,4), round(abs_x2,4), round(abs_y2,4)]

    return (
        [{"bbox": bbox, "confidence": 0.80}],
        _make_analysis(True, bbox, len(clusters), head_trim_applied, head_trim_reason),
    )


def _detect_pixel(img: Image.Image) -> list[dict]:
    """
    Find the signature region using per-row cluster analysis.

    Previous gap-detection approach failed whenever the largest blank gap in
    the zone was ABOVE the signature (e.g. the empty area between the account
    number box and the sig area) rather than below it — causing oversized bboxes
    and false "No-Sign-Present" results.

    New strategy:
      1. Build a tight ink mask (threshold capped at 110) that excludes
         security-print patterns (Canara Bank diagonal CANARA BANK text,
         which is typically gray > 110).
      2. For each row in the zone check TWO guards:
           Guard A — eroded span ≥ 18 % of zone width  (filters isolated dots)
           Guard B — original run count ≤ 6             (cursive: 1–5 runs/row;
                                                          printed block caps: 8–18)
      3. Cluster qualifying rows (merge gaps ≤ 4 rows).
      4. Pick the BOTTOMMOST qualifying cluster — signatures are always the
         lowest ink element on a CTS-2010 cheque.
      5. Return the tight pixel bbox of that cluster.
    """
    detections, _ = _detect_pixel_detailed(img)
    return detections


# ── Post-detection refinement ─────────────────────────────────────────────────

def _refine_with_pixel(img: Image.Image, bbox: list[float]) -> list[float] | None:
    """
    Tighten a coarse bounding box by running pixel gap-detection INSIDE
    the detected region.  Removes the printed-name rows at the bottom.

    Returns a tightened [x1, y1, x2, y2] (normalised) or None to discard
    the detection if it contains no real signature ink after refinement.
    """
    from PIL import ImageFilter

    iw, ih = img.size
    x1, y1, x2, y2 = bbox
    px1, py1 = int(x1 * iw), int(y1 * ih)
    px2, py2 = int(x2 * iw), int(y2 * ih)

    if px2 - px1 < 10 or py2 - py1 < 5:
        return None

    crop = img.crop((px1, py1, px2, py2))
    cw, ch = crop.size

    gray = np.array(crop.convert("L").filter(ImageFilter.MedianFilter(size=3)))
    thr  = _ink_threshold(gray)
    ink  = (gray < thr).astype(np.uint8)

    raw_density = ink.sum(axis=1) / cw
    row_density = _smooth_profile(raw_density, window=5)
    ink_rows    = row_density > 0.01

    # Find the largest gap of ≥ 3 blank rows — signature / text boundary
    best_gap_start = best_gap_len = 0
    cur_start = cur_len = 0
    in_gap = False
    for y, has_ink in enumerate(ink_rows):
        if not has_ink:
            if not in_gap:
                cur_start, cur_len, in_gap = y, 0, True
            cur_len += 1
            if cur_len > best_gap_len:
                best_gap_len, best_gap_start = cur_len, cur_start
        else:
            in_gap = False

    if best_gap_len >= 3 and ink_rows[:best_gap_start].sum() >= 6:
        sig_bottom = best_gap_start
    else:
        sig_bottom = ch   # no clean gap — keep full crop

    ink_region = ink[:sig_bottom, :]
    ink_coords = np.argwhere(ink_region)
    if ink_coords.size == 0:
        return None

    top    = int(ink_coords[:, 0].min())
    bottom = int(ink_coords[:, 0].max()) + 1
    left   = int(ink_coords[:, 1].min())
    right  = int(ink_coords[:, 1].max()) + 1

    if bottom - top < 5 or right - left < 8:
        return None

    return [
        round((px1 + left)   / iw, 4),
        round((py1 + top)    / ih, 4),
        round((px1 + right)  / iw, 4),
        round((py1 + bottom) / ih, 4),
    ]


# ── YOLOv8 detector ───────────────────────────────────────────────────────────

def _detect_yolo(img: Image.Image) -> list[dict]:
    conf_thr = float(os.environ.get("SIG_DETECTOR_CONF", "0.25"))
    iou_thr  = float(os.environ.get("SIG_DETECTOR_IOU",  "0.45"))
    results  = _yolo_model.predict(img, conf=conf_thr, iou=iou_thr, verbose=False)
    detections = []
    for r in results:
        if r.boxes is None:
            continue
        for box, conf in zip(r.boxes.xyxyn.tolist(), r.boxes.conf.tolist()):
            x1, y1, x2, y2 = box
            # Refine the coarse COCO bbox using pixel gap-detection inside
            # the region — removes printed-name rows that bleed into the crop.
            refined = _refine_with_pixel(img, [x1, y1, x2, y2])
            if refined is None:
                continue
            detections.append({"bbox": refined,
                                "confidence": round(float(conf), 4)})
    detections.sort(key=lambda d: d["confidence"], reverse=True)
    return detections


# ── Qwen2-VL vision detector ─────────────────────────────────────────────────

def _detect_qwen2vl(img: Image.Image) -> list[dict]:
    """
    Use Qwen2-VL (via vLLM) to locate all handwritten signatures in a cheque.
    Returns normalised [x1,y1,x2,y2] bboxes for every signature found.
    Falls back to [] on any error (pixel mode used as fallback at call site).

    Env: SIG_DETECTOR_VISION_URL   — vLLM base URL (e.g. http://vllm-cts:8000)
         SIG_DETECTOR_VISION_MODEL — model name (default: Qwen/Qwen2-VL-72B-Instruct)
    """
    import httpx

    iw, ih = img.size
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode()

    model = os.environ.get("SIG_DETECTOR_VISION_MODEL", "Qwen/Qwen2-VL-72B-Instruct")
    prompt = (
        "You are a cheque processing system. "
        "Identify every handwritten signature in this cheque image. "
        "Ignore pre-printed text, stamps, bank names, amounts, and annotations. "
        "For each signature found, output its bounding box as normalised coordinates "
        "(values 0.0–1.0, origin top-left). "
        'Respond with ONLY valid JSON: {"signatures": [{"x1":f,"y1":f,"x2":f,"y2":f,"confidence":f}, ...]}'
        " — no other text."
    )

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": 512,
        "temperature": 0.0,
        "extra_body": {"queue": "cts-vision"},
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(f"{_vision_url}/v1/chat/completions", json=payload)
            r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        # strip markdown fences if model wraps in ```json ... ```
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = json.loads(content)
        detections = []
        for sig in parsed.get("signatures", []):
            x1, y1 = max(0.0, float(sig["x1"])), max(0.0, float(sig["y1"]))
            x2, y2 = min(1.0, float(sig["x2"])), min(1.0, float(sig["y2"]))
            if x2 > x1 and y2 > y1:
                detections.append({
                    "bbox": [round(x1,4), round(y1,4), round(x2,4), round(y2,4)],
                    "confidence": round(float(sig.get("confidence", 0.90)), 4),
                })
        log.info("sig_detector.qwen2vl.done", count=len(detections))
        return detections
    except Exception as exc:
        log.warning("sig_detector.qwen2vl.error", error=str(exc))
        return []


# ── Qwen2-VL comprehensive integrity check ───────────────────────────────────

_INTEGRITY_PROMPT = """
You are a forensic cheque examiner. Inspect this cheque image for integrity issues.

Analyze FOUR areas:

1. WHITE_INK_CANCELLATION
   Bright-white patch with unnaturally sharp edges (correction fluid / whitener) over
   the signature zone, amount field, payee name, or date. Luminance spike well above
   surrounding paper + crisp edge boundary = correction fluid.

2. SIGNATURE_CANCELLATION
   Pen strokes crossing through the signature area in a visually distinct ink or colour —
   diagonal lines, horizontal strikes, or a CANCELLED / VOID rubber stamp over the
   signature zone.

3. FIELD_ALTERATION
   Overwriting or erasure on any of: amount_figures, amount_words, date, payee_name.
   Evidence: ink layer on ink layer, paper-fibre distortion, chemical halo/ring,
   colour temperature shift around the altered region.

4. SIGNATURE_PRESENCE
   Handwritten signature in the lower-right zone (roughly y=55%-90%, x=52%-100%).
   Count signatures (0 = absent, 1 = single, 2 = joint account).
   Quality: clear | partial | smudged | absent.

Respond in EXACTLY this JSON — no prose, no markdown fences:
{
  "white_ink_cancellation": {
    "detected": true,
    "confidence": 0.00,
    "location": "signature_zone|amount_field|payee_field|date_field|null",
    "detail": "string or null"
  },
  "signature_cancellation": {
    "detected": false,
    "confidence": 0.00,
    "method": "cross_through|stamp|null",
    "detail": "string or null"
  },
  "field_alteration": {
    "detected": false,
    "confidence": 0.00,
    "affected_fields": [],
    "alteration_type": "overwriting|erasure|chemical|correction_fluid|null"
  },
  "signature_presence": {
    "count": 1,
    "confidence": 0.00,
    "quality": "clear|partial|smudged|absent"
  },
  "overall_tamper_risk": 0.00,
  "physical_anomaly_score": 0.00
}
"""


def _inspect_qwen2vl(img: Image.Image) -> Optional[VisionAnalysis]:
    """
    Comprehensive cheque integrity check via Qwen2-VL.

    Covers what pixel detection cannot see:
      - White ink / correction fluid (lighter than background — invisible to ink mask)
      - Signature cancellation (different-color cross-through or CANCELLED stamp)
      - Field alteration (overwriting, chemical erasure, paper-fibre distortion)
      - Signature presence and quality

    Returns None if vLLM is not configured (IMMUDB_HOST or SIG_DETECTOR_VISION_URL unset).
    Returns VisionAnalysis with degraded=True on any vLLM error (never raises).
    """
    if not _vision_url:
        return None

    import httpx

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode()

    model = os.environ.get("SIG_DETECTOR_VISION_MODEL", "Qwen/Qwen2-VL-72B-Instruct")
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": _INTEGRITY_PROMPT},
            ],
        }],
        "max_tokens": 1024,
        "temperature": 0.0,
        "extra_body": {"queue": "cts-vision"},
    }

    try:
        with httpx.Client(timeout=90.0) as client:
            r = client.post(f"{_vision_url}/v1/chat/completions", json=payload)
            r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content)
    except Exception as exc:
        log.warning("sig_detector.inspect.vision_error", error=str(exc))
        return VisionAnalysis(checks=[], model_used=model, degraded=True)

    checks: list[VisionCheck] = []

    wic = data.get("white_ink_cancellation", {})
    checks.append(VisionCheck(
        name="white_ink_cancellation",
        status=CheckStatus.DETECTED if wic.get("detected") else CheckStatus.NOT_DETECTED,
        confidence=round(float(wic.get("confidence", 0.0)), 3),
        detail=wic.get("detail") or (f"location: {wic['location']}" if wic.get("location") else None),
    ))

    sc = data.get("signature_cancellation", {})
    checks.append(VisionCheck(
        name="signature_cancellation",
        status=CheckStatus.DETECTED if sc.get("detected") else CheckStatus.NOT_DETECTED,
        confidence=round(float(sc.get("confidence", 0.0)), 3),
        detail=sc.get("detail") or sc.get("method"),
    ))

    fa = data.get("field_alteration", {})
    checks.append(VisionCheck(
        name="field_alteration",
        status=CheckStatus.DETECTED if fa.get("detected") else CheckStatus.NOT_DETECTED,
        confidence=round(float(fa.get("confidence", 0.0)), 3),
        affected_fields=fa.get("affected_fields", []),
        detail=fa.get("alteration_type"),
    ))

    sp = data.get("signature_presence", {})
    count = int(sp.get("count", 0))
    checks.append(VisionCheck(
        name="signature_presence",
        status=CheckStatus.DETECTED if count > 0 else CheckStatus.NOT_DETECTED,
        confidence=round(float(sp.get("confidence", 0.0)), 3),
        detail=f"count={count}, quality={sp.get('quality', 'unknown')}",
    ))

    log.info("sig_detector.inspect.vision_done",
             tamper_risk=data.get("overall_tamper_risk", 0),
             checks={c.name: c.status for c in checks})

    return VisionAnalysis(
        checks=checks,
        overall_tamper_risk=round(float(data.get("overall_tamper_risk", 0.0)), 3),
        physical_anomaly_score=round(float(data.get("physical_anomaly_score", 0.0)), 3),
        model_used=model,
        degraded=False,
    )


# ── API ───────────────────────────────────────────────────────────────────────

class Detection(BaseModel):
    bbox: list[float]
    confidence: float


class DetectResponse(BaseModel):
    detections: list[Detection]
    mode: str           # "qwen2vl" | "yolov8" | "pixel"
    image_size: list[int]


@app.post("/detect", response_model=DetectResponse)
async def detect_signatures(file: UploadFile = File(...)) -> DetectResponse:
    data = await file.read()
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc

    iw, ih = img.size
    if _mode == "qwen2vl":
        raw = _detect_qwen2vl(img) or _detect_pixel(img)   # pixel fallback on error
    elif _mode == "yolov8":
        raw = _detect_yolo(img)
    else:
        raw = _detect_pixel(img)
    detections = [Detection(bbox=d["bbox"], confidence=d["confidence"]) for d in raw]

    log.info("sig_detector.detected", count=len(detections), mode=_mode)
    return DetectResponse(detections=detections, mode=_mode, image_size=[iw, ih])


@app.post("/inspect", response_model=InstrumentPassport)
async def inspect_instrument(
    file: UploadFile = File(...),
    instrument_id: str = Form(default=""),
    bank_id: str = Form(default="demo"),
) -> InstrumentPassport:
    """
    Full per-instrument passport: pixel analysis (guards A-E, head-trim) +
    Qwen2-VL integrity check (white ink, cancellation, alteration, signature quality)
    + ImmuDB audit write.

    Every check result is explicit — DETECTED / NOT_DETECTED / SKIPPED — so the
    passport is a complete evidence record regardless of what was found.
    """
    raw_data = await file.read()
    try:
        img = Image.open(io.BytesIO(raw_data)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc

    passport_id = str(uuid.uuid4())
    if not instrument_id:
        instrument_id = f"INSP-{passport_id[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()

    # ── 1. Pixel analysis (always runs — zero dependencies) ───────────────
    _, pixel_analysis = _detect_pixel_detailed(img)

    # ── 2. Vision integrity check (only if vLLM is configured) ───────────
    vision_analysis: Optional[VisionAnalysis] = None
    if _vision_url:
        vision_analysis = _inspect_qwen2vl(img)

    # ── 3. Build consolidated summary ─────────────────────────────────────
    summary: list[SummaryCheck] = []

    # Pixel guard results
    for g in pixel_analysis.guard_results:
        summary.append(SummaryCheck(
            check=f"pixel_guard_{g.guard}",
            status=CheckStatus.PASS if g.rows_rejected == 0 else CheckStatus.FAIL,
            confidence=1.0,
            detail=f"{g.rows_rejected} rows rejected — {g.description}",
        ))

    summary.append(SummaryCheck(
        check="pixel_ink_mode",
        status=CheckStatus.PASS,
        confidence=1.0,
        detail=(f"mode={pixel_analysis.ink_mask_mode}, "
                f"abs_density={pixel_analysis.abs_ink_density:.3f}, "
                f"qualifying={pixel_analysis.qualifying_rows}/{pixel_analysis.total_rows_with_ink} rows"),
    ))

    summary.append(SummaryCheck(
        check="pixel_signature_detected",
        status=CheckStatus.DETECTED if pixel_analysis.signature_detected else CheckStatus.NOT_DETECTED,
        confidence=pixel_analysis.confidence,
        detail=str(pixel_analysis.bbox) if pixel_analysis.bbox else "no qualifying cluster",
    ))

    if pixel_analysis.head_trim_applied:
        summary.append(SummaryCheck(
            check="pixel_annotation_stripped",
            status=CheckStatus.DETECTED,
            confidence=1.0,
            detail=pixel_analysis.head_trim_reason,
        ))

    # Vision checks or SKIPPED markers
    if vision_analysis and not vision_analysis.degraded:
        for vc in vision_analysis.checks:
            summary.append(SummaryCheck(
                check=f"vision_{vc.name}",
                status=vc.status,
                confidence=vc.confidence,
                detail=vc.detail,
            ))
        summary.append(SummaryCheck(
            check="vision_tamper_risk",
            status=(CheckStatus.FAIL if vision_analysis.overall_tamper_risk > 0.4
                    else CheckStatus.PASS),
            confidence=vision_analysis.overall_tamper_risk,
            detail=(f"tamper_risk={vision_analysis.overall_tamper_risk:.3f}, "
                    f"physical_anomaly={vision_analysis.physical_anomaly_score:.3f}"),
        ))
    elif vision_analysis and vision_analysis.degraded:
        for name in ("white_ink_cancellation", "signature_cancellation",
                     "field_alteration", "signature_presence"):
            summary.append(SummaryCheck(
                check=f"vision_{name}",
                status=CheckStatus.INCONCLUSIVE,
                detail="vLLM returned error — result inconclusive",
            ))
    else:
        for name in ("white_ink_cancellation", "signature_cancellation",
                     "field_alteration", "signature_presence"):
            summary.append(SummaryCheck(
                check=f"vision_{name}",
                status=CheckStatus.SKIPPED,
                detail="SIG_DETECTOR_VISION_URL not configured",
            ))

    # ── 4. Overall status ─────────────────────────────────────────────────
    vision_alert = (
        vision_analysis is not None
        and not vision_analysis.degraded
        and (
            vision_analysis.overall_tamper_risk > 0.6
            or any(
                c.status == CheckStatus.DETECTED
                for c in vision_analysis.checks
                if c.name in ("white_ink_cancellation", "signature_cancellation", "field_alteration")
            )
        )
    )
    if vision_alert:
        overall_status = "REVIEW_REQUIRED"
    elif not pixel_analysis.signature_detected:
        overall_status = "SUSPECT"
    elif vision_analysis and not vision_analysis.degraded and vision_analysis.overall_tamper_risk > 0.25:
        overall_status = "SUSPECT"
    else:
        overall_status = "CLEAN"

    # ── 5. ImmuDB audit write ─────────────────────────────────────────────
    immudb_tx_id: Optional[int] = None
    immudb_key: Optional[str] = None
    if _immudb_client is not None:
        try:
            payload: dict = {
                "event_type": "CTS_INSTRUMENT_PASSPORT",
                "bank_id": bank_id,
                "event_id": passport_id,
                "instrument_id": instrument_id,
                "timestamp": timestamp,
                "overall_status": overall_status,
                "pixel": {
                    "ink_mask_mode": pixel_analysis.ink_mask_mode,
                    "abs_ink_density": pixel_analysis.abs_ink_density,
                    "qualifying_rows": pixel_analysis.qualifying_rows,
                    "signature_detected": pixel_analysis.signature_detected,
                    "bbox": pixel_analysis.bbox,
                    "head_trim_applied": pixel_analysis.head_trim_applied,
                    "head_trim_reason": pixel_analysis.head_trim_reason,
                    "guard_rejections": {g.guard: g.rows_rejected
                                         for g in pixel_analysis.guard_results},
                },
                "vision": (
                    {
                        "overall_tamper_risk": vision_analysis.overall_tamper_risk,
                        "physical_anomaly_score": vision_analysis.physical_anomaly_score,
                        "model_used": vision_analysis.model_used,
                        "degraded": vision_analysis.degraded,
                        "checks": {
                            c.name: {
                                "status": c.status.value,
                                "confidence": c.confidence,
                                "detail": c.detail,
                                "affected_fields": c.affected_fields,
                            }
                            for c in vision_analysis.checks
                        },
                    }
                    if vision_analysis else None
                ),
            }
            result = _immudb_client.write_event(payload)
            immudb_tx_id = result.get("tx_id")
            raw_key = result.get("key", "")
            immudb_key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            log.info("sig_detector.passport.written",
                     tx_id=immudb_tx_id, instrument_id=instrument_id,
                     bank_id=bank_id, status=overall_status)
        except Exception as exc:
            log.error("sig_detector.passport.immudb_failed",
                      instrument_id=instrument_id, error=str(exc))

    return InstrumentPassport(
        passport_id=passport_id,
        instrument_id=instrument_id,
        bank_id=bank_id,
        timestamp=timestamp,
        pixel_analysis=pixel_analysis,
        vision_analysis=vision_analysis,
        summary=summary,
        overall_status=overall_status,
        immudb_tx_id=immudb_tx_id,
        immudb_key=immudb_key,
    )


@app.get("/health/live", include_in_schema=False)
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    return JSONResponse({"status": "ready", "mode": _mode})


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8020, reload=False)
