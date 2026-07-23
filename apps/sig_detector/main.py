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


def _detect_pixel(img: Image.Image) -> list[dict]:
    """
    Find the signature region in a cheque image using ink-row profiling.

    CTS-2010 layout assumed:
      - Signature zone: y ∈ [52%, 90%] of image height, x ∈ [38%, 100%]
      - Within that zone: signature strokes on top, printed name below
      - A blank (or near-blank) gap separates them

    Returns a list with one detection dict (bbox normalised, confidence 0.80)
    or [] when no ink is found.
    """
    iw, ih = img.size

    # ── 1. Crop to the CTS-2010 signature zone ───────────────────────────
    # x starts at 52% (not 38%) to avoid bottom-left bank name text that
    # sits in the lower-left corner of CTS-2010 cheques.
    zy1 = int(ih * 0.52)
    zy2 = int(ih * 0.90)
    zx1 = int(iw * 0.52)
    zx2 = iw
    zone = img.crop((zx1, zy1, zx2, zy2))
    zw, zh = zone.size

    gray = np.array(zone.convert("L"))
    thr  = _ink_threshold(gray)
    ink  = (gray < thr).astype(np.uint8)   # 1 = ink pixel

    # ── 2. Per-row ink density profile ───────────────────────────────────
    row_density = ink.sum(axis=1) / zw     # fraction of ink pixels per row

    ink_rows = row_density > 0.01          # rows with meaningful ink

    # ── 3. Find the largest blank gap in the ink profile ─────────────────
    # We scan for consecutive non-ink rows; the longest such run is the
    # boundary between the signature strokes (above) and the printed name.
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

    # Cut at the top of the best gap if it's at least 1 row wide and is
    # preceded by at least 6 rows of ink (the signature itself).
    # If no real gap found, take the full zone.
    if best_gap_len >= 1:
        ink_above = ink_rows[:best_gap_start].sum()
        if ink_above >= 6:
            sig_bottom_zone = best_gap_start   # exclusive, zone-relative
        else:
            sig_bottom_zone = zh
    else:
        sig_bottom_zone = zh

    # ── 4. Find tight bbox of ink ABOVE the cut ──────────────────────────
    ink_above = ink[:sig_bottom_zone, :]
    ink_coords = np.argwhere(ink_above)
    if ink_coords.size == 0:
        return []

    top    = int(ink_coords[:, 0].min())
    bottom = int(ink_coords[:, 0].max()) + 1
    left   = int(ink_coords[:, 1].min())
    right  = int(ink_coords[:, 1].max()) + 1

    if bottom - top < 5 or right - left < 10:
        return []

    # ── 5. Convert to full-image normalised coords ───────────────────────
    abs_x1 = (zx1 + left)   / iw
    abs_y1 = (zy1 + top)    / ih
    abs_x2 = (zx1 + right)  / iw
    abs_y2 = (zy1 + bottom) / ih

    return [{"bbox": [round(abs_x1, 4), round(abs_y1, 4),
                      round(abs_x2, 4), round(abs_y2, 4)],
             "confidence": 0.80}]


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
            detections.append({"bbox": [round(x1, 4), round(y1, 4),
                                        round(x2, 4), round(y2, 4)],
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
