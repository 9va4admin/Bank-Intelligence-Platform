"""
Indian currency amount-words parser for CTS cheque cross-check.

Converts written-out Indian English amount text to a numeric float.
Used to compare amount_in_words against amount_in_figures extracted by OCR.

Supports: units through Crores (Indian denomination system).
Tolerant of: "Rupees"/"Rs." prefix, "Only"/"/-" suffix, case variations, extra spaces.

Returns None on unparseable input — never raises.
"""
from __future__ import annotations

import re
from typing import Optional

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
# Indian scale words (descending magnitude order for parsing)
_SCALES = [
    ("crore", 10_000_000),
    ("crores", 10_000_000),
    ("lakh", 100_000),
    ("lakhs", 100_000),
    ("lac", 100_000),
    ("lacs", 100_000),   # plural variant used on many printed cheque forms
    ("thousand", 1_000),
    ("hundred", 100),
]

# ── Devanagari digit normalisation ───────────────────────────────────────────

_DEVANAGARI_DIGIT_MAP = str.maketrans("०१२३४५६७८९", "0123456789")


def normalize_devanagari_digits(text: str) -> str:
    """Convert Devanagari digits (०–९) to ASCII digits (0–9)."""
    return text.translate(_DEVANAGARI_DIGIT_MAP)


# ── Hindi / Marathi (Devanagari script) number word tables ───────────────────
# Covers Hindi and Marathi — both use Devanagari. Where words differ the
# Marathi variant is listed alongside the Hindi one.

_HINDI_ONES: dict[str, int] = {
    # 1–9
    "एक": 1,
    "दो": 2, "दोन": 2,                    # दोन = Marathi
    "तीन": 3,
    "चार": 4,
    "पाँच": 5, "पांच": 5, "पाच": 5,       # पाच = Marathi
    "छह": 6, "छः": 6, "सहा": 6,           # सहा = Marathi
    "सात": 7,
    "आठ": 8,
    "नौ": 9, "नऊ": 9,                      # नऊ = Marathi
    # 10–19
    "दस": 10, "दहा": 10,
    "ग्यारह": 11, "अकरा": 11,
    "बारह": 12, "बारा": 12,
    "तेरह": 13, "तेरा": 13,
    "चौदह": 14, "चौदा": 14,
    "पंद्रह": 15, "पंधरा": 15,
    "सोलह": 16, "सोळा": 16,
    "सत्रह": 17, "सतरा": 17,
    "अठारह": 18, "अठरा": 18,
    "उन्नीस": 19, "एकोणीस": 19,
    # 20–29
    "बीस": 20, "वीस": 20,
    "इक्कीस": 21, "एकवीस": 21,
    "बाईस": 22, "बावीस": 22,
    "तेईस": 23, "तेवीस": 23,
    "चौबीस": 24, "चोवीस": 24,
    "पच्चीस": 25, "पंचवीस": 25,
    "छब्बीस": 26, "सव्वीस": 26,
    "सत्ताईस": 27, "सत्तावीस": 27,
    "अट्ठाईस": 28, "अठ्ठावीस": 28,
    "उनतीस": 29, "एकोणतीस": 29,
    # 30–39
    "तीस": 30,
    "इकतीस": 31, "एकतीस": 31,
    "बत्तीस": 32,
    "तैंतीस": 33, "तेहतीस": 33,
    "चौंतीस": 34,
    "पैंतीस": 35,
    "छत्तीस": 36,
    "सैंतीस": 37,
    "अड़तीस": 38,
    "उनतालीस": 39,
    # 40–49
    "चालीस": 40, "चाळीस": 40,
    "इकतालीस": 41,
    "बयालीस": 42,
    "तैंतालीस": 43,
    "चौंतालीस": 44,
    "पैंतालीस": 45,
    "छियालीस": 46,
    "सैंतालीस": 47,
    "अड़तालीस": 48,
    "उनचास": 49,
    # 50–59
    "पचास": 50, "पन्नास": 50,
    "इक्यावन": 51, "एकावन": 51,
    "बावन": 52,
    "तिरपन": 53, "त्रेपन्न": 53,
    "चौवन": 54,
    "पचपन": 55,
    "छप्पन": 56,
    "सत्तावन": 57,
    "अट्ठावन": 58,
    "उनसठ": 59,
    # 60–69
    "साठ": 60,
    "इकसठ": 61,
    "बासठ": 62,
    "तिरसठ": 63,
    "चौंसठ": 64,
    "पैंसठ": 65,
    "छियासठ": 66,
    "सड़सठ": 67,
    "अड़सठ": 68,
    "उनहत्तर": 69,
    # 70–79
    "सत्तर": 70,
    "इकहत्तर": 71,
    "बहत्तर": 72,
    "तिहत्तर": 73,
    "चौहत्तर": 74,
    "पचहत्तर": 75,
    "छिहत्तर": 76,
    "सतहत्तर": 77,
    "अठहत्तर": 78,
    "उन्यासी": 79,
    # 80–89
    "अस्सी": 80, "ऐंशी": 80,
    "इक्यासी": 81,
    "बयासी": 82,
    "तिरासी": 83,
    "चौरासी": 84,
    "पचासी": 85,
    "छियासी": 86,
    "सत्तासी": 87,
    "अट्ठासी": 88,
    "नवासी": 89,
    # 90–99
    "नब्बे": 90, "नव्वद": 90,
    "इक्यानवे": 91,
    "बानवे": 92,
    "तिरानवे": 93,
    "चौरानवे": 94,
    "पचानवे": 95,
    "छियानवे": 96,
    "सत्तानवे": 97,
    "अट्ठानवे": 98,
    "निन्यानवे": 99,
}

_HINDI_SCALES: dict[str, int] = {
    "सौ": 100, "सो": 100, "शंभर": 100, "शे": 100,
    "हजार": 1_000,
    "लाख": 100_000, "लाखों": 100_000,
    "करोड़": 10_000_000, "करोड": 10_000_000,
    "कोटी": 10_000_000, "कोटि": 10_000_000,
}

# Token-based noise filter — \b word-boundary does not work reliably with
# Devanagari in Python's re module, so we filter by token equality after split.
_HINDI_NOISE_TOKENS: frozenset[str] = frozenset({
    "रुपये", "रुपया", "रुपए", "रु", "रु.",
    "मात्र", "केवल", "और", "पैसे", "पैसा", "सिर्फ", "तथा",
})


def parse_hindi_amount_words(text: str | None) -> float | None:
    """
    Parse Hindi/Marathi (Devanagari) amount-in-words to float.

    Handles: रुपये/मात्र noise, Devanagari digits (२५ हजार → 25000),
    Arabic numerals mixed with Hindi scale words (5 लाख → 500000).
    Returns None on unparseable input — never raises.
    """
    if not text:
        return None
    try:
        return _parse_hindi(text)
    except Exception:
        return None


def _parse_hindi(text: str) -> float | None:
    text = normalize_devanagari_digits(text)
    tokens = [t for t in text.split() if t not in _HINDI_NOISE_TOKENS]
    if not tokens:
        return None

    total = 0
    current = 0

    for token in tokens:
        if token in _HINDI_ONES:
            current += _HINDI_ONES[token]
        elif token in _HINDI_SCALES:
            scale = _HINDI_SCALES[token]
            if scale == 100:
                # "सौ" multiplies the preceding segment: पाँच सौ = 500
                current = (current or 1) * 100
            else:
                total += (current or 1) * scale
                current = 0
        elif token.isdigit():
            # Arabic numeral mixed in (e.g. "25 हजार")
            current += int(token)
        else:
            return None   # unknown token — cannot safely parse

    total += current
    return float(total) if total > 0 else None


_LAKH_TOKENS = frozenset({"lakh", "lakhs", "lac", "lacs"})
_NOISE_PATTERNS = re.compile(
    r"\b(rupees?|rs\.?|only|paisa|paise|and|/-)\b", re.IGNORECASE
)

# Prefix: ₹, Rs., Rs, INR — optionally followed by whitespace
_FIGURES_PREFIX = re.compile(r"^(₹|Rs\.?|INR)\s*", re.IGNORECASE)
# Suffix: any combination of /, -, –, —, = that terminates the amount
# Indian convention: drawer draws a line/stroke after amount to prevent alteration
_FIGURES_SUFFIX = re.compile(r"[/\-–—=]+$")


def _clean_figures(text: str) -> str:
    """
    Normalise the figures string from OCR before float conversion.

    Strips:
      - Leading whitespace and currency prefix (₹, Rs., INR)
      - Trailing tamper-prevention strokes (/, /-, /–, -, =, etc.)
      - Indian-style comma grouping (1,00,000 → 100000)
    """
    t = text.strip()
    t = _FIGURES_PREFIX.sub("", t)
    t = _FIGURES_SUFFIX.sub("", t)
    return t.replace(",", "").strip()


def parse_amount_words(text: Optional[str]) -> Optional[float]:
    """
    Parse Indian English amount words to a float.

    Returns None if the text cannot be parsed (unknown words, empty, None).
    Never raises.
    """
    if not text:
        return None
    try:
        return _parse(text)
    except Exception:
        return None


def amounts_match(
    figures: Optional[str],
    words: Optional[str],
    tolerance: float = 1.0,
) -> Optional[bool]:
    """
    Compare amount_in_figures (string) vs amount_in_words (string).

    Returns:
      True   — amounts match within tolerance
      False  — amounts differ beyond tolerance (SUSPICIOUS)
      None   — cannot determine (unparseable input — treat as unknown, not mismatch)
    """
    if figures is None or words is None:
        return None

    try:
        fig_value = float(_clean_figures(figures))
    except (ValueError, AttributeError):
        return None

    word_value = parse_amount_words(words)

    # English parser failed → try Hindi/Marathi (Devanagari script)
    if word_value is None:
        word_value = parse_hindi_amount_words(words)

    # Still None → unknown language/script — undecidable, not a mismatch
    if word_value is None:
        return None

    return abs(fig_value - word_value) <= tolerance


# ---------------------------------------------------------------------------
# Internal parser
# ---------------------------------------------------------------------------

def _parse(text: str) -> Optional[float]:
    cleaned = _NOISE_PATTERNS.sub(" ", text)
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", cleaned)
    cleaned = " ".join(cleaned.split()).lower()

    if not cleaned:
        return None

    tokens = cleaned.split()

    # Validate all tokens are known words
    for token in tokens:
        if (
            token not in _ONES
            and token not in _TENS
            and token not in {"hundred", "thousand", "crore", "crores"}
            and token not in _LAKH_TOKENS
        ):
            return None

    total = _parse_tokens(tokens)
    return float(total) if total is not None else None


def _parse_tokens(tokens: list[str]) -> Optional[int]:
    """
    Recursive descent parser for Indian number words.
    Handles: crore → lakh → thousand → hundred → tens/ones
    """
    # Build a flat token → value dict for a single pass
    result = 0
    current = 0   # accumulator for the current magnitude segment

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in _ONES:
            current += _ONES[token]
        elif token in _TENS:
            current += _TENS[token]
        elif token == "hundred":
            if current == 0:
                current = 1
            current *= 100
        elif token in ("thousand",):
            if current == 0:
                current = 1
            result += current * 1_000
            current = 0
        elif token in _LAKH_TOKENS:
            if current == 0:
                current = 1
            result += current * 100_000
            current = 0
        elif token in ("crore", "crores"):
            if current == 0:
                current = 1
            result += current * 10_000_000
            current = 0
        else:
            return None
        i += 1

    result += current
    return result if result > 0 else None
