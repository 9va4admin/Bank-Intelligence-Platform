"""Payee name normalizer for CTS inward and outward cheque processing.

Handles the core India reality:
  - Cheque: "श्रीमती लता देशपांडे"  (handwritten, Devanagari, with salutation)
  - CBS:    "Lata Deshpande"         (English, no salutation)

Three-stage pipeline:
  1. strip_salutation   — remove cultural honorifics (all 9 Indic scripts + English)
  2. transliterate      — Indic script → Latin (character-level, all 9 scripts)
  3. fuzzy match        — Jaro-Winkler; threshold from config_service caller

All 9 Indic scripts now fully transliterate — UNDECIDABLE is never returned
for a known script with detected content.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

# ─────────────────────────────────────────────────────────────────────────────
#  Salutations
# ─────────────────────────────────────────────────────────────────────────────

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
    """Remove leading Indic or English salutation token(s) from a payee name."""
    if not text:
        return ""
    tokens = text.split()
    start = 0
    for tok in tokens:
        normalised = tok.rstrip(".").lower()
        if normalised in _SALUTATIONS_NORMALISED:
            start += 1
        else:
            break
    return " ".join(tokens[start:])


# ─────────────────────────────────────────────────────────────────────────────
#  Generic Brahmic transliteration engine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _IndicScript:
    """Configuration for one Brahmic script's transliteration."""
    consonants: dict          # consonant char → Latin
    matras: dict              # vowel sign → Latin (replaces inherent 'a')
    standalone: dict          # standalone vowel → Latin
    halant: str               # virama / pulli — suppresses inherent 'a'
    anusvara: str             # nasal marker → 'n'
    chandrabindu: str         # alternate nasal ('' if absent)
    visarga: str              # aspiration → omit ('' if absent)
    nukta: str                # nukta for borrowed sounds ('' if absent)
    digits: dict              # script digit → ASCII digit
    range_lo: str             # Unicode block start
    range_hi: str             # Unicode block end


def _transliterate_indic(text: str, cfg: _IndicScript) -> str:
    """Generic Brahmic script transliterator.

    Same inherent-'a' algorithm as transliterate_devanagari(), parameterised
    so all 9 scripts share one implementation.
    """
    out: list[str] = []
    chars = list(text)
    n = len(chars)
    i = 0

    def in_script(ch: str) -> bool:
        return cfg.range_lo <= ch <= cfg.range_hi

    while i < n:
        ch = chars[i]

        if ch in cfg.digits:
            out.append(cfg.digits[ch])
            i += 1
            continue

        if not in_script(ch):
            out.append(ch)
            i += 1
            continue

        if ch in cfg.standalone:
            out.append(cfg.standalone[ch])
            i += 1
            continue

        if ch == cfg.anusvara or (cfg.chandrabindu and ch == cfg.chandrabindu):
            out.append("n")
            i += 1
            continue

        if cfg.visarga and ch == cfg.visarga:
            i += 1
            continue

        if cfg.nukta and ch == cfg.nukta:
            i += 1
            continue

        if ch == cfg.halant:
            i += 1
            continue

        if ch in cfg.matras:
            out.append(cfg.matras[ch])
            i += 1
            continue

        if ch in cfg.consonants:
            nukta_form = (ch + cfg.nukta
                          if (cfg.nukta and i + 1 < n and chars[i + 1] == cfg.nukta)
                          else None)
            if nukta_form and nukta_form in cfg.consonants:
                cons_latin = cfg.consonants[nukta_form]
                i += 2
            else:
                cons_latin = cfg.consonants[ch]
                i += 1

            out.append(cons_latin)

            if i < n:
                nxt = chars[i]
                if nxt == cfg.halant:
                    i += 1
                elif nxt in cfg.matras:
                    out.append(cfg.matras[nxt])
                    i += 1
                elif nxt == cfg.anusvara or (cfg.chandrabindu and nxt == cfg.chandrabindu):
                    out.append("a")
                else:
                    out.append("a")
            else:
                out.append("a")
            continue

        i += 1

    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
#  Devanagari (Hindi, Marathi, Sanskrit)
# ─────────────────────────────────────────────────────────────────────────────

_DEVA_CONSONANTS: dict[str, str] = {
    "क": "k",  "ख": "kh", "ग": "g",  "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh","ज": "j",  "झ": "jh", "ञ": "n",
    "ट": "t",  "ठ": "th", "ड": "d",  "ढ": "dh", "ण": "n",
    "त": "t",  "थ": "th", "द": "d",  "ध": "dh", "न": "n",
    "प": "p",  "फ": "ph", "ब": "b",  "भ": "bh", "म": "m",
    "य": "y",  "र": "r",  "ल": "l",  "व": "v",
    "श": "sh", "ष": "sh", "स": "s",  "ह": "h",
    "ळ": "l",
    "ड़": "r",  "ढ़": "rh", "ऱ": "r",
    "क़": "q",  "ख़": "kh", "ग़": "g",
    "ज़": "z",  "फ़": "f",  "य़": "y",
}
_DEVA_MATRAS: dict[str, str] = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "o", "ृ": "ri",
    "ॅ": "e", "ॆ": "e", "ॊ": "o",
}
_DEVA_STANDALONE: dict[str, str] = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i",
    "उ": "u", "ऊ": "u", "ए": "e", "ऐ": "ai",
    "ओ": "o", "औ": "o", "ऋ": "ri",
}
_DEVA_DIGITS: dict[str, str] = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

_SCRIPT_DEVANAGARI = _IndicScript(
    consonants=_DEVA_CONSONANTS,
    matras=_DEVA_MATRAS,
    standalone=_DEVA_STANDALONE,
    halant="्",
    anusvara="ं",
    chandrabindu="ँ",
    visarga="ः",
    nukta="़",
    digits=_DEVA_DIGITS,
    range_lo="ऀ",
    range_hi="ॿ",
)


def transliterate_devanagari(text: str) -> str:
    """Convert Devanagari text to simplified Latin for name matching."""
    return _transliterate_indic(text, _SCRIPT_DEVANAGARI)


# ─────────────────────────────────────────────────────────────────────────────
#  Bengali (West Bengal, Bangladesh — 0x0980–0x09FF)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_BENGALI = _IndicScript(
    consonants={
        "ক": "k", "খ": "kh", "গ": "g", "ঘ": "gh", "ঙ": "n",
        "চ": "ch", "ছ": "chh", "জ": "j", "ঝ": "jh", "ঞ": "n",
        "ট": "t", "ঠ": "th", "ড": "d", "ঢ": "dh", "ণ": "n",
        "ত": "t", "থ": "th", "দ": "d", "ধ": "dh", "ন": "n",
        "প": "p", "ফ": "ph", "ব": "b", "ভ": "bh", "ম": "m",
        "য": "y", "র": "r", "ল": "l",
        "শ": "sh", "ষ": "sh", "স": "s", "হ": "h",
        "ড়": "r", "ঢ়": "rh", "য়": "y",
    },
    matras={
        "া": "a", "ি": "i", "ী": "i", "ু": "u", "ূ": "u",
        "ৃ": "ri", "ে": "e", "ৈ": "ai", "ো": "o", "ৌ": "o",
    },
    standalone={
        "অ": "a", "আ": "a", "ই": "i", "ঈ": "i",
        "উ": "u", "ঊ": "u", "ঋ": "ri", "এ": "e",
        "ঐ": "ai", "ও": "o", "ঔ": "o",
    },
    halant="্",
    anusvara="ং",
    chandrabindu="ঁ",
    visarga="ঃ",
    nukta="়",
    digits={
        "০": "0", "১": "1", "২": "2", "৩": "3", "৪": "4",
        "৫": "5", "৬": "6", "৭": "7", "৮": "8", "৯": "9",
    },
    range_lo="ঀ",
    range_hi="৿",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Gurmukhi / Punjabi (0x0A00–0x0A7F)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_GURMUKHI = _IndicScript(
    consonants={
        "ਕ": "k", "ਖ": "kh", "ਗ": "g", "ਘ": "gh", "ਙ": "n",
        "ਚ": "ch", "ਛ": "chh", "ਜ": "j", "ਝ": "jh", "ਞ": "n",
        "ਟ": "t", "ਠ": "th", "ਡ": "d", "ਢ": "dh", "ਣ": "n",
        "ਤ": "t", "ਥ": "th", "ਦ": "d", "ਧ": "dh", "ਨ": "n",
        "ਪ": "p", "ਫ": "ph", "ਬ": "b", "ਭ": "bh", "ਮ": "m",
        "ਯ": "y", "ਰ": "r", "ਲ": "l", "ਵ": "v",
        "ਸ਼": "sh", "ਸ": "s", "ਹ": "h",
        "ਖ਼": "kh", "ਗ਼": "g", "ਜ਼": "z", "ਫ਼": "f",
        "ਲ਼": "l", "ਸ਼": "sh",
    },
    matras={
        "ਾ": "a", "ਿ": "i", "ੀ": "i", "ੁ": "u", "ੂ": "u",
        "ੇ": "e", "ੈ": "ai", "ੋ": "o", "ੌ": "o",
        "ੱ": "",   # addak (gemination marker) — omit for name matching
    },
    standalone={
        "ਅ": "a", "ਆ": "a", "ਇ": "i", "ਈ": "i",
        "ਉ": "u", "ਊ": "u", "ਏ": "e", "ਐ": "ai",
        "ਓ": "o", "ਔ": "o",
    },
    halant="੍",
    anusvara="ਂ",
    chandrabindu="ੰ",   # tippi (U+0A70) — also nasal in Punjabi
    visarga="ਃ",
    nukta="਼",
    digits={
        "੦": "0", "੧": "1", "੨": "2", "੩": "3", "੪": "4",
        "੫": "5", "੬": "6", "੭": "7", "੮": "8", "੯": "9",
    },
    range_lo="਀",
    range_hi="੿",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Gujarati (0x0A80–0x0AFF)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_GUJARATI = _IndicScript(
    consonants={
        "ક": "k", "ખ": "kh", "ગ": "g", "ઘ": "gh", "ઙ": "n",
        "ચ": "ch", "છ": "chh", "જ": "j", "ઝ": "jh", "ઞ": "n",
        "ટ": "t", "ઠ": "th", "ડ": "d", "ઢ": "dh", "ણ": "n",
        "ત": "t", "થ": "th", "દ": "d", "ધ": "dh", "ન": "n",
        "પ": "p", "ફ": "ph", "બ": "b", "ભ": "bh", "મ": "m",
        "ય": "y", "ર": "r", "લ": "l", "વ": "v",
        "શ": "sh", "ષ": "sh", "સ": "s", "હ": "h",
        "ળ": "l",
    },
    matras={
        "ા": "a", "િ": "i", "ી": "i", "ુ": "u", "ૂ": "u",
        "ૃ": "ri", "ે": "e", "ૈ": "ai", "ો": "o", "ૌ": "o",
    },
    standalone={
        "અ": "a", "આ": "a", "ઇ": "i", "ઈ": "i",
        "ઉ": "u", "ઊ": "u", "ઋ": "ri", "એ": "e",
        "ઐ": "ai", "ઓ": "o", "ઔ": "o",
    },
    halant="્",
    anusvara="ં",
    chandrabindu="ઁ",
    visarga="ઃ",
    nukta="",
    digits={
        "૦": "0", "૧": "1", "૨": "2", "૩": "3", "૪": "4",
        "૫": "5", "૬": "6", "૭": "7", "૮": "8", "૯": "9",
    },
    range_lo="઀",
    range_hi="૿",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Odia / Oriya (0x0B00–0x0B7F)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_ODIA = _IndicScript(
    consonants={
        "କ": "k", "ଖ": "kh", "ଗ": "g", "ଘ": "gh", "ଙ": "n",
        "ଚ": "ch", "ଛ": "chh", "ଜ": "j", "ଝ": "jh", "ଞ": "n",
        "ଟ": "t", "ଠ": "th", "ଡ": "d", "ଢ": "dh", "ଣ": "n",
        "ତ": "t", "ଥ": "th", "ଦ": "d", "ଧ": "dh", "ନ": "n",
        "ପ": "p", "ଫ": "ph", "ବ": "b", "ଭ": "bh", "ମ": "m",
        "ଯ": "y", "ର": "r", "ଲ": "l", "ୱ": "v",
        "ଶ": "sh", "ଷ": "sh", "ସ": "s", "ହ": "h",
        "ଳ": "l", "ଡ଼": "r", "ଢ଼": "rh",
    },
    matras={
        "ା": "a", "ି": "i", "ୀ": "i", "ୁ": "u", "ୂ": "u",
        "ୃ": "ri", "େ": "e", "ୈ": "ai", "ୋ": "o", "ୌ": "o",
    },
    standalone={
        "ଅ": "a", "ଆ": "a", "ଇ": "i", "ଈ": "i",
        "ଉ": "u", "ଊ": "u", "ଋ": "ri", "ଏ": "e",
        "ଐ": "ai", "ଓ": "o", "ଔ": "o",
    },
    halant="୍",
    anusvara="ଂ",
    chandrabindu="ଁ",
    visarga="ଃ",
    nukta="",
    digits={
        "୦": "0", "୧": "1", "୨": "2", "୩": "3", "୪": "4",
        "୫": "5", "୬": "6", "୭": "7", "୮": "8", "୯": "9",
    },
    range_lo="଀",
    range_hi="୿",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Tamil (0x0B80–0x0BFF)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_TAMIL = _IndicScript(
    consonants={
        "க": "k", "ங": "n", "ச": "ch", "ஞ": "n",
        "ட": "t", "ண": "n", "த": "t", "ந": "n",
        "ப": "p", "ம": "m", "ய": "y", "ர": "r",
        "ல": "l", "வ": "v", "ழ": "l", "ள": "l",
        "ற": "r", "ன": "n",
        # Grantha (borrowed for Sanskrit sounds)
        "ஜ": "j", "ஷ": "sh", "ஸ": "s", "ஹ": "h",
        "க்ஷ": "ksh",
    },
    matras={
        "ா": "a", "ி": "i", "ீ": "i", "ு": "u", "ூ": "u",
        "ெ": "e", "ே": "e", "ை": "ai", "ொ": "o", "ோ": "o",
        "ௌ": "o",
    },
    standalone={
        "அ": "a", "ஆ": "a", "இ": "i", "ஈ": "i",
        "உ": "u", "ஊ": "u", "எ": "e", "ஏ": "e",
        "ஐ": "ai", "ஒ": "o", "ஓ": "o", "ஔ": "o",
    },
    halant="்",      # pulli — Tamil virama
    anusvara="ஂ",
    chandrabindu="",
    visarga="",
    nukta="",
    digits={
        "௦": "0", "௧": "1", "௨": "2", "௩": "3", "௪": "4",
        "௫": "5", "௬": "6", "௭": "7", "௮": "8", "௯": "9",
    },
    range_lo="஀",
    range_hi="௿",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Telugu (0x0C00–0x0C7F)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_TELUGU = _IndicScript(
    consonants={
        "క": "k", "ఖ": "kh", "గ": "g", "ఘ": "gh", "ఙ": "n",
        "చ": "ch", "ఛ": "chh", "జ": "j", "ఝ": "jh", "ఞ": "n",
        "ట": "t", "ఠ": "th", "డ": "d", "ఢ": "dh", "ణ": "n",
        "త": "t", "థ": "th", "ద": "d", "ధ": "dh", "న": "n",
        "ప": "p", "ఫ": "ph", "బ": "b", "భ": "bh", "మ": "m",
        "య": "y", "ర": "r", "ల": "l", "వ": "v",
        "శ": "sh", "ష": "sh", "స": "s", "హ": "h",
        "ళ": "l", "ఱ": "r",
    },
    matras={
        "ా": "a", "ి": "i", "ీ": "i", "ు": "u", "ూ": "u",
        "ృ": "ri", "ె": "e", "ే": "e", "ై": "ai", "ొ": "o",
        "ో": "o", "ౌ": "o",
    },
    standalone={
        "అ": "a", "ఆ": "a", "ఇ": "i", "ఈ": "i",
        "ఉ": "u", "ఊ": "u", "ఋ": "ri", "ఎ": "e",
        "ఏ": "e", "ఐ": "ai", "ఒ": "o", "ఓ": "o", "ఔ": "o",
    },
    halant="్",
    anusvara="ం",
    chandrabindu="ఁ",
    visarga="ః",
    nukta="",
    digits={
        "౦": "0", "౧": "1", "౨": "2", "౩": "3", "౪": "4",
        "౫": "5", "౬": "6", "౭": "7", "౮": "8", "౯": "9",
    },
    range_lo="ఀ",
    range_hi="౿",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Kannada (0x0C80–0x0CFF)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_KANNADA = _IndicScript(
    consonants={
        "ಕ": "k", "ಖ": "kh", "ಗ": "g", "ಘ": "gh", "ಙ": "n",
        "ಚ": "ch", "ಛ": "chh", "ಜ": "j", "ಝ": "jh", "ಞ": "n",
        "ಟ": "t", "ಠ": "th", "ಡ": "d", "ಢ": "dh", "ಣ": "n",
        "ತ": "t", "ಥ": "th", "ದ": "d", "ಧ": "dh", "ನ": "n",
        "ಪ": "p", "ಫ": "ph", "ಬ": "b", "ಭ": "bh", "ಮ": "m",
        "ಯ": "y", "ರ": "r", "ಲ": "l", "ವ": "v",
        "ಶ": "sh", "ಷ": "sh", "ಸ": "s", "ಹ": "h",
        "ಳ": "l", "ೞ": "l", "ಱ": "r",
    },
    matras={
        "ಾ": "a", "ಿ": "i", "ೀ": "i", "ು": "u", "ೂ": "u",
        "ೃ": "ri", "ೆ": "e", "ೇ": "e", "ೈ": "ai", "ೊ": "o",
        "ೋ": "o", "ೌ": "o",
    },
    standalone={
        "ಅ": "a", "ಆ": "a", "ಇ": "i", "ಈ": "i",
        "ಉ": "u", "ಊ": "u", "ಋ": "ri", "ಎ": "e",
        "ಏ": "e", "ಐ": "ai", "ಒ": "o", "ಓ": "o", "ಔ": "o",
    },
    halant="್",
    anusvara="ಂ",
    chandrabindu="ಁ",
    visarga="ಃ",
    nukta="",
    digits={
        "೦": "0", "೧": "1", "೨": "2", "೩": "3", "೪": "4",
        "೫": "5", "೬": "6", "೭": "7", "೮": "8", "೯": "9",
    },
    range_lo="ಀ",
    range_hi="೿",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Malayalam (0x0D00–0x0D7F)
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_MALAYALAM = _IndicScript(
    consonants={
        "ക": "k", "ഖ": "kh", "ഗ": "g", "ഘ": "gh", "ങ": "n",
        "ച": "ch", "ഛ": "chh", "ജ": "j", "ഝ": "jh", "ഞ": "n",
        "ട": "t", "ഠ": "th", "ഡ": "d", "ഢ": "dh", "ണ": "n",
        "ത": "t", "ഥ": "th", "ദ": "d", "ധ": "dh", "ന": "n",
        "പ": "p", "ഫ": "ph", "ബ": "b", "ഭ": "bh", "മ": "m",
        "യ": "y", "ര": "r", "ല": "l", "വ": "v",
        "ശ": "sh", "ഷ": "sh", "സ": "s", "ഹ": "h",
        "ള": "l", "ഴ": "l", "റ": "r",
        # Chillu (standalone final consonants)
        "ൺ": "n", "ൻ": "n", "ർ": "r", "ൽ": "l", "ൾ": "l",
    },
    matras={
        "ാ": "a", "ി": "i", "ീ": "i", "ു": "u", "ൂ": "u",
        "ൃ": "ri", "െ": "e", "േ": "e", "ൈ": "ai", "ൊ": "o",
        "ോ": "o", "ൌ": "o", "ൗ": "o",
    },
    standalone={
        "അ": "a", "ആ": "a", "ഇ": "i", "ഈ": "i",
        "ഉ": "u", "ഊ": "u", "ഋ": "ri", "എ": "e",
        "ഏ": "e", "ഐ": "ai", "ഒ": "o", "ഓ": "o", "ഔ": "o",
    },
    halant="്",     # chandrakkala
    anusvara="ം",
    chandrabindu="ഁ",
    visarga="ഃ",
    nukta="",
    digits={
        "൦": "0", "൧": "1", "൨": "2", "൩": "3", "൪": "4",
        "൫": "5", "൬": "6", "൭": "7", "൮": "8", "൯": "9",
    },
    range_lo="ഀ",
    range_hi="ൿ",
)


# ─────────────────────────────────────────────────────────────────────────────
#  Dispatch table
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_CONFIGS: dict[str, _IndicScript] = {
    "devanagari": _SCRIPT_DEVANAGARI,
    "bengali":    _SCRIPT_BENGALI,
    "gurmukhi":   _SCRIPT_GURMUKHI,
    "gujarati":   _SCRIPT_GUJARATI,
    "odia":       _SCRIPT_ODIA,
    "tamil":      _SCRIPT_TAMIL,
    "telugu":     _SCRIPT_TELUGU,
    "kannada":    _SCRIPT_KANNADA,
    "malayalam":  _SCRIPT_MALAYALAM,
}

_TRANSLITERABLE_SCRIPTS: frozenset[str] = frozenset(_SCRIPT_CONFIGS)


def transliterate_by_script(text: str, script: str) -> str:
    """Transliterate Indic text to Latin given the script name.

    Returns the original text unchanged if the script is not recognised
    (safe fallback — Jaro-Winkler will score it low → MISMATCH path).
    """
    cfg = _SCRIPT_CONFIGS.get(script)
    if cfg is None:
        return text
    return _transliterate_indic(text, cfg)


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
    """Return True if text contains any Indic-block codepoints (U+0900–U+0D7F)."""
    return any(0x0900 <= ord(ch) <= 0x0D7F for ch in text)


def _detect_script(text: str) -> str | None:
    """Return the dominant Indic script name, or None if no Indic characters."""
    try:
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        return identify_indic_script(text)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Jaro-Winkler (stdlib-only)
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
    score: float | None
    normalized_ocr: str
    normalized_cbs: str


def payee_names_match(
    ocr_name: str,
    cbs_name: str,
    threshold: float,
    script: str | None = None,
) -> PayeeMatchResult:
    """Compare a cheque payee name (possibly Indic) against a CBS-stored name (English).

    For all 9 Indic scripts: strip salutation, transliterate to Latin, then
    Jaro-Winkler fuzzy match against the CBS name.

    Returns UNDECIDABLE only if the script cannot be identified at all —
    not used for any of the 9 supported scripts.
    """
    # Determine script if not provided
    if script is None and _is_indic(ocr_name):
        script = _detect_script(ocr_name)

    # Unknown script (not one of the 9) with Indic content → UNDECIDABLE
    if (script is not None
            and script not in _TRANSLITERABLE_SCRIPTS
            and _is_indic(ocr_name)):
        norm_cbs = _normalize(cbs_name)
        return PayeeMatchResult(
            decision="UNDECIDABLE",
            score=None,
            normalized_ocr=ocr_name,
            normalized_cbs=norm_cbs,
        )

    # Transliterate if the OCR name contains Indic text
    ocr_work = ocr_name
    if script is not None and _is_indic(ocr_name):
        # Strip salutation BEFORE transliteration (critical ordering)
        ocr_work = strip_salutation(ocr_name)
        # Lexicon lookup: replace script-specific loan-words (Malayalam Christian
        # names) with their canonical English form before the phonemic engine runs
        try:
            from modules.cts.preprocessing.name_lexicon import apply_lexicon
            ocr_work = apply_lexicon(ocr_work, script)
        except ImportError:
            pass
        # Transliterate any remaining Indic tokens the lexicon didn't cover
        if _is_indic(ocr_work):
            ocr_work = transliterate_by_script(ocr_work, script)

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
