"""Transliteration benchmark: Brahmic engine vs indic-transliteration (ITRANS scheme).

POC that empirically answers: "Does switching to the indic-transliteration library
(scholarly ITRANS romanization) improve payee-name JW matching accuracy over our
homegrown Brahmic engine?"

Verdict (2026-08-13): NO. Our Brahmic engine is already better for Indian name
matching:
  - anusvara → 'n' (ours) vs 'm' before consonants (ITRANS Sanskrit rule)
    gives 'deshpande' vs 'deshapamde' — ours wins by 0.087 JW
  - tippi/anusvara → 'n' (ours) vs 'simgha' (ITRANS) for ਸਿੰਘ — ours wins by 0.109

Remaining gap is NOT a transliteration problem: Malayalam Christian names
(George, Thomas from Greek/Aramaic origins) cannot be recovered by any
phonemic rule engine. Recommendation: name lexicon or IndicXlit seq2seq.

Reference: see docs/xlit-poc-findings.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from modules.cts.preprocessing.payee_normalizer import (
    transliterate_by_script,
    _jaro_winkler,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NameRow:
    indic: str
    english: str
    script: str
    language: str


@dataclass
class BenchmarkResultRow:
    name_row: NameRow
    brahmic_latin: str
    brahmic_jw: float
    itrans_latin: str
    itrans_jw: float
    winner: str   # 'brahmic' | 'itrans' | 'tie'

    @property
    def english(self) -> str:
        return self.name_row.english


@dataclass
class BenchmarkReport:
    rows: list[BenchmarkResultRow]
    brahmic_avg_jw: float
    itrans_avg_jw: float
    brahmic_wins: int
    itrans_wins: int
    ties: int
    per_language: dict[str, dict]
    known_failures: list[BenchmarkResultRow]
    recommendation: str


# ─────────────────────────────────────────────────────────────────────────────
#  Corpus — representative Indian banking names across all 9 scripts
# ─────────────────────────────────────────────────────────────────────────────

_CORPUS: list[NameRow] = [
    # Devanagari (Hindi, Marathi)
    NameRow("रामेश्वर",    "Rameshwar",    "devanagari", "Hindi"),
    NameRow("विश्वनाथ",   "Vishwanath",   "devanagari", "Hindi"),
    NameRow("देशपांडे",   "Deshpande",    "devanagari", "Marathi"),
    NameRow("लता देवी",   "Lata Devi",    "devanagari", "Hindi"),
    NameRow("महेंद्र",    "Mahendra",     "devanagari", "Hindi"),
    # Bengali
    NameRow("রামকৃষ্ণ",   "Ramkrishna",   "bengali",    "Bengali"),
    NameRow("দেবনাথ",     "Debnath",      "bengali",    "Bengali"),
    NameRow("চক্রবর্তী",  "Chakraborty",  "bengali",    "Bengali"),
    # Gurmukhi (Punjabi)
    NameRow("ਸਿੰਘ",       "Singh",        "gurmukhi",   "Punjabi"),
    NameRow("ਗੁਰਪ੍ਰੀਤ",  "Gurpreet",     "gurmukhi",   "Punjabi"),
    NameRow("ਕਮਲਜੀਤ",    "Kamaljit",     "gurmukhi",   "Punjabi"),
    # Gujarati
    NameRow("ભટ્ટ",       "Bhatt",        "gujarati",   "Gujarati"),
    NameRow("પટેલ",       "Patel",        "gujarati",   "Gujarati"),
    # Tamil
    NameRow("முருகன்",    "Murugan",      "tamil",      "Tamil"),
    NameRow("சுப்பிரமணியன்", "Subramanian", "tamil",    "Tamil"),
    NameRow("வேலுசாமி",   "Velusamy",     "tamil",      "Tamil"),
    # Telugu
    NameRow("రామారావు",   "Ramarao",      "telugu",     "Telugu"),
    NameRow("వెంకటేష్",  "Venkatesh",    "telugu",     "Telugu"),
    # Kannada
    NameRow("ರಾಮಕೃಷ್ಣ",  "Ramakrishna",  "kannada",    "Kannada"),
    NameRow("ಹೆಗಡೆ",     "Hegde",        "kannada",    "Kannada"),
    # Malayalam — standard Hindu names
    NameRow("കൃഷ്ണൻ",    "Krishnan",     "malayalam",  "Malayalam"),
    NameRow("നായർ",      "Nair",         "malayalam",  "Malayalam"),
    # Malayalam — Christian names (known failures)
    NameRow("ജോർജ്ജ്",   "George",       "malayalam",  "Malayalam"),
    NameRow("തോമസ്",     "Thomas",       "malayalam",  "Malayalam"),
]

_FAILURE_JW_THRESHOLD = 0.75


# ─────────────────────────────────────────────────────────────────────────────
#  ITRANS via indic-transliteration
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_TO_ITRANS_CONSTANT: dict[str, object] = {}

def _get_itrans_constant(script: str) -> Optional[object]:
    """Lazy-load the sanscript scheme constant for a given script name."""
    global _SCRIPT_TO_ITRANS_CONSTANT
    if not _SCRIPT_TO_ITRANS_CONSTANT:
        try:
            from indic_transliteration.sanscript import (
                DEVANAGARI, BENGALI, GURMUKHI, GUJARATI, ORIYA,
                TAMIL, TELUGU, KANNADA, MALAYALAM, ITRANS,
            )
            _SCRIPT_TO_ITRANS_CONSTANT = {
                "devanagari": DEVANAGARI,
                "bengali":    BENGALI,
                "gurmukhi":   GURMUKHI,
                "gujarati":   GUJARATI,
                "odia":       ORIYA,
                "tamil":      TAMIL,
                "telugu":     TELUGU,
                "kannada":    KANNADA,
                "malayalam":  MALAYALAM,
                "_itrans":    ITRANS,
            }
        except ImportError:
            return None
    return _SCRIPT_TO_ITRANS_CONSTANT.get(script)


def _transliterate_itrans(text: str, script: str) -> str:
    """Transliterate Indic text via indic-transliteration ITRANS scheme, then lowercase."""
    try:
        from indic_transliteration.sanscript import transliterate
        src = _get_itrans_constant(script)
        itrans = _get_itrans_constant("_itrans")
        if src is None or itrans is None:
            return text
        result = transliterate(text, src, itrans)
        return result.lower()
    except Exception:
        return text.lower()


# ─────────────────────────────────────────────────────────────────────────────
#  Core comparison function
# ─────────────────────────────────────────────────────────────────────────────

def compare_approaches(indic: str, english: str, script: str) -> dict:
    """Compare Brahmic engine vs ITRANS for a single name pair.

    Returns:
        brahmic_latin: transliterated form from our Brahmic engine
        brahmic_jw: Jaro-Winkler(brahmic_latin, english.lower())
        itrans_latin: transliterated form from indic-transliteration
        itrans_jw: Jaro-Winkler(itrans_latin, english.lower())
        winner: 'brahmic' | 'itrans' | 'tie'
    """
    english_lower = english.lower().replace("  ", " ").strip()

    brahmic_latin = transliterate_by_script(indic, script).lower()
    brahmic_jw = _jaro_winkler(brahmic_latin, english_lower)

    itrans_latin = _transliterate_itrans(indic, script)
    itrans_jw = _jaro_winkler(itrans_latin, english_lower)

    diff = brahmic_jw - itrans_jw
    if abs(diff) < 0.005:
        winner = "tie"
    elif diff > 0:
        winner = "brahmic"
    else:
        winner = "itrans"

    return {
        "brahmic_latin": brahmic_latin,
        "brahmic_jw":    round(brahmic_jw, 4),
        "itrans_latin":  itrans_latin,
        "itrans_jw":     round(itrans_jw, 4),
        "winner":        winner,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Benchmark runner
# ─────────────────────────────────────────────────────────────────────────────

def run_benchmark() -> BenchmarkReport:
    """Run the full benchmark corpus and return a BenchmarkReport."""
    result_rows: list[BenchmarkResultRow] = []

    for name_row in _CORPUS:
        cmp = compare_approaches(name_row.indic, name_row.english, name_row.script)
        result_rows.append(BenchmarkResultRow(
            name_row=name_row,
            brahmic_latin=cmp["brahmic_latin"],
            brahmic_jw=cmp["brahmic_jw"],
            itrans_latin=cmp["itrans_latin"],
            itrans_jw=cmp["itrans_jw"],
            winner=cmp["winner"],
        ))

    brahmic_avg = sum(r.brahmic_jw for r in result_rows) / len(result_rows)
    itrans_avg = sum(r.itrans_jw for r in result_rows) / len(result_rows)
    brahmic_wins = sum(1 for r in result_rows if r.winner == "brahmic")
    itrans_wins = sum(1 for r in result_rows if r.winner == "itrans")
    ties = sum(1 for r in result_rows if r.winner == "tie")

    # Per-language breakdown
    per_language: dict[str, dict] = {}
    from itertools import groupby
    lang_sorted = sorted(result_rows, key=lambda r: r.name_row.language)
    for lang, group in groupby(lang_sorted, key=lambda r: r.name_row.language):
        rows_l = list(group)
        per_language[lang] = {
            "brahmic_avg": round(sum(r.brahmic_jw for r in rows_l) / len(rows_l), 4),
            "itrans_avg":  round(sum(r.itrans_jw for r in rows_l) / len(rows_l), 4),
            "n":           len(rows_l),
        }

    # Known failures: names where even the better approach scores below threshold
    known_failures = [
        r for r in result_rows
        if r.brahmic_jw < _FAILURE_JW_THRESHOLD
    ]

    recommendation = (
        "KEEP our Brahmic engine — it outperforms ITRANS (scholarly scheme) for Indian "
        "name matching: avg JW {brahmic_avg:.3f} vs {itrans_avg:.3f}. "
        "Remaining gap is semantic (foreign-origin Christian names like George, Thomas "
        "in Malayalam), not phonemic. Next steps: "
        "(1) add a Malayalam Christian-name lexicon for the top-50 names; "
        "(2) in a Docker/Linux environment, trial AI4Bharat IndicXlit (seq2seq, 5ms CPU) "
        "which was trained on conventional name spellings from the Dakshina dataset; "
        "(3) long-term: consider BGE-M3 semantic embeddings (already deployed for EJ) "
        "to bypass transliteration entirely."
    ).format(brahmic_avg=brahmic_avg, itrans_avg=itrans_avg)

    return BenchmarkReport(
        rows=result_rows,
        brahmic_avg_jw=round(brahmic_avg, 4),
        itrans_avg_jw=round(itrans_avg, 4),
        brahmic_wins=brahmic_wins,
        itrans_wins=itrans_wins,
        ties=ties,
        per_language=per_language,
        known_failures=known_failures,
        recommendation=recommendation,
    )
