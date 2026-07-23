"""
ASTRA Signature Detector — YOLOv8-based microservice.

Accepts a cheque image (multipart POST /detect), returns normalised bounding
boxes of every detected handwritten signature.  Runs on CPU — YOLOv8s is
small enough that inference completes in < 200ms on a modern core.

Model: keremberke/yolov8s-signature-detection (public HF model, no gating)
Fallback: set SIG_DETECTOR_MODEL env var to a local .pt/.onnx path or any
other HF model ID that ultralytics can load.

Port: 8020 (local dev).  In K8s: deployed as astra-sig-detector in the
astra-cts-{bank_id} namespace, reachable at http://sig-detector:8020.
"""
from __future__ import annotations

import io
import os

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

_model = None
_model_name: str = ""


@app.on_event("startup")
async def _load_model() -> None:
    global _model, _model_name
    from ultralytics import YOLO

    model_src = os.environ.get(
        "SIG_DETECTOR_MODEL", "keremberke/yolov8s-signature-detection"
    )
    log.info("sig_detector.loading", model=model_src)
    try:
        _model = YOLO(model_src)
        _model_name = model_src
        log.info("sig_detector.ready", model=model_src)
    except Exception as exc:
        log.error("sig_detector.load_failed", model=model_src, error=str(exc))
        raise


class Detection(BaseModel):
    bbox: list[float]  # [x1, y1, x2, y2] — normalised 0.0–1.0
    confidence: float


class DetectResponse(BaseModel):
    detections: list[Detection]
    model: str
    image_size: list[int]  # [width, height] of the input image


@app.post("/detect", response_model=DetectResponse)
async def detect_signatures(file: UploadFile = File(...)) -> DetectResponse:
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet — try again shortly.")

    data = await file.read()
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc

    iw, ih = img.size

    conf_threshold = float(os.environ.get("SIG_DETECTOR_CONF", "0.25"))
    iou_threshold  = float(os.environ.get("SIG_DETECTOR_IOU",  "0.45"))

    results = _model.predict(img, conf=conf_threshold, iou=iou_threshold, verbose=False)

    detections: list[Detection] = []
    for r in results:
        if r.boxes is None:
            continue
        for box, conf in zip(r.boxes.xyxyn.tolist(), r.boxes.conf.tolist()):
            x1, y1, x2, y2 = box
            detections.append(Detection(
                bbox=[round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                confidence=round(float(conf), 4),
            ))

    # Sort by confidence descending
    detections.sort(key=lambda d: d.confidence, reverse=True)

    log.info("sig_detector.detected", count=len(detections), model=_model_name)
    return DetectResponse(detections=detections, model=_model_name, image_size=[iw, ih])


@app.get("/health/live", include_in_schema=False)
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    if _model is None:
        return JSONResponse({"status": "loading", "model": _model_name}, status_code=503)
    return JSONResponse({"status": "ready", "model": _model_name})


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8020, reload=False)
