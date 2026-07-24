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

_yolo_model = None   # loaded only when SIG_DETECTOR_LOCAL_PATH is set
_mode: str = "pixel"


@app.on_event("startup")
async def _startup() -> None:
    global _yolo_model, _mode
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
        log.info("sig_detector.ready", mode="pixel",
                 note="Set SIG_DETECTOR_LOCAL_PATH to a .pt file to enable YOLOv8")


# ── Pixel-based detector ──────────────────────────────────────────────────────

def _ink_threshold(arr: np.ndarray) -> int:
    """10th-percentile intensity + 28, clamped to [60, 150]."""
    p10 = int(np.percentile(arr.flatten(), 10))
    return max(60, min(150, p10 + 28))


def _smooth_profile(profile: np.ndarray, window: int = 5) -> np.ndarray:
    """
    Moving-average smoothing over a 1-D row-density profile.
    Merges tiny intra-signature gaps (1–4 rows) so they don't register as
    the "largest gap", leaving only the true gap between signature and text.
    """
    kernel = np.ones(window) / window
    return np.convolve(profile, kernel, mode="same")


def _detect_pixel(img: Image.Image) -> list[dict]:
    """
    Find the signature region in a cheque image using ink-row profiling.

    CTS-2010 layout assumed:
      - Signature zone: y ∈ [55%, 90%] of image height, x ∈ [52%, 100%]
      - Within that zone: signature strokes on top, printed name below
      - A blank (or near-blank) gap separates them

    Denoising steps (tuned to exclude printed-name text from crop):
      1. MedianFilter(3) on zone greyscale — removes salt-and-pepper noise
      2. 5-row moving average on the ink-density profile — merges tiny
         internal signature gaps so only the true sig/text gap dominates
      3. Minimum gap of 3 blank rows required for a valid cut

    Returns a list with one detection dict (bbox normalised, confidence 0.80)
    or [] when no ink is found.
    """
    from PIL import ImageFilter  # local import keeps top-level imports unchanged

    iw, ih = img.size

    # ── 1. Crop to the CTS-2010 signature zone ───────────────────────────
    # y starts at 55% (was 52%) to skip the amount-in-figures row that
    # sometimes lands at ~52–54% and introduces stray ink near the zone top.
    zy1 = int(ih * 0.55)
    zy2 = int(ih * 0.90)
    zx1 = int(iw * 0.52)
    zx2 = iw
    zone = img.crop((zx1, zy1, zx2, zy2))
    zw, zh = zone.size

    # ── 2. Denoise: MedianFilter removes isolated noise pixels ───────────
    gray_img = zone.convert("L").filter(ImageFilter.MedianFilter(size=3))
    gray = np.array(gray_img)
    thr  = _ink_threshold(gray)
    ink  = (gray < thr).astype(np.uint8)   # 1 = ink pixel

    # ── 3. Per-row ink density profile with smoothing ────────────────────
    raw_density  = ink.sum(axis=1) / zw        # raw fraction of ink pixels per row
    row_density  = _smooth_profile(raw_density, window=5)  # merge tiny intra-sig gaps
    ink_rows     = row_density > 0.01           # rows with meaningful ink (post-smooth)

    # ── 4. Top-gap: strip annotations above the signature (NKIT, KUMAR stamps) ──
    # Find the FIRST row gap from the top where ink below is ≥ 3× ink above.
    # That means: small annotation at top, main signature below.
    sig_top_zone = 0
    y = 0
    while y < zh - 1:
        if not ink_rows[y]:
            y += 1
            continue
        sec_end = y
        while sec_end < zh and ink_rows[sec_end]:
            sec_end += 1
        gap_end = sec_end
        while gap_end < zh and not ink_rows[gap_end]:
            gap_end += 1
        gap_len = gap_end - sec_end
        if gap_len >= 2:
            ink_before = int(ink_rows[:sec_end].sum())
            ink_after  = int(ink_rows[gap_end:].sum())
            if ink_before > 0 and ink_after >= ink_before * 3:
                sig_top_zone = gap_end
        break

    # ── 5. Bottom-gap: separate signature from text below ─────────────────
    best_gap_start = best_gap_len = 0
    cur_start = cur_len = 0
    in_gap = False

    for y, has_ink in enumerate(ink_rows):
        if not has_ink:
            if not in_gap:
                cur_start = y
                cur_len   = 0
                in_gap    = True
            cur_len += 1
            if cur_len > best_gap_len:
                best_gap_len   = cur_len
                best_gap_start = cur_start
        else:
            in_gap = False

    if best_gap_len >= 3:
        ink_above_count = ink_rows[sig_top_zone:best_gap_start].sum()
        if ink_above_count >= 6:
            sig_bottom_zone = best_gap_start
        else:
            sig_bottom_zone = zh
    else:
        sig_bottom_zone = zh

    # ── 6. Tight bbox from raw ink between top and bottom cuts ────────────
    ink_above = ink[sig_top_zone:sig_bottom_zone, :]
    ink_coords = np.argwhere(ink_above)
    if ink_coords.size == 0:
        return []

    top    = int(ink_coords[:, 0].min())
    bottom = int(ink_coords[:, 0].max()) + 1
    left   = int(ink_coords[:, 1].min())
    right  = int(ink_coords[:, 1].max()) + 1

    if bottom - top < 5 or right - left < 10:
        return []

    abs_x1 = (zx1 + left)              / iw
    abs_y1 = (zy1 + sig_top_zone + top) / ih
    abs_x2 = (zx1 + right)             / iw
    abs_y2 = (zy1 + sig_top_zone + bottom) / ih

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

    # Top-gap: annotation above sig (same logic as _detect_pixel)
    sig_top = 0
    y = 0
    while y < ch - 1:
        if not ink_rows[y]:
            y += 1
            continue
        sec_end = y
        while sec_end < ch and ink_rows[sec_end]:
            sec_end += 1
        gap_end = sec_end
        while gap_end < ch and not ink_rows[gap_end]:
            gap_end += 1
        gap_len = gap_end - sec_end
        if gap_len >= 2:
            ink_before = int(ink_rows[:sec_end].sum())
            ink_after  = int(ink_rows[gap_end:].sum())
            if ink_before > 0 and ink_after >= ink_before * 3:
                sig_top = gap_end
        break

    # Bottom-gap: text below sig
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

    if best_gap_len >= 3 and ink_rows[sig_top:best_gap_start].sum() >= 6:
        sig_bottom = best_gap_start
    else:
        sig_bottom = ch

    ink_region = ink[sig_top:sig_bottom, :]
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
        round((px1 + left)              / iw, 4),
        round((py1 + sig_top + top)     / ih, 4),
        round((px1 + right)             / iw, 4),
        round((py1 + sig_top + bottom)  / ih, 4),
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


# ── API ───────────────────────────────────────────────────────────────────────

class Detection(BaseModel):
    bbox: list[float]
    confidence: float


class DetectResponse(BaseModel):
    detections: list[Detection]
    mode: str           # "yolov8" or "pixel"
    image_size: list[int]


@app.post("/detect", response_model=DetectResponse)
async def detect_signatures(file: UploadFile = File(...)) -> DetectResponse:
    data = await file.read()
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc

    iw, ih = img.size
    raw = _detect_yolo(img) if _mode == "yolov8" else _detect_pixel(img)
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
