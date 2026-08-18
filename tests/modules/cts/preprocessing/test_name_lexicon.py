"""Tests for Malayalam Christian-name lexicon (TDD — RED before GREEN).

Malayalam Christian names (George, Thomas, John, etc.) are of Greek/Aramaic/Hebrew
origin, borrowed via Portuguese colonialism. No phonemic transliteration engine can
recover the conventional English spelling from the Malayalam script form. The lexicon
provides direct script→English mappings checked before transliteration.

All tests follow RED→GREEN order. Run pytest first to confirm FAILED before
any implementation exists.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
#  Module import — expected to fail (RED) until name_lexicon.py is created
# ─────────────────────────────────────────────────────────────────────────────

from modules.cts.preprocessing.name_lexicon import (
    apply_lexicon,
    lookup_token,
    MALAYALAM_LEXICON_SIZE,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Token-level lookup — single Malayalam word
# ─────────────────────────────────────────────────────────────────────────────

class TestLookupToken:
    def test_george_recognised(self):
        assert lookup_token("ജോർജ്ജ്", "malayalam") == "george"

    def test_george_alternate_spelling(self):
        # ജോർജ് (single ജ at end) is also common on cheques
        assert lookup_token("ജോർജ്", "malayalam") == "george"

    def test_thomas_recognised(self):
        assert lookup_token("തോമസ്", "malayalam") == "thomas"

    def test_john_recognised(self):
        assert lookup_token("ജോൺ", "malayalam") == "john"

    def test_mary_recognised(self):
        assert lookup_token("മേരി", "malayalam") == "mary"

    def test_joseph_recognised(self):
        assert lookup_token("ജോസഫ്", "malayalam") == "joseph"

    def test_paul_recognised(self):
        assert lookup_token("പോൾ", "malayalam") == "paul"

    def test_peter_recognised(self):
        assert lookup_token("പീറ്റർ", "malayalam") == "peter"

    def test_philip_recognised(self):
        assert lookup_token("ഫിലിപ്പ്", "malayalam") == "philip"

    def test_mathew_recognised(self):
        # Kerala convention: Mathew (not Matthew)
        assert lookup_token("മത്തായി", "malayalam") == "mathew"

    def test_jacob_recognised(self):
        assert lookup_token("ജേക്കബ്", "malayalam") == "jacob"

    def test_abraham_recognised(self):
        assert lookup_token("അബ്രഹാം", "malayalam") == "abraham"

    def test_elizabeth_recognised(self):
        assert lookup_token("എലിസബത്ത്", "malayalam") == "elizabeth"

    def test_mariamma_recognised(self):
        # Mariamma — Malayalam Christian compound (Maria + amma)
        assert lookup_token("മറിയാമ്മ", "malayalam") == "mariamma"

    def test_thankamma_recognised(self):
        assert lookup_token("തങ്കമ്മ", "malayalam") == "thankamma"

    def test_annamma_recognised(self):
        assert lookup_token("അന്നമ്മ", "malayalam") == "annamma"

    def test_unknown_token_returns_none(self):
        # Standard Hindu name — not in lexicon
        assert lookup_token("കൃഷ്ണൻ", "malayalam") is None

    def test_non_malayalam_script_returns_none(self):
        # Lexicon is Malayalam-only; other scripts must not match
        assert lookup_token("रामेश्वर", "devanagari") is None

    def test_empty_string_returns_none(self):
        assert lookup_token("", "malayalam") is None

    def test_whitespace_returns_none(self):
        assert lookup_token("   ", "malayalam") is None

    def test_latin_input_returns_none(self):
        # Latin text not in lexicon
        assert lookup_token("George", "malayalam") is None


# ─────────────────────────────────────────────────────────────────────────────
#  apply_lexicon — multi-token text
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyLexicon:
    def test_single_christian_name(self):
        result = apply_lexicon("ജോർജ്ജ്", "malayalam")
        assert result == "george"

    def test_two_christian_names(self):
        # "George Thomas" — both in lexicon
        result = apply_lexicon("ജോർജ്ജ് തോമസ്", "malayalam")
        assert result == "george thomas"

    def test_christian_name_plus_hindu_name(self):
        # First token in lexicon, second not — second passes through for transliteration
        result = apply_lexicon("ജോൺ നായർ", "malayalam")
        # "john" from lexicon, "nayara" or similar from transliteration
        parts = result.split()
        assert parts[0] == "john"
        assert len(parts) == 2  # both tokens present

    def test_all_hindu_names_unchanged_script(self):
        # No lexicon match — returns original (transliteration happens later)
        result = apply_lexicon("കൃഷ്ണൻ നായർ", "malayalam")
        assert result == "കൃഷ്ണൻ നായർ"  # unchanged — no lexicon entries

    def test_non_malayalam_script_passthrough(self):
        # Devanagari should not be touched
        text = "रामेश्वर"
        assert apply_lexicon(text, "devanagari") == text

    def test_latin_passthrough(self):
        text = "Lata Deshpande"
        assert apply_lexicon(text, "latin") == text

    def test_empty_string(self):
        assert apply_lexicon("", "malayalam") == ""

    def test_compound_name_georgekutty(self):
        # ജോർജ്ജ്കുട്ടി — one token, whole entry in lexicon
        result = apply_lexicon("ജോർജ്ജ്കുട്ടി", "malayalam")
        assert result == "georgekutty"

    def test_compound_name_thomaskutty(self):
        result = apply_lexicon("തോമസ്കുട്ടി", "malayalam")
        assert result == "thomaskutty"

    def test_three_token_name(self):
        # "John George Thomas" — all three in lexicon
        result = apply_lexicon("ജോൺ ജോർജ്ജ് തോമസ്", "malayalam")
        assert result == "john george thomas"

    def test_preserves_token_order(self):
        result = apply_lexicon("തോമസ്  ജോർജ്ജ്", "malayalam")
        parts = result.split()
        assert parts == ["thomas", "george"]


# ─────────────────────────────────────────────────────────────────────────────
#  Lexicon size guarantee — must have >= 50 entries
# ─────────────────────────────────────────────────────────────────────────────

class TestLexiconSize:
    def test_at_least_50_entries(self):
        assert MALAYALAM_LEXICON_SIZE >= 50

    def test_all_values_are_lowercase_latin(self):
        from modules.cts.preprocessing.name_lexicon import _MALAYALAM_LEXICON
        for key, val in _MALAYALAM_LEXICON.items():
            assert val == val.lower(), f"Lexicon value not lowercase: {key!r} → {val!r}"
            assert val.isascii(), f"Lexicon value not ASCII: {key!r} → {val!r}"

    def test_no_empty_keys_or_values(self):
        from modules.cts.preprocessing.name_lexicon import _MALAYALAM_LEXICON
        for key, val in _MALAYALAM_LEXICON.items():
            assert key.strip(), "Empty key in lexicon"
            assert val.strip(), f"Empty value for key {key!r}"


# ─────────────────────────────────────────────────────────────────────────────
#  Integration: payee_names_match improves after lexicon wiring
# ─────────────────────────────────────────────────────────────────────────────

class TestLexiconInPayeeMatch:
    """Verify payee_names_match uses the lexicon — JW must be >=0.90 for
    Christian names that scored <0.60 before the lexicon was wired in."""

    def test_george_match_improves(self):
        from modules.cts.preprocessing.payee_normalizer import payee_names_match
        result = payee_names_match("ജോർജ്ജ്", "George", threshold=0.85)
        assert result.score is not None
        assert result.score >= 0.90, (
            f"George: expected JW >=0.90, got {result.score} "
            f"(normalized_ocr={result.normalized_ocr!r})"
        )
        assert result.decision in ("MATCH", "FUZZY")

    def test_thomas_match_improves(self):
        from modules.cts.preprocessing.payee_normalizer import payee_names_match
        result = payee_names_match("തോമസ്", "Thomas", threshold=0.85)
        assert result.score is not None
        assert result.score >= 0.90
        assert result.decision in ("MATCH", "FUZZY")

    def test_george_thomas_full_name(self):
        from modules.cts.preprocessing.payee_normalizer import payee_names_match
        result = payee_names_match("ജോർജ്ജ് തോമസ്", "George Thomas", threshold=0.85)
        assert result.score is not None
        assert result.score >= 0.88
        assert result.decision in ("MATCH", "FUZZY")

    def test_standard_hindu_names_unaffected(self):
        from modules.cts.preprocessing.payee_normalizer import payee_names_match
        # Krishnan / Nair — should still match at same quality as before
        result = payee_names_match("കൃഷ്ണൻ", "Krishnan", threshold=0.85)
        assert result.score is not None
        assert result.score >= 0.75  # same level as always

    def test_devanagari_names_unaffected(self):
        from modules.cts.preprocessing.payee_normalizer import payee_names_match
        result = payee_names_match("देशपांडे", "Deshpande", threshold=0.82)
        assert result.score is not None
        assert result.score >= 0.85  # Brahmic engine baseline
