"""
IndicOCR Microservice — Devanagari OCR for Indian cheque field zones.

Two backends, both kept available at runtime:

  ai4bharat  (default) — AI4Bharat ilocr; trained on Indian scripts; higher
                          accuracy on printed Devanagari bank fonts.
                          Install: pip install ilocr
                          Downloads ~150 MB model to ~/.ilocr/ on first run.

  easyocr              — EasyOCR 'hi' language pack; general-purpose;
                          useful as a quick fallback or for comparison.
                          Install: pip install easyocr
                          Downloads ~100 MB to ~/.EasyOCR/ on first run.

Configuration:
  INDIC_OCR_BACKEND=ai4bharat   # service-wide default (env var)
  ?backend=easyocr              # per-request override (query param)

Start:
    cd apps/indic_ocr && python main.py
    # or
    uvicorn apps.indic_ocr.main:app --port 8021

CTS-2010 field zones (hardcoded approximate fractions):
  bank_name, date, payee_name, amount_words.
  MICR / cheque number / account number are English numerics — not extracted here.
"""

import io
import os
from typing import Any, Literal, Optional

import numpy as np
import structlog
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

# ── Backend constants ─────────────────────────────────────────────────────────

BACKEND_AI4BHARAT = "ai4bharat"
BACKEND_EASYOCR   = "easyocr"
_VALID_BACKENDS   = {BACKEND_AI4BHARAT, BACKEND_EASYOCR}

_SERVICE_DEFAULT: str = os.environ.get("INDIC_OCR_BACKEND", BACKEND_AI4BHARAT).lower()
if _SERVICE_DEFAULT not in _VALID_BACKENDS:
    log.warning("indic_ocr.invalid_backend_env",
                value=_SERVICE_DEFAULT, fallback=BACKEND_AI4BHARAT)
    _SERVICE_DEFAULT = BACKEND_AI4BHARAT

# ── CTS-2010 field zones ──────────────────────────────────────────────────────

# (x1_frac, y1_frac, x2_frac, y2_frac) of the full cheque image.
_CTS_ZONES: dict[str, tuple[float, float, float, float]] = {
    "bank_name":    (0.00, 0.00, 0.65, 0.20),
    "date":         (0.62, 0.00, 1.00, 0.22),
    "payee_name":   (0.05, 0.25, 0.88, 0.46),
    "amount_words": (0.05, 0.44, 0.88, 0.63),
}

# ── Lazy singletons — one per backend ────────────────────────────────────────

_ai4bharat_reader: Optional[Any] = None
_easyocr_reader:   Optional[Any] = None


def _get_ai4bharat_reader() -> Any:
    global _ai4bharat_reader
    if _ai4bharat_reader is None:
        try:
            from ilocr import OCR  # pip install ilocr
        except ImportError as exc:
            raise RuntimeError(
                "AI4Bharat ilocr not installed. Run: pip install ilocr"
            ) from exc
        # lang='Hindi' covers Devanagari (Hindi, Marathi, Sanskrit).
        # PyTorch detects CUDA automatically — no gpu flag needed.
        _ai4bharat_reader = OCR(lang="Hindi")
        log.info("indic_ocr.ai4bharat_loaded", lang="Hindi")
    return _ai4bharat_reader


def _get_easyocr_reader() -> Any:
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr  # pip install easyocr
        except ImportError as exc:
            raise RuntimeError(
                "EasyOCR not installed. Run: pip install easyocr"
            ) from exc
        _easyocr_reader = easyocr.Reader(["hi"], gpu=True, verbose=False)
        log.info("indic_ocr.easyocr_loaded", lang="hi")
    return _easyocr_reader


def _run_ocr(arr: np.ndarray, backend: str) -> list[tuple[str, float]]:
    """
    Run OCR on a (H, W, 3) uint8 numpy array.
    Returns a list of (text, confidence) tuples — same contract regardless of backend.
    """
    if backend == BACKEND_AI4BHARAT:
        reader = _get_ai4bharat_reader()
        raw = reader.predict(arr) or []
        pairs: list[tuple[str, float]] = []
        for r in raw:
            if isinstance(r, dict):
                text = r.get("text", "")
                conf = float(r.get("confidence", r.get("score", 1.0)))
            elif isinstance(r, (list, tuple)) and len(r) >= 2:
                # Some ilocr versions return [bbox, text, conf] like easyocr
                text = r[-2] if len(r) >= 3 else str(r[0])
                conf = float(r[-1])
            else:
                continue
            if text:
                pairs.append((text, conf))
        return pairs

    else:  # EASYOCR
        reader = _get_easyocr_reader()
        raw = reader.readtext(arr, detail=1) or []
        # easyocr returns [bbox, text, confidence]
        return [(r[1], float(r[2])) for r in raw if r[1]]


def _resolve_backend(override: Optional[str]) -> str:
    """Return the backend to use: per-request override beats service default."""
    if override:
        b = override.lower()
        if b not in _VALID_BACKENDS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown backend '{override}'. Valid: {sorted(_VALID_BACKENDS)}"
            )
        return b
    return _SERVICE_DEFAULT


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="ASTRA IndicOCR",
    description=(
        "Devanagari OCR for Indian cheque fields. "
        "Default backend: AI4Bharat ilocr. "
        "Fallback: EasyOCR. Both available at runtime via ?backend= param."
    ),
    version="2.0.0",
    docs_url="/docs" if os.environ.get("ASTRA_ENV", "dev") == "dev" else None,
    redoc_url=None,
)

# ── Models ────────────────────────────────────────────────────────────────────

class OcrResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    text:     str
    confidence: float
    backend:  str


class ZoneOcrResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_name:    Optional[str] = None
    date:         Optional[str] = None
    payee_name:   Optional[str] = None
    amount_words: Optional[str] = None
    backend:      str
    raw:          dict  # zone_name → [[text, confidence], ...]


class BackendInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    service_default: str
    valid_backends:  list[str]
    loaded:          dict[str, bool]  # backend → whether singleton is initialised


# ── Health + info endpoints ───────────────────────────────────────────────────

@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": "indic-ocr"}


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    try:
        if _SERVICE_DEFAULT == BACKEND_AI4BHARAT:
            _get_ai4bharat_reader()
        else:
            _get_easyocr_reader()
        return {"status": "ready", "backend": _SERVICE_DEFAULT}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "backend": _SERVICE_DEFAULT, "error": str(exc)},
        )


@app.get("/info", response_model=BackendInfo)
async def info() -> BackendInfo:
    """Return which backend is the service default and which are already loaded."""
    return BackendInfo(
        service_default=_SERVICE_DEFAULT,
        valid_backends=sorted(_VALID_BACKENDS),
        loaded={
            BACKEND_AI4BHARAT: _ai4bharat_reader is not None,
            BACKEND_EASYOCR:   _easyocr_reader   is not None,
        },
    )


# ── OCR endpoints ─────────────────────────────────────────────────────────────

@app.post("/ocr", response_model=OcrResult)
async def ocr_image(
    file:    UploadFile = File(...),
    backend: Optional[str] = Query(
        default=None,
        description="Backend override: 'ai4bharat' or 'easyocr'. Omit to use service default.",
    ),
) -> OcrResult:
    """Run Devanagari OCR on the entire uploaded image. Returns concatenated text."""
    b = _resolve_backend(backend)
    try:
        raw_bytes = await file.read()
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="Unreadable image.")

    arr = np.array(img)
    pairs = _run_ocr(arr, b)

    if not pairs:
        return OcrResult(text="", confidence=0.0, backend=b)

    texts  = [p[0] for p in pairs]
    confs  = [p[1] for p in pairs]
    avg    = sum(confs) / len(confs)
    log.info("indic_ocr.full_ocr_done", backend=b, text_preview=" ".join(texts)[:80],
             confidence=round(avg, 4))
    return OcrResult(text=" ".join(texts), confidence=round(avg, 4), backend=b)


@app.post("/ocr_zones", response_model=ZoneOcrResult)
async def ocr_zones(
    file:    UploadFile = File(...),
    backend: Optional[str] = Query(
        default=None,
        description="Backend override: 'ai4bharat' or 'easyocr'. Omit to use service default.",
    ),
) -> ZoneOcrResult:
    """
    Crop CTS-2010 field zones from the full cheque image and run Devanagari OCR
    on each zone independently.

    Returns per-field Devanagari text: payee_name, amount_words, date, bank_name.
    MICR / cheque number / account number are English numerics — not extracted here.
    """
    b = _resolve_backend(backend)
    try:
        raw_bytes = await file.read()
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="Unreadable image.")

    iw, ih = img.size
    raw_results:  dict[str, list] = {}
    field_text:   dict[str, Optional[str]] = {}

    for field, (x1f, y1f, x2f, y2f) in _CTS_ZONES.items():
        x1 = max(0, int(x1f * iw))
        y1 = max(0, int(y1f * ih))
        x2 = min(iw, int(x2f * iw))
        y2 = min(ih, int(y2f * ih))
        if x2 <= x1 or y2 <= y1:
            field_text[field]   = None
            raw_results[field]  = []
            continue

        zone  = img.crop((x1, y1, x2, y2))
        arr   = np.array(zone)
        pairs = _run_ocr(arr, b)

        if pairs:
            texts     = [p[0] for p in pairs]
            confs     = [p[1] for p in pairs]
            combined  = " ".join(texts)
            avg_conf  = sum(confs) / len(confs)
            field_text[field]  = combined
            raw_results[field] = [[t, round(c, 4)] for t, c in zip(texts, confs)]
            log.info("indic_ocr.zone_done", backend=b, field=field,
                     text=combined[:80], conf=round(avg_conf, 4))
        else:
            field_text[field]  = None
            raw_results[field] = []

    return ZoneOcrResult(
        bank_name    = field_text.get("bank_name"),
        date         = field_text.get("date"),
        payee_name   = field_text.get("payee_name"),
        amount_words = field_text.get("amount_words"),
        backend      = b,
        raw          = raw_results,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8021, log_level="info")
