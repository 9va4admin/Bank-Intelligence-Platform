"""
ASTRA Signature Detector — YOLOv8-based microservice.

Accepts a cheque image (multipart POST /detect), returns normalised bounding
boxes of every detected handwritten signature.  Runs on CPU.

Model: tech4humans/yolov8s-signature-detector (yolov8s.pt, ~23 MB)
Downloaded via huggingface_hub at first startup, then cached locally by HF.

Token: reads ASTRA_DEMO_HF_TOKEN from .env.local (same as dev_auth_server.py)
and exposes it as HF_TOKEN for huggingface_hub.

Port: 8020 (local dev). In K8s: astra-sig-detector in astra-cts-{bank_id}.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

# Load .env.local so ASTRA_DEMO_HF_TOKEN is available without manual export.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env.local", override=False)
except ImportError:
    pass

# Bridge ASTRA_DEMO_HF_TOKEN → HF_TOKEN used by huggingface_hub.
if not os.environ.get("HF_TOKEN") and os.environ.get("ASTRA_DEMO_HF_TOKEN"):
    os.environ["HF_TOKEN"] = os.environ["ASTRA_DEMO_HF_TOKEN"]

import structlog
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

log = structlog.get_logger()

_HF_REPO    = "tech4humans/yolov8s-signature-detector"
_HF_FILE    = "yolov8s.pt"

app = FastAPI(
    title="ASTRA Signature Detector",
    docs_url="/docs" if os.environ.get("ENV", "production") == "development" else None,
    redoc_url=None,
)

_model = None
_model_name: str = ""


def _download_model() -> str:
    """Download the model file from HuggingFace Hub and return the local path."""
    from huggingface_hub import hf_hub_download

    repo_id  = os.environ.get("SIG_DETECTOR_REPO", _HF_REPO)
    filename = os.environ.get("SIG_DETECTOR_FILE", _HF_FILE)
    token    = os.environ.get("HF_TOKEN") or None

    log.info("sig_detector.downloading", repo=repo_id, file=filename)
    local_path = hf_hub_download(repo_id=repo_id, filename=filename, token=token)
    log.info("sig_detector.downloaded", path=local_path)
    return local_path


@app.on_event("startup")
async def _load_model() -> None:
    global _model, _model_name
    from ultralytics import YOLO

    # Allow pointing straight at a local .pt/.onnx file to skip the HF download.
    local_override = os.environ.get("SIG_DETECTOR_LOCAL_PATH")
    if local_override:
        model_path = local_override
        log.info("sig_detector.using_local_override", path=model_path)
    else:
        model_path = _download_model()

    try:
        _model = YOLO(model_path)
        _model_name = model_path
        log.info("sig_detector.ready", model=model_path)
    except Exception as exc:
        log.error("sig_detector.load_failed", model=model_path, error=str(exc))
        raise


class Detection(BaseModel):
    bbox: list[float]  # [x1, y1, x2, y2] normalised 0.0–1.0
    confidence: float


class DetectResponse(BaseModel):
    detections: list[Detection]
    model: str
    image_size: list[int]


@app.post("/detect", response_model=DetectResponse)
async def detect_signatures(file: UploadFile = File(...)) -> DetectResponse:
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

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

    detections.sort(key=lambda d: d.confidence, reverse=True)
    log.info("sig_detector.detected", count=len(detections))
    return DetectResponse(detections=detections, model=_model_name, image_size=[iw, ih])


@app.get("/health/live", include_in_schema=False)
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    if _model is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return JSONResponse({"status": "ready", "model": _model_name})


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8020, reload=False)
