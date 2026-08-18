"""Tests for automated OCR failure mode classifier (TDD — RED before GREEN).

The classifier gets NO human input. It works entirely from signals already
present in every cheque processing run:
  - payee match score (from payee_names_match / CBS comparison)
  - OCR text output
  - Script detected
  - Whether lexicon + transliteration close the gap

Each failure mode maps to a different automated action:
  THRESHOLD_ISSUE  → config_service threshold adjustment (no retraining)
  LEXICON_GAP      → add entry to name_lexicon.py (automated PR / hot-reload)
  XLIT_GAP         → transliteration improvement (automated PR)
  OCR_CHAR_ERROR   → add to GOT-OCR training corpus (retrain)
  CLEAN            → score was fine, no action
  INDETERMINATE    → score too ambiguous to classify safely (skip)
"""
from __future__ import annotations
import pytest

from modules.cts.feedback.failure_classifier import (
    classify_failure,
    FailureMode,
    ClassificationResult,
)


class TestFailureMode:
    def test_high_score_is_clean(self):
        # Score above threshold → no error of any kind
        result = classify_failure(
            ocr_payee="Lata Deshpande",
            name_match_score=0.93,
            threshold=0.82,
            script="latin",
        )
        assert result.mode == FailureMode.CLEAN

    def test_score_just_below_threshold_is_threshold_issue(self):
        # Score in 0.72-0.82 zone → threshold too tight, not an OCR error
        result = classify_failure(
            ocr_payee="देशपांडे",
            name_match_score=0.78,
            threshold=0.82,
            script="devanagari",
        )
        assert result.mode == FailureMode.THRESHOLD_ISSUE

    def test_lexicon_gap_detected_for_malayalam_christian_name(self):
        # OCR read "ജോർജ്ജ്" correctly, but lexicon not applied → score low
        # Classifier should detect: applying lexicon would close the gap
        result = classify_failure(
            ocr_payee="ജോർജ്ജ്",
            name_match_score=0.52,          # what we'd get WITHOUT lexicon
            threshold=0.82,
            script="malayalam",
            cbs_display_initial="G",        # CBS holder starts with "G"
        )
        assert result.mode == FailureMode.LEXICON_GAP

    def test_ocr_char_error_when_score_very_low(self):
        # Score < 0.50 AND no lexicon/xlit fix can close it → OCR character error
        result = classify_failure(
            ocr_payee="रामश्वर",           # OCR misread 'े' → nothing (missing matra)
            name_match_score=0.41,
            threshold=0.82,
            script="devanagari",
        )
        assert result.mode == FailureMode.OCR_CHAR_ERROR

    def test_indeterminate_when_script_unknown(self):
        # Cannot classify if script detection failed
        result = classify_failure(
            ocr_payee="some text",
            name_match_score=0.60,
            threshold=0.82,
            script=None,
        )
        assert result.mode == FailureMode.INDETERMINATE

    def test_clean_for_micr_ngch_success(self):
        # NGCH accepted → MICR fields were correct → CLEAN for MICR
        result = classify_failure(
            ocr_payee="",
            name_match_score=1.0,
            threshold=0.82,
            script="latin",
            ngch_outcome="ACCEPTED",
        )
        assert result.mode == FailureMode.CLEAN

    def test_micr_error_on_ngch_rejection(self):
        # NGCH rejected with MICR error → OCR_CHAR_ERROR for MICR fields
        result = classify_failure(
            ocr_payee="",
            name_match_score=0.0,
            threshold=0.82,
            script="latin",
            ngch_outcome="REJECTED_MICR_ERROR",
        )
        assert result.mode == FailureMode.OCR_CHAR_ERROR

    def test_threshold_issue_has_no_corpus_action(self):
        result = classify_failure(
            ocr_payee="देशपांडे",
            name_match_score=0.78,
            threshold=0.82,
            script="devanagari",
        )
        assert result.add_to_corpus is False
        assert result.suggested_action == "adjust_threshold"

    def test_lexicon_gap_has_no_corpus_action(self):
        result = classify_failure(
            ocr_payee="ജോർജ്ജ്",
            name_match_score=0.52,
            threshold=0.82,
            script="malayalam",
            cbs_display_initial="G",
        )
        assert result.add_to_corpus is False
        assert result.suggested_action == "extend_lexicon"

    def test_ocr_char_error_triggers_corpus_action(self):
        result = classify_failure(
            ocr_payee="रामश्वर",
            name_match_score=0.41,
            threshold=0.82,
            script="devanagari",
        )
        assert result.add_to_corpus is True
        assert result.suggested_action == "retrain_ocr"

    def test_clean_no_action(self):
        result = classify_failure(
            ocr_payee="Ramesh Kumar",
            name_match_score=0.95,
            threshold=0.82,
            script="latin",
        )
        assert result.add_to_corpus is False
        assert result.suggested_action == "none"

    def test_result_contains_score_and_mode(self):
        result = classify_failure(
            ocr_payee="देशपांडे",
            name_match_score=0.78,
            threshold=0.82,
            script="devanagari",
        )
        assert isinstance(result, ClassificationResult)
        assert result.mode in list(FailureMode)
        assert result.score == 0.78

    def test_high_gap_below_50_is_ocr_even_if_indic(self):
        # Even with valid Indic script, very low score = OCR problem
        result = classify_failure(
            ocr_payee="కృతి",            # Telugu — plausible Indic sequence
            name_match_score=0.38,
            threshold=0.82,
            script="telugu",
        )
        assert result.mode == FailureMode.OCR_CHAR_ERROR
        assert result.add_to_corpus is True

    def test_human_review_approved_promotes_borderline(self):
        # Score was borderline (0.65-0.82) but human approved → XLIT_GAP not OCR error
        result = classify_failure(
            ocr_payee="சுப்பிரமணியன்",
            name_match_score=0.67,
            threshold=0.82,
            script="tamil",
            human_approved=True,
        )
        # Human approved → business said it's fine → probably xlit not OCR
        assert result.mode in (FailureMode.XLIT_GAP, FailureMode.THRESHOLD_ISSUE)
        assert result.add_to_corpus is False  # don't retrain OCR when human approved borderline


class TestFailureModeEnum:
    def test_all_modes_defined(self):
        modes = {m.value for m in FailureMode}
        assert "CLEAN" in modes
        assert "THRESHOLD_ISSUE" in modes
        assert "LEXICON_GAP" in modes
        assert "XLIT_GAP" in modes
        assert "OCR_CHAR_ERROR" in modes
        assert "INDETERMINATE" in modes
