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
    ("thousand", 1_000),
    ("hundred", 100),
]
_NOISE_PATTERNS = re.compile(
    r"\b(rupees?|rs\.?|only|paisa|paise|and|/-)\b", re.IGNORECASE
)


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
        fig_value = float(figures.replace(",", ""))
    except (ValueError, AttributeError):
        return None

    word_value = parse_amount_words(words)
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
            and token not in {"hundred", "thousand", "lakh", "lakhs", "lac", "crore", "crores"}
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
        elif token in ("lakh", "lakhs", "lac"):
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
