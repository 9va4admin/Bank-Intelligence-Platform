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

import io
import os
from pathlib import Path

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
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

log = structlog.get_logger()

app = FastAPI(
    title="ASTRA Signature Detector",
    docs_url="/docs" if os.environ.get("ENV", "production") == "development" else None,
    redoc_url=None,
)

_yolo_model = None
_mode: str = "pixel"
_vision_url: str = ""   # vLLM endpoint for Qwen2-VL mode


@app.on_event("startup")
async def _startup() -> None:
    global _yolo_model, _mode, _vision_url
    vision_url = os.environ.get("SIG_DETECTOR_VISION_URL", "").strip()
    if vision_url:
        _vision_url = vision_url
        _mode = "qwen2vl"
        log.info("sig_detector.ready", mode="qwen2vl", url=vision_url)
        return
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
    from PIL import ImageFilter

    iw, ih = img.size

    # ── 1. Crop to the CTS-2010 signature zone ───────────────────────────
    zy1 = int(ih * 0.55)
    zy2 = int(ih * 0.90)
    zx1 = int(iw * 0.52)
    zx2 = iw
    zone = img.crop((zx1, zy1, zx2, zy2))
    zw, zh = zone.size

    # ── 2. Build ink mask ─────────────────────────────────────────────────
    gray_img = zone.convert("L").filter(ImageFilter.MedianFilter(size=3))
    gray     = np.array(gray_img)
    thr      = _ink_threshold(gray)
    ink      = (gray < thr).astype(np.uint8)

    # ── 3. Collect qualifying rows ─────────────────────────────────────────
    # Guard A — span ≥ 5 % of zone width (was 10 % — too wide for compact sigs)
    # Guard B — density < 40 %: rejects solid horizontal rule lines
    # Guard C — runs ≤ 15: at high resolution (2365 px wide) disconnected
    #           cursive strokes produce up to 12 runs/row; security print
    #           (Canara Bank diagonal) produces 20+ runs/row
    MIN_SPAN    = max(8, int(zw * 0.05))   # 5 % of zone width
    MAX_DENSITY = 0.40                      # solid fill / rule line
    MAX_RUNS    = 15                        # cursive at high-res: ≤ 12; Canara: 20+
    MERGE_GAP   = 15                        # rows ≤ 15 apart → same cluster
    MIN_ROWS    = 2                         # cluster needs ≥ 2 qualifying rows

    sig_rows: list[tuple[int, int, int]] = []   # (y, left_x, right_x)

    for y in range(zh):
        o_xs = np.where(ink[y])[0]
        if len(o_xs) == 0:
            continue

        # Guard A: horizontal span
        span = int(o_xs[-1]) - int(o_xs[0])
        if span < MIN_SPAN:
            continue

        # Guard B: density — reject solid fill / horizontal rule lines
        density = len(o_xs) / zw
        if density > MAX_DENSITY:
            continue

        # Guard C: run count (gap > 3 px = new run)
        runs = 1
        for i in range(1, len(o_xs)):
            if int(o_xs[i]) - int(o_xs[i - 1]) > 3:
                runs += 1
        if runs > MAX_RUNS:
            continue

        sig_rows.append((y, int(o_xs[0]), int(o_xs[-1])))

    if not sig_rows:
        return []

    # ── 4. Cluster qualifying rows ─────────────────────────────────────────
    clusters: list[list[tuple[int, int, int]]] = []
    cur: list[tuple[int, int, int]] = [sig_rows[0]]
    for i in range(1, len(sig_rows)):
        if sig_rows[i][0] - sig_rows[i - 1][0] <= MERGE_GAP:
            cur.append(sig_rows[i])
        else:
            clusters.append(cur)
            cur = [sig_rows[i]]
    clusters.append(cur)

    qualifying = [c for c in clusters if len(c) >= MIN_ROWS]
    if not qualifying:
        qualifying = [max(clusters, key=len)]

    # Take the LARGEST qualifying cluster.
    # The signature is the most ink-dense handwritten element and always
    # produces more qualifying rows than horizontal rules (2-5 rows) or
    # isolated printed labels (5-8 rows). "Bottommost" fails when a form
    # line (e.g. "Payable at par...") sits below the signature in the zone.
    best = max(qualifying, key=len)

    left   = min(r[1] for r in best)
    top    = min(r[0] for r in best)
    right  = max(r[2] for r in best)
    bottom = max(r[0] for r in best) + 1

    if bottom - top < 2 or right - left < 8:
        return []

    # ── 5. Convert to full-image normalised coords ───────────────────────
    abs_x1 = (zx1 + left)   / iw
    abs_y1 = (zy1 + top)    / ih
    abs_x2 = (zx1 + right)  / iw
    abs_y2 = (zy1 + bottom) / ih

    return [{"bbox": [round(abs_x1, 4), round(abs_y1, 4),
                      round(abs_x2, 4), round(abs_y2, 4)],
             "confidence": 0.80}]


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
    import base64, json, httpx

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


@app.get("/health/live", include_in_schema=False)
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    return JSONResponse({"status": "ready", "mode": _mode})


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8020, reload=False)
