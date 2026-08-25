"""
TDD — IndicXlit seq2seq transliteration path in payee_normalizer.

RED: run before implementing _XLIT_SCRIPT_TO_LANG, _get_xlit_engine, or
     the IndicXlit branch in transliterate_by_script.

Covers:
  - All 9 scripts have a lang_code mapping in _XLIT_SCRIPT_TO_LANG
  - transliterate_by_script uses IndicXlit when engine is available
  - word-level fallback to Brahmic phonemic when IndicXlit returns [] or raises
  - graceful fallback to phonemic when IndicXlit is not installed
  - payee_names_match end-to-end with IndicXlit active (Malayalam Christian names)
  - payee_names_match end-to-end with IndicXlit unavailable (phonemic path)
"""

import pytest
from unittest.mock import MagicMock

import modules.cts.preprocessing.payee_normalizer as norm


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset_xlit(monkeypatch):
    """Reset module-level IndicXlit cache so each test starts from a clean state."""
    monkeypatch.setattr(norm, "_xlit_engine", None)
    monkeypatch.setattr(norm, "_xlit_tried", False)


# ─────────────────────────────────────────────────────────────────────────────
#  Script → lang mapping
# ─────────────────────────────────────────────────────────────────────────────

class TestXlitScriptMapping:
    def test_all_nine_scripts_present(self):
        expected = {
            "devanagari", "bengali", "gurmukhi", "gujarati",
            "odia", "tamil", "telugu", "kannada", "malayalam",
        }
        assert expected == set(norm._XLIT_SCRIPT_TO_LANG.keys())

    def test_lang_codes_are_iso_639_1(self):
        valid = {"hi", "bn", "pa", "gu", "or", "ta", "te", "kn", "ml"}
        assert valid == set(norm._XLIT_SCRIPT_TO_LANG.values())

    def test_malayalam_maps_to_ml(self):
        assert norm._XLIT_SCRIPT_TO_LANG["malayalam"] == "ml"

    def test_devanagari_maps_to_hi(self):
        assert norm._XLIT_SCRIPT_TO_LANG["devanagari"] == "hi"


# ─────────────────────────────────────────────────────────────────────────────
#  transliterate_by_script — IndicXlit available
# ─────────────────────────────────────────────────────────────────────────────

class TestTransliterateByScriptXlitAvailable:
    def test_malayalam_george_via_xlit(self, monkeypatch):
        """IndicXlit returns 'george' — the conventional spelling that phonemic can't produce."""
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.return_value = ["george"]
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.transliterate_by_script("ജോർജ്ജ്", "malayalam")
        assert result == "george"
        engine.translit_word.assert_called_once_with("ജോർജ്ജ്", lang_code="ml", topk=1)

    def test_hindi_name_via_xlit(self, monkeypatch):
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.return_value = ["sharma"]
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.transliterate_by_script("शर्मा", "devanagari")
        assert result == "sharma"
        engine.translit_word.assert_called_once_with("शर्मा", lang_code="hi", topk=1)

    def test_multiword_each_word_xlitted_separately(self, monkeypatch):
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.side_effect = [["lata"], ["deshpande"]]
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.transliterate_by_script("लता देशपांडे", "devanagari")
        assert result == "lata deshpande"
        assert engine.translit_word.call_count == 2

    def test_unknown_script_returns_original_text(self, monkeypatch):
        """Script not in _XLIT_SCRIPT_TO_LANG → original unchanged, engine not called."""
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.transliterate_by_script("some text", "sinhala")
        assert result == "some text"
        engine.translit_word.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
#  transliterate_by_script — word-level phonemic fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestTransliterateXlitWordLevelFallback:
    def test_xlit_returns_empty_list_falls_back_to_phonemic(self, monkeypatch):
        """XlitEngine returns [] for a word → phonemic engine handles it."""
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.return_value = []
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        # Devanagari: ल=l inherent-a=a, त=t inherent-a=a → "lata"
        result = norm.transliterate_by_script("लता", "devanagari")
        assert result == "lata"

    def test_xlit_raises_falls_back_to_phonemic(self, monkeypatch):
        """XlitEngine.translit_word raises RuntimeError → phonemic for that word."""
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.side_effect = RuntimeError("gpu error")
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.transliterate_by_script("राज", "devanagari")
        # phonemic: र=r, ा=a (matra on prev), ज=j inherent-a → "raja"
        assert result == "raja"

    def test_mixed_xlit_and_phonemic_per_word(self, monkeypatch):
        """First word fails xlit → phonemic; second word succeeds via xlit."""
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.side_effect = [[], ["deshpande"]]
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.transliterate_by_script("लता देशपांडे", "devanagari")
        # "लता" → phonemic "lata"; "देशपांडे" → xlit "deshpande"
        assert result == "lata deshpande"


# ─────────────────────────────────────────────────────────────────────────────
#  transliterate_by_script — IndicXlit unavailable
# ─────────────────────────────────────────────────────────────────────────────

class TestTransliterateXlitUnavailable:
    def test_phonemic_engine_used_when_xlit_none(self, monkeypatch):
        """engine=None (package not installed) → full Brahmic phonemic fallback."""
        _reset_xlit(monkeypatch)
        monkeypatch.setattr(norm, "_xlit_engine", None)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.transliterate_by_script("लता", "devanagari")
        assert result == "lata"

    def test_phonemic_tamil_when_xlit_none(self, monkeypatch):
        _reset_xlit(monkeypatch)
        monkeypatch.setattr(norm, "_xlit_engine", None)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        # Tamil: க=k inherent-a → "ka" (basic Tamil consonant)
        result = norm.transliterate_by_script("கணேஷ்", "tamil")
        assert len(result) > 0   # something was produced
        assert result.isascii()   # Latin output


# ─────────────────────────────────────────────────────────────────────────────
#  payee_names_match — end-to-end with IndicXlit
# ─────────────────────────────────────────────────────────────────────────────

class TestPayeeNamesMatchEndToEnd:
    def test_malayalam_george_matches_english_via_xlit(self, monkeypatch):
        """
        'ജോർജ്ജ്' (Malayalam George) should MATCH 'George' with IndicXlit.
        Without xlit, phonemic produces 'joorjj' → MISMATCH.
        """
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.return_value = ["george"]
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.payee_names_match(
            ocr_name="ജോർജ്ജ്",
            cbs_name="George",
            threshold=0.82,
            script="malayalam",
        )
        assert result.decision in ("MATCH", "FUZZY"), \
            f"Expected MATCH/FUZZY but got {result.decision} (score={result.score})"
        assert result.normalized_ocr == "george"

    def test_malayalam_thomas_matches_english_via_xlit(self, monkeypatch):
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.return_value = ["thomas"]
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.payee_names_match(
            ocr_name="തോമസ്",
            cbs_name="Thomas",
            threshold=0.82,
            script="malayalam",
        )
        assert result.decision in ("MATCH", "FUZZY")

    def test_standard_hindi_name_matches_phonemic_fallback(self, monkeypatch):
        """Standard Hindu names match fine even without IndicXlit (phonemic path)."""
        _reset_xlit(monkeypatch)
        monkeypatch.setattr(norm, "_xlit_engine", None)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.payee_names_match(
            ocr_name="लता देशपांडे",
            cbs_name="Lata Deshpande",
            threshold=0.82,
            script="devanagari",
        )
        assert result.decision in ("MATCH", "FUZZY"), \
            f"Expected MATCH/FUZZY but got {result.decision} (score={result.score})"

    def test_xlit_active_wrong_person_still_mismatch(self, monkeypatch):
        """Different person entirely → MISMATCH even with IndicXlit active."""
        _reset_xlit(monkeypatch)
        engine = MagicMock()
        engine.translit_word.return_value = ["suresh"]
        monkeypatch.setattr(norm, "_xlit_engine", engine)
        monkeypatch.setattr(norm, "_xlit_tried", True)

        result = norm.payee_names_match(
            ocr_name="सुरेश",
            cbs_name="Rajesh Kumar",
            threshold=0.82,
            script="devanagari",
        )
        assert result.decision == "MISMATCH"
