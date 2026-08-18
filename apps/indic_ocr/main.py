"""
IndicOCR Microservice — multi-script Indic OCR for Indian cheque field zones.

Scripts covered (via PaddleOCR language packs):
  devanagari → hi   Hindi, Marathi, Sanskrit (Devanagari script)
  bengali    → bn   Bengali/Bangla
  gurmukhi   → pa   Punjabi (Gurmukhi)
  gujarati   → gu   Gujarati
  odia       → or   Odia (Oriya)
  tamil      → ta   Tamil
  telugu     → te   Telugu
  kannada    → kn   Kannada
  malayalam  → ml   Malayalam

Backends (select via INDIC_OCR_BACKEND env var):
  paddle      (default) — PaddleOCR, one lazy-loaded instance per script.
                          Install: pip install paddlepaddle paddleocr
                          GPU:     pip install paddlepaddle-gpu paddleocr
  ai4bharat             — Stub: weights not yet set up.  Falls back to paddle.
  easyocr               — EasyOCR ['hi'] pack. Latin-only fallback; ignores ?script.
                          Install: pip install easyocr

Query parameters:
  ?script=devanagari    Language hint from the OCR activity (identify_indic_script() result).
                        When omitted or unknown, defaults to devanagari.
  ?backend=paddle       Per-request backend override.

Start:
    cd apps/indic_ocr && python main.py
    uvicorn apps.indic_ocr.main:app --port 8021
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

# ── Script → PaddleOCR lang code mapping ─────────────────────────────────────
# Keys match the script names returned by identify_indic_script() in zone_extractor.py.
# Values are PaddleOCR lang codes: https://paddlepaddle.github.io/PaddleOCR/latest/en/ppocr/blog/multi_languages.html

_SCRIPT_TO_PADDLE_LANG: dict[str, str] = {
    "devanagari": "hi",   # Hindi, Marathi (Devanagari)
    "bengali":    "bn",
    "gurmukhi":   "pa",   # Punjabi
    "gujarati":   "gu",
    "odia":       "or",   # Oriya
    "tamil":      "ta",
    "telugu":     "te",
    "kannada":    "kn",
    "malayalam":  "ml",
}

_DEFAULT_PADDLE_LANG = "hi"   # fallback when script is unknown or absent

# ── CTS-2010 field zones ──────────────────────────────────────────────────────

_CTS_ZONES: dict[str, tuple[float, float, float, float]] = {
    "bank_name":    (0.00, 0.00, 0.65, 0.20),
    "date":         (0.62, 0.00, 1.00, 0.22),
    "payee_name":   (0.05, 0.25, 0.88, 0.46),
    "amount_words": (0.05, 0.44, 0.88, 0.63),
}

# ── Lazy singletons ───────────────────────────────────────────────────────────
# One PaddleOCR instance per lang code; created on first use and cached.

_paddle_ocr_pool:  dict[str, Any] = {}
_easyocr_reader:   Optional[Any]  = None
_ai4bharat_reader: Optional[Any]  = None


def _get_paddle_ocr(lang: str = _DEFAULT_PADDLE_LANG) -> Any:
    global _paddle_ocr_pool
    if lang not in _paddle_ocr_pool:
        try:
            from paddleocr import PaddleOCR  # pip install paddlepaddle paddleocr
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR not installed.\n"
                "CPU:  pip install paddlepaddle paddleocr\n"
                "GPU:  pip install paddlepaddle-gpu paddleocr"
            ) from exc
        _paddle_ocr_pool[lang] = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
        log.info("indic_ocr.paddle_loaded", lang=lang)
    return _paddle_ocr_pool[lang]


def _get_ai4bharat_reader() -> Any:
    """
    AI4Bharat IndicOCR — uses OneFourthLabs/Indic-OCR framework (the upstream
    implementation AI4Bharat references for Indic document OCR).

    One-time setup on the inference node:
      1. git clone https://github.com/OneFourthLabs/Indic-OCR \\
             apps/indic_ocr/ai4bharat_src
      2. pip install -r apps/indic_ocr/ai4bharat_src/dependencies.txt
      3. Set INDIC_OCR_BACKEND=ai4bharat and restart.

    The framework uses CRAFT text detection + EasyOCR Devanagari recognition,
    fully on-prem with no outbound calls after initial model download.

    Returns an EasyOCR end2end instance from the AI4Bharat framework whose
    .run(numpy_array) produces [{'text': str, 'confidence': float, ...}].
    Falls back to PaddleOCR automatically when the src tree is absent.
    """
    global _ai4bharat_reader
    if _ai4bharat_reader is not None:
        return _ai4bharat_reader

    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai4bharat_src")
    if not os.path.isdir(src_dir):
        raise NotImplementedError(
            "AI4Bharat IndicOCR source tree not found.\n"
            f"Run:  git clone https://github.com/OneFourthLabs/Indic-OCR {src_dir}\n"
            f"      pip install -r {src_dir}/dependencies.txt\n"
            "Then: INDIC_OCR_BACKEND=ai4bharat (restart service)"
        )

    import sys
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    try:
        from indic_ocr.end2end.easy_ocr import EasyOCR as _A4BEasyOCR
    except ImportError as exc:
        raise NotImplementedError(
            f"indic_ocr package not importable from {src_dir}.\n"
            f"Run: pip install -r {src_dir}/dependencies.txt\n"
            f"Error: {exc}"
        ) from exc

    log.info("indic_ocr.ai4bharat_loading", src_dir=src_dir)
    try:
        _ai4bharat_reader = _A4BEasyOCR(langs=["hi", "en"], gpu=True)
        log.info("indic_ocr.ai4bharat_loaded", gpu=True)
    except Exception:
        log.warning("indic_ocr.ai4bharat_gpu_unavailable_falling_back_to_cpu")
        _ai4bharat_reader = _A4BEasyOCR(langs=["hi", "en"], gpu=False)
        log.info("indic_ocr.ai4bharat_loaded", gpu=False)

    return _ai4bharat_reader


def _get_easyocr_reader() -> Any:
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr  # pip install easyocr
        except ImportError as exc:
            raise RuntimeError("EasyOCR not installed. Run: pip install easyocr") from exc
        _easyocr_reader = easyocr.Reader(["hi"], gpu=True, verbose=False)
        log.info("indic_ocr.easyocr_loaded", lang="hi")
    return _easyocr_reader


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


def _resolve_paddle_lang(script: Optional[str]) -> str:
    """Map a script name (from identify_indic_script()) to a PaddleOCR lang code."""
    if not script:
        return _DEFAULT_PADDLE_LANG
    return _SCRIPT_TO_PADDLE_LANG.get(script.lower(), _DEFAULT_PADDLE_LANG)


def _run_ocr(arr: np.ndarray, backend: str, script: Optional[str] = None) -> list[tuple[str, float]]:
    """
    Run OCR on a (H, W, 3) uint8 numpy array.
    Returns [(text, confidence)] regardless of backend.

    script: Indic script name from identify_indic_script() — used to select
            the correct PaddleOCR language model. Ignored for easyocr/ai4bharat.
    """
    if backend == BACKEND_AI4BHARAT:
        try:
            reader  = _get_ai4bharat_reader()
            bboxes  = reader.run(arr) or []
            return [
                (b["text"], float(b.get("confidence", 0.0)))
                for b in bboxes
                if b.get("text")
            ]
        except NotImplementedError:
            log.warning("indic_ocr.ai4bharat_not_ready_falling_back_to_paddle")
            backend = BACKEND_PADDLE   # graceful fallback
        except Exception as exc:
            log.warning("indic_ocr.ai4bharat_inference_error_falling_back_to_paddle",
                        error=str(exc))
            backend = BACKEND_PADDLE

    if backend == BACKEND_PADDLE:
        lang   = _resolve_paddle_lang(script)
        ocr    = _get_paddle_ocr(lang)
        result = ocr.ocr(arr, cls=True)
        pairs: list[tuple[str, float]] = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0]
                    conf = float(line[1][1])
                    if text:
                        pairs.append((text, conf))
        return pairs

    else:  # EASYOCR (always hi — lang pack is fixed on load)
        reader = _get_easyocr_reader()
        raw    = reader.readtext(arr, detail=1) or []
        return [(r[1], float(r[2])) for r in raw if r[1]]


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="ASTRA IndicOCR",
    description=(
        "Multi-script Indic OCR for Indian cheque field zones. "
        "Pass ?script=<script_name> for script-aware PaddleOCR language selection. "
        "Scripts: devanagari, bengali, gurmukhi, gujarati, odia, tamil, telugu, kannada, malayalam."
    ),
    version="3.0.0",
    docs_url="/docs" if os.environ.get("ASTRA_ENV", "dev") == "dev" else None,
    redoc_url=None,
)

# ── Response models ───────────────────────────────────────────────────────────

class OcrResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    text:        str
    confidence:  float
    backend:     str
    script:      Optional[str] = None
    paddle_lang: Optional[str] = None   # resolved PaddleOCR lang code


class ZoneOcrResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_name:    Optional[str] = None
    date:         Optional[str] = None
    payee_name:   Optional[str] = None
    amount_words: Optional[str] = None
    backend:      str
    script:       Optional[str] = None
    raw:          dict   # zone_name → [[text, confidence], ...]


class BackendInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    service_default:   str
    valid_backends:    list[str]
    supported_scripts: list[str]
    loaded_paddle:     list[str]   # lang codes with loaded PaddleOCR instance
    loaded_easyocr:    bool
    loaded_ai4bharat:  bool
    ai4bharat_status:  str


# ── Health + info ─────────────────────────────────────────────────────────────

@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": "indic-ocr"}


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    try:
        if _SERVICE_DEFAULT == BACKEND_EASYOCR:
            _get_easyocr_reader()
        else:
            _get_paddle_ocr(_DEFAULT_PADDLE_LANG)
        return {"status": "ready", "backend": _SERVICE_DEFAULT}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "backend": _SERVICE_DEFAULT, "error": str(exc)},
        )


@app.get("/info", response_model=BackendInfo)
async def info() -> BackendInfo:
    src_dir     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai4bharat_src")
    src_present = os.path.isdir(src_dir)
    a4b_loaded  = _ai4bharat_reader is not None

    if a4b_loaded:
        a4b_status = "LOADED — OneFourthLabs/Indic-OCR (CRAFT+EasyOCR), fully on-prem"
    elif src_present:
        a4b_status = (
            "READY_TO_LOAD — source tree present, will load on first request. "
            "Ensure: pip install -r apps/indic_ocr/ai4bharat_src/dependencies.txt"
        )
    else:
        a4b_status = (
            "NOT_INSTALLED — run: "
            f"git clone https://github.com/OneFourthLabs/Indic-OCR {src_dir} && "
            f"pip install -r {src_dir}/dependencies.txt  "
            "then set INDIC_OCR_BACKEND=ai4bharat. Falls back to paddle automatically."
        )

    return BackendInfo(
        service_default   = _SERVICE_DEFAULT,
        valid_backends    = sorted(_VALID_BACKENDS),
        supported_scripts = sorted(_SCRIPT_TO_PADDLE_LANG.keys()),
        loaded_paddle     = sorted(_paddle_ocr_pool.keys()),
        loaded_easyocr    = _easyocr_reader is not None,
        loaded_ai4bharat  = a4b_loaded,
        ai4bharat_status  = a4b_status,
    )


# ── OCR endpoints ─────────────────────────────────────────────────────────────

@app.post("/ocr", response_model=OcrResult)
async def ocr_image(
    file:    UploadFile = File(...),
    backend: Optional[str] = Query(
        default=None,
        description="Backend override: 'paddle', 'ai4bharat', or 'easyocr'.",
    ),
    script:  Optional[str] = Query(
        default=None,
        description=(
            "Indic script name from identify_indic_script(): "
            "devanagari | bengali | gurmukhi | gujarati | odia | "
            "tamil | telugu | kannada | malayalam. "
            "Selects the correct PaddleOCR language model. Defaults to devanagari."
        ),
    ),
) -> OcrResult:
    """Run Indic OCR on the entire uploaded image. Returns concatenated text."""
    b    = _resolve_backend(backend)
    lang = _resolve_paddle_lang(script)
    try:
        raw_bytes = await file.read()
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="Unreadable image.")

    arr   = np.array(img)
    pairs = _run_ocr(arr, b, script)

    if not pairs:
        return OcrResult(text="", confidence=0.0, backend=b, script=script, paddle_lang=lang)

    texts = [p[0] for p in pairs]
    confs = [p[1] for p in pairs]
    avg   = sum(confs) / len(confs)
    log.info("indic_ocr.full_ocr_done",
             backend=b, script=script, paddle_lang=lang,
             text_preview=" ".join(texts)[:80], confidence=round(avg, 4))
    return OcrResult(
        text=        " ".join(texts),
        confidence=  round(avg, 4),
        backend=     b,
        script=      script,
        paddle_lang= lang,
    )


@app.post("/ocr_zones", response_model=ZoneOcrResult)
async def ocr_zones(
    file:    UploadFile = File(...),
    backend: Optional[str] = Query(default=None),
    script:  Optional[str] = Query(
        default=None,
        description="Indic script name — applied to all zones.",
    ),
) -> ZoneOcrResult:
    """
    Crop CTS-2010 field zones from the full cheque image and run OCR on each.
    Returns: payee_name, amount_words, date, bank_name.
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
        pairs = _run_ocr(arr, b, script)

        if pairs:
            texts     = [p[0] for p in pairs]
            confs     = [p[1] for p in pairs]
            combined  = " ".join(texts)
            avg_conf  = sum(confs) / len(confs)
            field_text[field]  = combined
            raw_results[field] = [[t, round(c, 4)] for t, c in zip(texts, confs)]
            log.info("indic_ocr.zone_done", backend=b, script=script, field=field,
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
        script       = script,
        raw          = raw_results,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8021, log_level="info")
