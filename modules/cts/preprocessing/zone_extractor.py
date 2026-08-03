"""
CTS-2010 cheque zone extractor — field-level crop + script detection.

Splits a full cheque image into standard CTS-2010 field zones and classifies
each zone's script (Indic vs Latin) so the OCR activity can route:
  - ALWAYS_LATIN fields  → GOT-OCR2 via vLLM (cts-ocr queue)
  - SCRIPT_ADAPTIVE fields → detect script → IndicOCR if Indic, else GOT-OCR2

Used only in PARTIAL_IMAGE mode (ocr.mode = PARTIAL_IMAGE in config_service).
FULL_IMAGE mode bypasses this entirely — full cheque goes to GOT-OCR2 as before.

Zone coordinates are proportional (0.0–1.0) and calibrated against the
CTS-2010 standard landscape cheque layout (~3:1 aspect ratio).
"""
from __future__ import annotations

import base64
import io
from typing import Literal

from PIL import Image

# ── CTS-2010 field zone coordinates ───────────────────────────────────────────
# Format: (x1_frac, y1_frac, x2_frac, y2_frac) — top-left origin
# Calibrated against Syndicate Bank / Saraswat CTS-2010 cheque layout.

CTS_ZONES: dict[str, tuple[float, float, float, float]] = {
    # Calibrated against HDFC (Delhi), NKGSB (Pune) CTS-2010 cheques.
    # Designed to hold across private banks, PSBs, and UCBs — the three formats
    # vary ~5–8% vertically but the ranges below absorb that slack.
    #
    # Coordinate format: (x1, y1, x2, y2) — proportional, top-left origin.
    # All cheques tested: 1593–1606 × 741–745 px.
    "bank_name":      (0.00, 0.00, 0.60, 0.20),   # top-left: logo + branch address + IFSC
    "date":           (0.58, 0.00, 1.00, 0.22),   # top-right: date box (DD MM YYYY)
    "payee_name":     (0.04, 0.13, 0.78, 0.30),   # "Pay ___ Or Bearer" line
    "amount_words":   (0.04, 0.24, 0.80, 0.50),   # "Rupees ___ Only" — includes payee bleed-in
    "amount_figures": (0.57, 0.27, 0.99, 0.58),   # ₹ numeric box — right column, wide vertical
    "micr_band":      (0.00, 0.82, 1.00, 1.00),   # MICR E-13B strip — always bottom ~18%
}

# Fields whose content is always Latin-script numerics or dates.
# Skip Indic detection entirely — go straight to GOT-OCR2.
ALWAYS_LATIN: frozenset[str] = frozenset({
    "date",            # DD/MM/YYYY — always Latin
    "amount_figures",  # ₹ 2,25,5000/- — always Arabic numerals
    "micr_band",       # MICR E-13B font — always Latin
})

# Fields that may be written in an Indic script (regional language)
# e.g. payee "अभिलाष रेड्डी", amount words "बीस लाख पचास हजार"
SCRIPT_ADAPTIVE: frozenset[str] = frozenset({
    "payee_name",    # drawer may write in Devanagari, Gujarati, Tamil, etc.
    "amount_words",  # amount in words — frequently in regional script
    "bank_name",     # bank name may be printed in regional script
})

# ── Unicode ranges for Indic scripts ─────────────────────────────────────────
_INDIC_RANGES: tuple[tuple[str, str], ...] = (
    ('ऀ', 'ॿ'),   # Devanagari (Hindi, Marathi, Sanskrit, Nepali)
    ('ঀ', '৿'),   # Bengali
    ('਀', '੿'),   # Gurmukhi (Punjabi)
    ('઀', '૿'),   # Gujarati
    ('଀', '୿'),   # Oriya (Odia)
    ('஀', '௿'),   # Tamil
    ('ఀ', '౿'),   # Telugu
    ('ಀ', '೿'),   # Kannada
    ('ഀ', 'ൿ'),   # Malayalam
)


# ── Zone extraction ───────────────────────────────────────────────────────────

def extract_zone(img: Image.Image, field: str) -> Image.Image:
    """Crop the specified CTS-2010 field zone from a full cheque image."""
    if field not in CTS_ZONES:
        raise ValueError(
            f"Unknown CTS field '{field}'. Valid fields: {sorted(CTS_ZONES)}"
        )
    iw, ih = img.size
    x1f, y1f, x2f, y2f = CTS_ZONES[field]
    x1 = max(0,  int(x1f * iw))
    y1 = max(0,  int(y1f * ih))
    x2 = min(iw, int(x2f * iw))
    y2 = min(ih, int(y2f * ih))
    return img.crop((x1, y1, x2, y2))


def zone_to_data_uri(zone: Image.Image, fmt: str = "JPEG") -> str:
    """
    Encode a zone crop as a data URI suitable for vLLM image_url content.

    Returns: 'data:image/jpeg;base64,<payload>'
    """
    buf = io.BytesIO()
    zone.convert("RGB").save(buf, format=fmt, quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()
    mime = "image/jpeg" if fmt.upper() == "JPEG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64,{b64}"


# ── Script detection ──────────────────────────────────────────────────────────

def has_indic_script(text: str) -> bool:
    """Return True if text contains any Indic-script Unicode character."""
    return any(
        lo <= ch <= hi
        for ch in text
        for lo, hi in _INDIC_RANGES
    )


def has_devanagari(text: str) -> bool:
    """Return True if text contains Devanagari characters (Hindi, Marathi, etc.)."""
    lo, hi = 'ऀ', 'ॿ'
    return any(lo <= ch <= hi for ch in text)


def detect_script(text: str) -> Literal["indic", "latin", "unknown"]:
    """
    Classify the predominant script in OCR-extracted text.

      'indic'   — at least one Indic-script codepoint found
      'latin'   — non-empty, no Indic codepoints (Latin, numerics, punctuation)
      'unknown' — empty or whitespace-only

    Designed to work on the text output of a quick IndicOCR pass:
    if the text contains Devanagari (or any other Indic script), trust IndicOCR;
    otherwise fall back to GOT-OCR2 for Latin-script fields.
    """
    stripped = text.strip()
    if not stripped:
        return "unknown"
    if has_indic_script(stripped):
        return "indic"
    return "latin"
