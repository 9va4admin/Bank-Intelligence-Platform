"""
IndicOCR Microservice — Devanagari OCR for Indian cheque field zones.

Three backends (select via INDIC_OCR_BACKEND env var or ?backend= per request):

  paddle      (default) — PaddleOCR with Hindi model.  Pip-installable, offline,
                          better accuracy than EasyOCR on printed Indian bank fonts.
                          Install: pip install paddlepaddle paddleocr
                          GPU:     pip install paddlepaddle-gpu paddleocr
                          Downloads ~80 MB Hindi model to ~/.paddleocr/ on first run.

  ai4bharat             — AI4Bharat IndicOCR (CRNN weights). Highest accuracy on
                          Indian document/cheque Devanagari. NOT pip-installable.
                          Requires manual setup — see _get_ai4bharat_reader() below.
                          Once weights are in place, set INDIC_OCR_BACKEND=ai4bharat.

  easyocr               — EasyOCR 'hi' pack. Simplest fallback; lower accuracy on
                          printed bank fonts but zero extra setup if already installed.
                          Install: pip install easyocr

Configuration:
  INDIC_OCR_BACKEND=paddle     # service-wide default (env var)
  ?backend=easyocr             # per-request override (query param)

Start:
    cd apps/indic_ocr && python main.py
    uvicorn apps.indic_ocr.main:app --port 8021

CTS-2010 field zones: bank_name, date, payee_name, amount_words.
MICR / cheque number / account number are English numerics — not extracted here.
"""

import io
import os
from typing import Any, Optional

import numpy as np
import structlog
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

# ── Backend constants ─────────────────────────────────────────────────────────

BACKEND_PADDLE     = "paddle"
BACKEND_AI4BHARAT  = "ai4bharat"
BACKEND_EASYOCR    = "easyocr"
_VALID_BACKENDS    = {BACKEND_PADDLE, BACKEND_AI4BHARAT, BACKEND_EASYOCR}

_SERVICE_DEFAULT: str = os.environ.get("INDIC_OCR_BACKEND", BACKEND_PADDLE).lower()
if _SERVICE_DEFAULT not in _VALID_BACKENDS:
    log.warning("indic_ocr.invalid_backend_env",
                value=_SERVICE_DEFAULT, fallback=BACKEND_PADDLE)
    _SERVICE_DEFAULT = BACKEND_PADDLE

# ── CTS-2010 field zones ──────────────────────────────────────────────────────

_CTS_ZONES: dict[str, tuple[float, float, float, float]] = {
    "bank_name":    (0.00, 0.00, 0.65, 0.20),
    "date":         (0.62, 0.00, 1.00, 0.22),
    "payee_name":   (0.05, 0.25, 0.88, 0.46),
    "amount_words": (0.05, 0.44, 0.88, 0.63),
}

# ── Lazy singletons ───────────────────────────────────────────────────────────

_paddle_ocr:       Optional[Any] = None
_easyocr_reader:   Optional[Any] = None


def _get_paddle_ocr() -> Any:
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            from paddleocr import PaddleOCR  # pip install paddlepaddle paddleocr
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR not installed.\n"
                "CPU:  pip install paddlepaddle paddleocr\n"
                "GPU:  pip install paddlepaddle-gpu paddleocr"
            ) from exc
        # use_angle_cls=True handles rotated text (cheque backs, stamps).
        # show_log=False suppresses PaddlePaddle's verbose download logs.
        _paddle_ocr = PaddleOCR(use_angle_cls=True, lang="hi", show_log=False)
        log.info("indic_ocr.paddle_loaded", lang="hi")
    return _paddle_ocr


def _get_ai4bharat_reader() -> Any:
    """
    AI4Bharat IndicOCR — manual setup required (not pip-installable).

    Setup steps:
      1. git clone https://github.com/AI4Bharat/IndicOCR  apps/indic_ocr/ai4bharat_src
      2. Download Devanagari CRNN weights from their GitHub releases page and place at:
             apps/indic_ocr/weights/ai4bharat/devanagari_crnn.pth
      3. pip install -r apps/indic_ocr/ai4bharat_src/requirements.txt
      4. Implement the loader below using their inference API.
      5. Set INDIC_OCR_BACKEND=ai4bharat to activate.

    Reference: https://github.com/AI4Bharat/IndicOCR
    """
    raise NotImplementedError(
        "AI4Bharat IndicOCR backend is not yet set up on this instance.\n"
        "See _get_ai4bharat_reader() in apps/indic_ocr/main.py for setup steps.\n"
        "Use INDIC_OCR_BACKEND=paddle (default) or INDIC_OCR_BACKEND=easyocr in the meantime."
    )


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
    Returns [(text, confidence)] regardless of backend.
    """
    if backend == BACKEND_PADDLE:
        ocr    = _get_paddle_ocr()
        result = ocr.ocr(arr, cls=True)
        # PaddleOCR returns: list-per-image → list-of-lines
        # Each line: [[bbox_points], [text, confidence]]
        pairs: list[tuple[str, float]] = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0]
                    conf = float(line[1][1])
                    if text:
                        pairs.append((text, conf))
        return pairs

    elif backend == BACKEND_AI4BHARAT:
        # Raises NotImplementedError until weights are installed.
        _get_ai4bharat_reader()
        return []  # unreachable — kept for type checker

    else:  # EASYOCR
        reader = _get_easyocr_reader()
        raw    = reader.readtext(arr, detail=1) or []
        # easyocr: [bbox, text, confidence]
        return [(r[1], float(r[2])) for r in raw if r[1]]


def _resolve_backend(override: Optional[str]) -> str:
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
        "Default: PaddleOCR (paddle). "
        "Planned: AI4Bharat IndicOCR (ai4bharat, manual setup). "
        "Fallback: EasyOCR (easyocr)."
    ),
    version="2.1.0",
    docs_url="/docs" if os.environ.get("ASTRA_ENV", "dev") == "dev" else None,
    redoc_url=None,
)

# ── Response models ───────────────────────────────────────────────────────────

class OcrResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    text:       str
    confidence: float
    backend:    str


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
    service_default:  str
    valid_backends:   list[str]
    loaded:           dict[str, bool]
    ai4bharat_status: str


# ── Health + info ─────────────────────────────────────────────────────────────

@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": "indic-ocr"}


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    if _SERVICE_DEFAULT == BACKEND_AI4BHARAT:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "backend": BACKEND_AI4BHARAT,
                "error": "AI4Bharat backend requires manual setup. See /info.",
            },
        )
    try:
        if _SERVICE_DEFAULT == BACKEND_PADDLE:
            _get_paddle_ocr()
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
    return BackendInfo(
        service_default  = _SERVICE_DEFAULT,
        valid_backends   = sorted(_VALID_BACKENDS),
        loaded           = {
            BACKEND_PADDLE:    _paddle_ocr     is not None,
            BACKEND_AI4BHARAT: False,           # never loaded until manual setup
            BACKEND_EASYOCR:   _easyocr_reader is not None,
        },
        ai4bharat_status = (
            "NOT_IMPLEMENTED — clone https://github.com/AI4Bharat/IndicOCR, "
            "download Devanagari CRNN weights → apps/indic_ocr/weights/ai4bharat/, "
            "implement loader in _get_ai4bharat_reader(), "
            "then set INDIC_OCR_BACKEND=ai4bharat"
        ),
    )


# ── OCR endpoints ─────────────────────────────────────────────────────────────

@app.post("/ocr", response_model=OcrResult)
async def ocr_image(
    file:    UploadFile = File(...),
    backend: Optional[str] = Query(
        default=None,
        description="Backend override: 'paddle', 'ai4bharat', or 'easyocr'. Omit to use service default.",
    ),
) -> OcrResult:
    """Run Devanagari OCR on the entire uploaded image. Returns concatenated text."""
    b = _resolve_backend(backend)
    try:
        raw_bytes = await file.read()
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="Unreadable image.")

    arr   = np.array(img)
    pairs = _run_ocr(arr, b)

    if not pairs:
        return OcrResult(text="", confidence=0.0, backend=b)

    texts = [p[0] for p in pairs]
    confs = [p[1] for p in pairs]
    avg   = sum(confs) / len(confs)
    log.info("indic_ocr.full_ocr_done", backend=b,
             text_preview=" ".join(texts)[:80], confidence=round(avg, 4))
    return OcrResult(text=" ".join(texts), confidence=round(avg, 4), backend=b)


@app.post("/ocr_zones", response_model=ZoneOcrResult)
async def ocr_zones(
    file:    UploadFile = File(...),
    backend: Optional[str] = Query(
        default=None,
        description="Backend override: 'paddle', 'ai4bharat', or 'easyocr'. Omit to use service default.",
    ),
) -> ZoneOcrResult:
    """
    Crop CTS-2010 field zones from the full cheque image and run Devanagari OCR
    on each zone independently.

    Returns: payee_name, amount_words, date, bank_name.
    MICR / cheque number / account number are English numerics — not extracted here.
    """
    b = _resolve_backend(backend)
    try:
        raw_bytes = await file.read()
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="Unreadable image.")

    iw, ih       = img.size
    raw_results:  dict[str, list]          = {}
    field_text:   dict[str, Optional[str]] = {}

    for field, (x1f, y1f, x2f, y2f) in _CTS_ZONES.items():
        x1 = max(0,  int(x1f * iw))
        y1 = max(0,  int(y1f * ih))
        x2 = min(iw, int(x2f * iw))
        y2 = min(ih, int(y2f * ih))
        if x2 <= x1 or y2 <= y1:
            field_text[field]  = None
            raw_results[field] = []
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
