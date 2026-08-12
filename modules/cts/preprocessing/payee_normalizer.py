"""Payee name normalizer for CTS inward cheque processing.

Handles the core India reality:
  - Cheque: "श्रीमती लता देशपांडे"  (handwritten, Devanagari, with salutation)
  - CBS:    "Lata Deshpande"         (English, no salutation)

Three-stage pipeline:
  1. strip_salutation   — remove cultural honorifics (Hindi/Marathi/Tamil/Telugu + English)
  2. transliterate      — Devanagari → Latin (character-level, schwa retained for safety)
  3. fuzzy match        — Jaro-Winkler; threshold from config_service caller

Scripts without a transliterator return UNDECIDABLE so the cheque routes to
human review rather than a false mismatch.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

# ─────────────────────────────────────────────────────────────────────────────
#  Salutations
# ─────────────────────────────────────────────────────────────────────────────

# Stored lowercased after stripping trailing '.' so matching is simple.
_SALUTATIONS_NORMALISED: frozenset[str] = frozenset({
    # Hindi / Marathi / Sanskrit
    "श्रीमती", "श्री", "डॉ", "कु", "कुमारी", "सौ", "ड़ॉ", "मा", "आदरणीय",
    # Tamil
    "திருமதி", "திரு", "செல்வி", "செல்வன்",
    # Telugu
    "శ్రీమతి", "శ్రీ",
    # Kannada
    "ಶ್ರೀಮತಿ", "ಶ್ರೀ",
    # Malayalam
    "ശ്രീമതി", "ശ്രീ",
    # Gujarati
    "શ્રીમતી", "શ્રી",
    # Bengali
    "শ্রীমতী", "শ্রী",
    # Gurmukhi (Punjabi)
    "ਸ਼੍ਰੀਮਤੀ", "ਸ਼੍ਰੀ",
    # Odia
    "ଶ୍ରୀମତୀ", "ଶ୍ରୀ",
    # English (lowercased, dot stripped)
    "smt", "shri", "dr", "mr", "mrs", "ms", "prof", "rev", "col", "adv",
    "capt", "lt", "cdr", "brig", "gen", "maj",
})


def strip_salutation(text: str) -> str:
    """Remove leading Indic or English salutation token(s) from a payee name.

    Only the FIRST token is checked — 'Shridhar' in 'Lata Shridhar Deshpande'
    must NOT be removed.
    """
    if not text:
        return ""
    tokens = text.split()
    # Strip consecutive leading salutation tokens (rare but "Dr. Smt." can occur)
    start = 0
    for tok in tokens:
        normalised = tok.rstrip(".").lower()
        # Also try without trailing punctuation in unicode (handles full-stop variants)
        normalised_unicode = normalised.rstrip(".")
        if normalised_unicode in _SALUTATIONS_NORMALISED or normalised in _SALUTATIONS_NORMALISED:
            start += 1
        else:
            break
    return " ".join(tokens[start:])


# ─────────────────────────────────────────────────────────────────────────────
#  Devanagari → Latin transliteration
# ─────────────────────────────────────────────────────────────────────────────

# Consonant → Latin (without inherent vowel — algorithm handles that)
_DEVA_CONSONANTS: dict[str, str] = {
    "क": "k",  "ख": "kh", "ग": "g",  "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh","ज": "j",  "झ": "jh", "ञ": "n",
    "ट": "t",  "ठ": "th", "ड": "d",  "ढ": "dh", "ण": "n",
    "त": "t",  "थ": "th", "द": "d",  "ध": "dh", "न": "n",
    "प": "p",  "फ": "ph", "ब": "b",  "भ": "bh", "म": "m",
    "य": "y",  "र": "r",  "ल": "l",  "व": "v",
    "श": "sh", "ष": "sh", "स": "s",  "ह": "h",
    "ळ": "l",  "क्ष": "ksh", "त्र": "tr", "ज्ञ": "gn",
    # Nukta forms (borrowed sounds)
    "ड़": "r",  "ढ़": "rh", "ऱ": "r",
    "क़": "q",  "ख़": "kh", "ग़": "g",
    "ज़": "z",  "फ़": "f",  "य़": "y",
}

# Vowel signs (matras) — replace the inherent 'a' of the preceding consonant
_DEVA_MATRAS: dict[str, str] = {
    "ा": "a",  # ā → simplified 'a'
    "ि": "i",
    "ी": "i",  # ī → 'i'
    "ु": "u",
    "ू": "u",  # ū → 'u'
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "o",  # au → 'o' (CBS usually uses 'o')
    "ृ": "ri",
    "ॅ": "e",
    "ॆ": "e",
    "ॊ": "o",
}

# Standalone vowels (at word start or after another vowel)
_DEVA_STANDALONE: dict[str, str] = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i",
    "उ": "u", "ऊ": "u", "ए": "e", "ऐ": "ai",
    "ओ": "o", "औ": "o", "ऋ": "ri",
}

# Devanagari digits → ASCII
_DEVA_DIGITS: dict[str, str] = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

_HALANT     = "्"  # ् — virama / halant (kills inherent vowel)
_ANUSVARA   = "ं"  # ं
_CHANDRABINDU = "ँ"  # ँ
_VISARGA    = "ः"  # ः
_NUKTA      = "़"  # ़

_DEVA_RANGE = ("ऀ", "ॿ")  # Devanagari Unicode block


def _is_deva(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def transliterate_devanagari(text: str) -> str:
    """Convert Devanagari text to a simplified Latin approximation for name matching.

    Algorithm:
    - Each Devanagari consonant carries an inherent 'a' vowel.
    - A matra (vowel sign) following a consonant REPLACES the inherent 'a'.
    - A halant (्) following a consonant SUPPRESSES the inherent 'a'.
    - Anusvara (ं) → 'n'.
    - Non-Devanagari characters (spaces, ASCII) pass through unchanged.
    """
    out: list[str] = []
    i = 0
    chars = list(text)
    n = len(chars)

    while i < n:
        ch = chars[i]

        # Digits
        if ch in _DEVA_DIGITS:
            out.append(_DEVA_DIGITS[ch])
            i += 1
            continue

        # Non-Devanagari (spaces, ASCII letters, punctuation) — pass through
        if not _is_deva(ch):
            out.append(ch)
            i += 1
            continue

        # Standalone vowels
        if ch in _DEVA_STANDALONE:
            out.append(_DEVA_STANDALONE[ch])
            i += 1
            continue

        # Anusvara / chandrabindu → 'n'
        if ch in (_ANUSVARA, _CHANDRABINDU):
            out.append("n")
            i += 1
            continue

        # Visarga → omit (mostly silent at end of Sanskrit-origin names)
        if ch == _VISARGA:
            i += 1
            continue

        # Nukta alone (combining) — consumed as part of consonant look-up already
        if ch == _NUKTA:
            i += 1
            continue

        # Consonant (possibly with nukta as next char)
        if ch in _DEVA_CONSONANTS:
            # Check for nukta modifier (forms like ड़, ज़)
            nukta_form = ch + _NUKTA if (i + 1 < n and chars[i + 1] == _NUKTA) else None
            if nukta_form and nukta_form in _DEVA_CONSONANTS:
                cons_latin = _DEVA_CONSONANTS[nukta_form]
                i += 2  # skip consonant + nukta
            else:
                cons_latin = _DEVA_CONSONANTS[ch]
                i += 1

            out.append(cons_latin)

            # Peek at next character
            if i < n:
                nxt = chars[i]
                if nxt == _HALANT:
                    # Halant: suppress inherent 'a', consume halant
                    i += 1
                elif nxt in _DEVA_MATRAS:
                    # Matra: emit vowel in place of inherent 'a'
                    out.append(_DEVA_MATRAS[nxt])
                    i += 1
                elif nxt in (_ANUSVARA, _CHANDRABINDU):
                    # Anusvara follows consonant — inherent 'a' is present then nasal
                    out.append("a")
                    # anusvara itself will be picked up in the next iteration
                else:
                    # Next char is another consonant / space / non-deva → emit inherent 'a'
                    out.append("a")
            else:
                # End of string after consonant → emit inherent 'a'
                out.append("a")
            continue

        # Matra appearing without a preceding consonant (shouldn't happen, but guard)
        if ch in _DEVA_MATRAS:
            out.append(_DEVA_MATRAS[ch])
            i += 1
            continue

        # Halant orphan
        if ch == _HALANT:
            i += 1
            continue

        # Fallback: unknown Devanagari char — skip
        i += 1

    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
#  Scripts with transliterator support
# ─────────────────────────────────────────────────────────────────────────────

# Only Devanagari has a built-in transliterator.
# Other scripts return UNDECIDABLE → human review (safe default).
_TRANSLITERABLE_SCRIPTS: frozenset[str] = frozenset({"devanagari"})


# ─────────────────────────────────────────────────────────────────────────────
#  String normalisation
# ─────────────────────────────────────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[.,;:\-_/'\"()\[\]{}]")


def _normalize(text: str) -> str:
    """Lowercase, strip salutation, remove punctuation, collapse whitespace."""
    text = strip_salutation(text)
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = " ".join(text.split())
    return text


def _is_indic(text: str) -> bool:
    """Return True if text contains any Indic script codepoints."""
    for ch in text:
        cp = ord(ch)
        # Devanagari: 0x0900–0x097F + extended
        # Bengali: 0x0980–0x09FF
        # Gurmukhi: 0x0A00–0x0A7F
        # Gujarati: 0x0A80–0x0AFF
        # Odia: 0x0B00–0x0B7F
        # Tamil: 0x0B80–0x0BFF
        # Telugu: 0x0C00–0x0C7F
        # Kannada: 0x0C80–0x0CFF
        # Malayalam: 0x0D00–0x0D7F
        if 0x0900 <= cp <= 0x0D7F:
            return True
    return False


def _detect_script(text: str) -> str | None:
    """Return the dominant Indic script name, or None if no Indic characters."""
    from modules.cts.preprocessing.zone_extractor import identify_indic_script
    return identify_indic_script(text)


# ─────────────────────────────────────────────────────────────────────────────
#  Jaro-Winkler (stdlib-only, no external deps)
# ─────────────────────────────────────────────────────────────────────────────

def _jaro(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if l1 == 0 or l2 == 0:
        return 0.0
    match_dist = max(l1, l2) // 2 - 1
    s1m = [False] * l1
    s2m = [False] * l2
    matches = 0
    for i in range(l1):
        lo = max(0, i - match_dist)
        hi = min(i + match_dist + 1, l2)
        for j in range(lo, hi):
            if s2m[j] or s1[i] != s2[j]:
                continue
            s1m[i] = s2m[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    transpositions = 0
    k = 0
    for i in range(l1):
        if not s1m[i]:
            continue
        while not s2m[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    return (matches / l1 + matches / l2 + (matches - transpositions / 2) / matches) / 3


def _jaro_winkler(s1: str, s2: str, p: float = 0.1) -> float:
    """Standard Jaro-Winkler similarity, p = prefix scaling factor (default 0.1)."""
    j = _jaro(s1, s2)
    prefix = 0
    for c1, c2 in zip(s1, s2):
        if c1 != c2:
            break
        prefix += 1
        if prefix == 4:
            break
    return j + prefix * p * (1 - j)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

Decision = Literal["MATCH", "FUZZY", "MISMATCH", "UNDECIDABLE"]


@dataclass(frozen=True)
class PayeeMatchResult:
    decision: Decision
    score: float | None       # None when UNDECIDABLE
    normalized_ocr: str
    normalized_cbs: str


def payee_names_match(
    ocr_name: str,
    cbs_name: str,
    threshold: float,
    script: str | None = None,
) -> PayeeMatchResult:
    """Compare a cheque payee name (possibly Indic) against a CBS-stored name (English).

    Args:
        ocr_name:  Raw payee name as extracted by OCR — may contain salutation,
                   may be in an Indic script.
        cbs_name:  Account holder name from CBS — typically English.
        threshold: Jaro-Winkler score above which we accept as MATCH.
                   Below threshold - 0.10 = MISMATCH.
                   In between = FUZZY (route to human review with score shown).
                   Caller must source this from config_service.
        script:    Indic script detected from OCR text (e.g. "devanagari").
                   If None, auto-detected from ocr_name.

    Returns:
        PayeeMatchResult with decision ∈ {MATCH, FUZZY, MISMATCH, UNDECIDABLE}.
        UNDECIDABLE means the script has no transliterator — safe default is
        human review, NOT automatic return.
    """
    # Determine script if not provided
    if script is None and _is_indic(ocr_name):
        script = _detect_script(ocr_name)

    # If the OCR text is in an Indic script we can't transliterate → UNDECIDABLE
    if script is not None and script not in _TRANSLITERABLE_SCRIPTS and _is_indic(ocr_name):
        norm_cbs = _normalize(cbs_name)
        return PayeeMatchResult(
            decision="UNDECIDABLE",
            score=None,
            normalized_ocr=ocr_name,   # can't normalize without transliterator
            normalized_cbs=norm_cbs,
        )

    # For Devanagari: strip Indic salutation FIRST, then transliterate.
    # If we transliterate before stripping, "श्रीमती" becomes "shrimati"
    # which is not in the salutation set and would corrupt the fuzzy score.
    ocr_work = ocr_name
    if script == "devanagari" and _is_indic(ocr_name):
        ocr_work = strip_salutation(ocr_name)
        ocr_work = transliterate_devanagari(ocr_work)

    norm_ocr = _normalize(ocr_work)
    norm_cbs = _normalize(cbs_name)

    score = _jaro_winkler(norm_ocr, norm_cbs)

    if score >= threshold:
        decision: Decision = "MATCH"
    elif score >= threshold - 0.10:
        decision = "FUZZY"
    else:
        decision = "MISMATCH"

    return PayeeMatchResult(
        decision=decision,
        score=round(score, 4),
        normalized_ocr=norm_ocr,
        normalized_cbs=norm_cbs,
    )
