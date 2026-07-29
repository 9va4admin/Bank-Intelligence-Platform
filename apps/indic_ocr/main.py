"""
IndicOCR Microservice — Devanagari OCR for Indian cheque field zones.

Stage 1: Hindi/Marathi/Sanskrit (Devanagari script) using EasyOCR.
Stage 2 (planned): add ta, te, kn, ml, gu, pa packs.
Stage 3 (planned): fine-tune on annotated cheque crops.

Runs on port 8021, separate from sig_detector (8020).
GPU (RTX 4090) used automatically if CUDA is available; falls back to CPU.

Start:
    cd apps/indic_ocr
    python main.py
    # or
    uvicorn apps.indic_ocr.main:app --port 8021

No HF token required — EasyOCR downloads the 'hi' language pack from
https://www.jaided.ai/easyocr/modelhub/ on first start (~100 MB total).
Subsequent starts use the local cache (~/.EasyOCR/).

CTS-2010 field zones (hardcoded approximate fractions):
  These cover the standard printed layout for Indian CTS-2010 cheques.
  They do NOT need to be exact — EasyOCR runs on the full zone crop and
  returns all Devanagari text found within that region.
"""

import io
import os
from typing import Optional

import structlog
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

app = FastAPI(
    title="ASTRA IndicOCR",
    description="Devanagari OCR for Indian cheque fields — EasyOCR Stage 1",
    version="1.0.0",
    docs_url="/docs" if os.environ.get("ASTRA_ENV", "dev") == "dev" else None,
    redoc_url=None,
)

# Lazy-initialised — loaded on first request so startup is instant
_reader = None

# CTS-2010 approximate field zones as (x1_frac, y1_frac, x2_frac, y2_frac).
# Covers payee line, amount-in-words line, date box, and bank name area.
# MICR / cheque number / account number are printed in English numerics —
# they are not Devanagari and are not extracted by this service.
_CTS_ZONES: dict[str, tuple[float, float, float, float]] = {
    "bank_name":    (0.00, 0.00, 0.65, 0.20),
    "date":         (0.62, 0.00, 1.00, 0.22),
    "payee_name":   (0.05, 0.25, 0.88, 0.46),
    "amount_words": (0.05, 0.44, 0.88, 0.63),
}


def _get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
        except ImportError as exc:
            raise RuntimeError(
                "EasyOCR not installed. Run: pip install easyocr"
            ) from exc
        # gpu=True: uses CUDA if available, silently falls back to CPU
        _reader = easyocr.Reader(["hi"], gpu=True, verbose=False)
        log.info("indic_ocr.reader_loaded", lang="hi")
    return _reader


@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": "indic-ocr"}


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    try:
        _get_reader()
        return {"status": "ready", "lang": "hi"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "error": str(exc)},
        )


class OcrResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    text: str
    confidence: float


class ZoneOcrResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_name: Optional[str] = None
    date: Optional[str] = None
    payee_name: Optional[str] = None
    amount_words: Optional[str] = None
    raw: dict  # zone_name → list of [text, confidence] pairs


@app.post("/ocr", response_model=OcrResult)
async def ocr_image(file: UploadFile = File(...)) -> OcrResult:
    """Run Devanagari OCR on the entire uploaded image. Returns concatenated text."""
    try:
        raw_bytes = await file.read()
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="Unreadable image.")

    import numpy as np

    arr = np.array(img)
    reader = _get_reader()
    results = reader.readtext(arr, detail=1)

    if not results:
        return OcrResult(text="", confidence=0.0)

    texts = [r[1] for r in results]
    confidences = [r[2] for r in results]
    avg_conf = sum(confidences) / len(confidences)
    return OcrResult(text=" ".join(texts), confidence=round(avg_conf, 4))


@app.post("/ocr_zones", response_model=ZoneOcrResult)
async def ocr_zones(file: UploadFile = File(...)) -> ZoneOcrResult:
    """
    Crop CTS-2010 field zones from the full cheque image and run Devanagari OCR
    on each zone independently.

    Returns per-field Devanagari text — payee_name, amount_words, date,
    bank_name.  Fields not visible in a zone return null.
    MICR / cheque number / account number are not extracted here (they are
    English numerics, not Devanagari).
    """
    try:
        raw_bytes = await file.read()
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="Unreadable image.")

    import numpy as np

    iw, ih = img.size
    reader = _get_reader()
    raw_results: dict = {}
    field_text: dict[str, Optional[str]] = {}

    for field, (x1f, y1f, x2f, y2f) in _CTS_ZONES.items():
        x1 = max(0, int(x1f * iw))
        y1 = max(0, int(y1f * ih))
        x2 = min(iw, int(x2f * iw))
        y2 = min(ih, int(y2f * ih))
        if x2 <= x1 or y2 <= y1:
            field_text[field] = None
            raw_results[field] = []
            continue

        zone = img.crop((x1, y1, x2, y2))
        arr = np.array(zone)
        results = reader.readtext(arr, detail=1)

        if results:
            texts = [r[1] for r in results]
            confs = [float(r[2]) for r in results]
            combined = " ".join(texts)
            avg_conf = sum(confs) / len(confs)
            field_text[field] = combined
            raw_results[field] = [[t, round(c, 4)] for t, c in zip(texts, confs)]
            log.info(
                "indic_ocr.zone_result",
                field=field,
                text=combined[:80],
                conf=round(avg_conf, 4),
            )
        else:
            field_text[field] = None
            raw_results[field] = []

    return ZoneOcrResult(
        bank_name=field_text.get("bank_name"),
        date=field_text.get("date"),
        payee_name=field_text.get("payee_name"),
        amount_words=field_text.get("amount_words"),
        raw=raw_results,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8021, log_level="info")
