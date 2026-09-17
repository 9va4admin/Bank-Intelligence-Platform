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
import sys
from typing import Any, Optional

# Windows' default console codepage (cp1252) can't encode Devanagari/other
# Indic Unicode output — without this, every successful non-Latin OCR result
# crashes the request with UnicodeEncodeError the moment it's logged, even
# though the OCR call itself succeeded. Must run before structlog's first
# log call. errors="replace" so a genuinely unencodable byte still logs
# something rather than reintroducing the crash.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # PaddleOCR's import chain (paddleocr -> paddlex -> modelscope -> torch)
    # loads torch AFTER paddle's own native DLLs are already on the process —
    # on Windows this breaks torch's own DLL loading with
    # "OSError: [WinError 127] The specified procedure could not be found"
    # on torch/lib/shm.dll, even though `import torch` alone works fine.
    # Importing torch here, before anything paddle-related, forces the
    # working DLL load order. Confirmed: fails without this, works with it.
    try:
        import torch  # noqa: F401
    except ImportError:
        pass

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

_SERVICE_DEFAULT: str = BACKEND_PADDLE  # overridden in startup from config_service

# ── Script → PaddleOCR lang code mapping ─────────────────────────────────────
# Keys match the script names returned by identify_indic_script() in zone_extractor.py.
#
# IMPORTANT: these are NOT ISO 639-1 codes. paddleocr==2.7.3's actual
# recognition MODEL_URLS (apps/indic_ocr/.venv/Lib/site-packages/paddleocr/
# paddleocr.py) only ships models for: ch, en, korean, japan, chinese_cht,
# ta, te, ka, latin, arabic, cyrillic, devanagari. Confirmed by hitting the
# real "param lang must in dict_keys([...])" error from paddleocr itself.
#
# Two of the four Indic-relevant codes below were WRONG prior to 2026-09-17:
#   devanagari was "hi"  -- not a valid paddleocr key; must be "devanagari" itself.
#   kannada    was "kn"  -- not a valid paddleocr key; must be "ka".
# Both failures were silent: _run_ocr's cascade caught the paddle error and
# fell through to EasyOCR with the WRONG language pack (hardcoded "hi"),
# producing near-zero-confidence garbage instead of a loud failure.
#
# bengali/gurmukhi/gujarati/odia/malayalam have NO working paddleocr 2.7.3
# model at all -- not a code bug, a genuine gap in this library version.
# "malayalam": "ml" was an especially dangerous false friend: "ml" IS a
# valid paddleocr key, but it means the generic "Multilingual" detector,
# not Malayalam -- it would have silently run the wrong model with no
# error at all. Mapped to None below so these route to the ai4bharat/
# easyocr cascade instead of a misleading paddle "success".
_SCRIPT_TO_PADDLE_LANG: dict[str, Optional[str]] = {
    "latin":      "en",   # English/Latin — printed boilerplate text (signature-crop cleanup, etc.)
    "devanagari": "devanagari",   # Hindi, Marathi, Sanskrit
    "bengali":    None,    # no paddleocr 2.7.3 model — falls through to ai4bharat/easyocr
    "gurmukhi":   None,    # Punjabi — no paddleocr 2.7.3 model
    "gujarati":   None,    # no paddleocr 2.7.3 model
    "odia":       None,    # Oriya — no paddleocr 2.7.3 model
    "tamil":      "ta",
    "telugu":     "te",
    "kannada":    "ka",
    "malayalam":  None,    # "ml" is paddleocr's Multilingual detector, NOT Malayalam — do not map here
}

_DEFAULT_PADDLE_LANG = "devanagari"   # fallback when script is unknown or absent -- "hi" is NOT a valid paddleocr key

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
            # paddleocr==2.7.3's transitive dependency `imgaug` reads
            # np.sctypes, which NumPy 2.0 removed outright. Restore it as a
            # shim scoped to this process only — the shared numpy install
            # (used by torch/ultralytics/the whole API) is never downgraded.
            # https://numpy.org/doc/stable/numpy_2_0_migration_guide.html
            if not hasattr(np, "sctypes"):
                np.sctypes = {
                    "int":     [np.int8, np.int16, np.int32, np.int64],
                    "uint":    [np.uint8, np.uint16, np.uint32, np.uint64],
                    "float":   [np.float16, np.float32, np.float64, np.longdouble],
                    "complex": [np.complex64, np.complex128, np.clongdouble],
                    "others":  [bool, object, bytes, str, np.void],
                }
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


def _resolve_paddle_lang(script: Optional[str]) -> Optional[str]:
    """
    Map a script name (from identify_indic_script()) to a PaddleOCR lang code.
    Returns None when the script has no paddleocr 2.7.3 model at all
    (bengali/gurmukhi/gujarati/odia/malayalam) -- the caller must treat that
    as "paddle can't serve this" and let it cascade to easyocr/ai4bharat,
    never silently force an unrelated script's model onto it.
    """
    if not script:
        return _DEFAULT_PADDLE_LANG
    return _SCRIPT_TO_PADDLE_LANG.get(script.lower(), _DEFAULT_PADDLE_LANG)


def _run_paddle_lang(arr: np.ndarray, lang: str) -> list[tuple[str, float]]:
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


def _paddle_score(pairs: list[tuple[str, float]]) -> float:
    # confidence weighted by recognized length — rewards a model that reads
    # more text at decent confidence over one that returns a single
    # high-confidence noise token from forcing the wrong script's glyphs
    # through its recognizer (which is exactly what happens when the wrong
    # PaddleOCR language model is applied — it still returns *a* confidence
    # score, just a meaningless one, so confidence alone is not enough).
    return sum(conf * len(text) for text, conf in pairs)


def _run_paddle_auto(arr: np.ndarray) -> tuple[list[tuple[str, float]], str]:
    """
    Try every supported PaddleOCR language model against this zone crop and
    keep whichever scores best (see _paddle_score). This is the fix for a
    real failure mode: a caller (or an upstream cloud VLM) guessing the wrong
    script confidently — asking PaddleOCR to run in a caller-guessed-wrong
    language reproduces the same error in a different engine. Trying every
    script and scoring the actual OCR output is the only way to find the
    real script without trusting a guess that has already been shown wrong.

    Returns ([(text, confidence)], winning_lang_code).
    """
    best_pairs: list[tuple[str, float]] = []
    best_lang = _DEFAULT_PADDLE_LANG
    best_score = -1.0
    for lang in sorted({v for v in _SCRIPT_TO_PADDLE_LANG.values() if v is not None}):
        try:
            pairs = _run_paddle_lang(arr, lang)
        except Exception as exc:
            log.warning("indic_ocr.auto_script_lang_failed", lang=lang, error=str(exc))
            continue
        score = _paddle_score(pairs)
        if score > best_score:
            best_score, best_pairs, best_lang = score, pairs, lang
    log.info("indic_ocr.auto_script_selected", lang=best_lang, score=round(best_score, 2))
    return best_pairs, best_lang


def _run_paddle(arr: np.ndarray, script: Optional[str]) -> tuple[list[tuple[str, float]], str]:
    """Returns ([(text, confidence)], resolved_paddle_lang_code)."""
    if script and script.lower() == "auto":
        return _run_paddle_auto(arr)
    lang = _resolve_paddle_lang(script)
    if lang is None:
        raise RuntimeError(
            f"No paddleocr 2.7.3 model for script '{script}' — "
            f"cascade to easyocr/ai4bharat."
        )
    return _run_paddle_lang(arr, lang), lang


def _run_easyocr(arr: np.ndarray) -> list[tuple[str, float]]:
    reader = _get_easyocr_reader()
    raw    = reader.readtext(arr, detail=1) or []
    return [(r[1], float(r[2])) for r in raw if r[1]]


def _run_ai4bharat(arr: np.ndarray) -> list[tuple[str, float]]:
    reader = _get_ai4bharat_reader()
    bboxes = reader.run(arr) or []
    return [
        (b["text"], float(b.get("confidence", 0.0)))
        for b in bboxes
        if b.get("text")
    ]


# Cascade order: PaddleOCR (best script coverage — 9 Indic langs) → EasyOCR
# (Hindi-only, different engine/weights so it survives a Paddle-specific
# failure) → AI4Bharat (Hindi-only, needs manual source-tree setup).
# The caller's requested backend is tried FIRST (respecting an explicit
# ?backend= override or INDIC_OCR_BACKEND), then the remaining backends are
# tried in cascade order — so one backend's outage never means the request
# silently comes back empty, it means it was answered by degrade-quality
# engine and callers can inspect the "backend" field returned to know which
# one actually served it.
_CASCADE_ORDER = [BACKEND_PADDLE, BACKEND_EASYOCR, BACKEND_AI4BHARAT]


def _run_ocr(
    arr: np.ndarray, backend: str, script: Optional[str] = None
) -> tuple[list[tuple[str, float]], str, Optional[str]]:
    """
    Run OCR on a (H, W, 3) uint8 numpy array, cascading across backends on failure.

    Returns ([(text, confidence)], backend_actually_used, resolved_paddle_lang).
    resolved_paddle_lang is the actual PaddleOCR language code used — most
    useful with script="auto", where it reports which script actually won
    the confidence contest; it's None for the easyocr/ai4bharat backends
    (they're single-language, nothing to resolve). Raises RuntimeError only
    when every backend in the cascade has failed, with all individual errors
    attached so the real cause is never swallowed into a silent blank.

    script: Indic script name from identify_indic_script(), or "auto" to try
            every supported PaddleOCR language and keep the best-scoring one
            (see _run_paddle_auto) — used to select the PaddleOCR language
            model. Ignored for easyocr/ai4bharat.
    """
    order = [backend] + [b for b in _CASCADE_ORDER if b != backend]
    errors: list[str] = []

    for candidate in order:
        try:
            if candidate == BACKEND_PADDLE:
                pairs, resolved_lang = _run_paddle(arr, script)
                return pairs, BACKEND_PADDLE, resolved_lang
            elif candidate == BACKEND_EASYOCR:
                return _run_easyocr(arr), BACKEND_EASYOCR, None
            else:
                return _run_ai4bharat(arr), BACKEND_AI4BHARAT, None
        except NotImplementedError as exc:
            log.warning("indic_ocr.backend_not_ready", backend=candidate, error=str(exc))
            errors.append(f"{candidate}: {exc}")
        except Exception as exc:
            log.warning("indic_ocr.backend_failed_cascading", backend=candidate, error=str(exc))
            errors.append(f"{candidate}: {exc}")

    raise RuntimeError(
        "All IndicOCR backends failed:\n" + "\n".join(errors)
    )


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="ASTRA IndicOCR",
    description=(
        "Multi-script Indic OCR for Indian cheque field zones. "
        "Pass ?script=<script_name> for script-aware PaddleOCR language selection. "
        "Scripts: devanagari, bengali, gurmukhi, gujarati, odia, tamil, telugu, kannada, malayalam."
    ),
    version="3.0.0",
    docs_url=None,
    redoc_url=None,
)


@app.on_event("startup")
async def _startup() -> None:
    global _SERVICE_DEFAULT
    try:
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
        from shared.config.config_service import config_service
        backend = str(await config_service.get("indic_ocr.backend")).lower()
        if backend in _VALID_BACKENDS:
            _SERVICE_DEFAULT = backend
        else:
            log.warning("indic_ocr.invalid_backend_config", value=backend, fallback=BACKEND_PADDLE)
    except Exception:
        pass


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

    arr = np.array(img)
    try:
        pairs, used_backend, resolved_lang = _run_ocr(arr, b, script)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    lang = resolved_lang or lang

    if not pairs:
        return OcrResult(text="", confidence=0.0, backend=used_backend, script=script, paddle_lang=lang)

    texts = [p[0] for p in pairs]
    confs = [p[1] for p in pairs]
    avg   = sum(confs) / len(confs)
    log.info("indic_ocr.full_ocr_done",
             requested_backend=b, backend=used_backend, script=script, paddle_lang=lang,
             text_preview=" ".join(texts)[:80], confidence=round(avg, 4))
    return OcrResult(
        text=        " ".join(texts),
        confidence=  round(avg, 4),
        backend=     used_backend,
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
    used_backend = b   # updated to whichever backend actually served a zone
    resolved_script = script   # updated when script="auto" resolves to a real lang

    for field, (x1f, y1f, x2f, y2f) in _CTS_ZONES.items():
        x1 = max(0,  int(x1f * iw))
        y1 = max(0,  int(y1f * ih))
        x2 = min(iw, int(x2f * iw))
        y2 = min(ih, int(y2f * ih))
        if x2 <= x1 or y2 <= y1:
            field_text[field]  = None
            raw_results[field] = []
            continue

        zone = img.crop((x1, y1, x2, y2))
        arr  = np.array(zone)
        try:
            pairs, used_backend, field_resolved_lang = _run_ocr(arr, b, script)
        except RuntimeError as exc:
            log.error("indic_ocr.zone_all_backends_failed", field=field, error=str(exc))
            field_text[field]  = None
            raw_results[field] = []
            continue

        if pairs:
            # payee_name/amount_words are the fields this endpoint's callers
            # actually care about the script of (bank_name/date are often
            # numeric/Latin regardless of the cheque's handwriting script),
            # so let their auto-resolved language be the one reported back.
            if field_resolved_lang and field in ("payee_name", "amount_words"):
                resolved_script = field_resolved_lang
            texts     = [p[0] for p in pairs]
            confs     = [p[1] for p in pairs]
            combined  = " ".join(texts)
            avg_conf  = sum(confs) / len(confs)
            field_text[field]  = combined
            raw_results[field] = [[t, round(c, 4)] for t, c in zip(texts, confs)]
            log.info("indic_ocr.zone_done", requested_backend=b, backend=used_backend,
                     script=script, resolved_lang=field_resolved_lang, field=field,
                     text=combined[:80], conf=round(avg_conf, 4))
        else:
            field_text[field]  = None
            raw_results[field] = []

    return ZoneOcrResult(
        bank_name    = field_text.get("bank_name"),
        date         = field_text.get("date"),
        payee_name   = field_text.get("payee_name"),
        amount_words = field_text.get("amount_words"),
        backend      = used_backend,
        script       = resolved_script,
        raw          = raw_results,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8021, log_level="info")
