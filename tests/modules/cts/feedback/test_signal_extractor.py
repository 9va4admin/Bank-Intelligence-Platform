"""Tests for passive signal extraction from existing activity outputs.

The extractor reads decision payloads already produced by the CTS workflow
and derives OCR feedback signals with zero extra human work.

Signal sources (all already exist in every run):
  - PayeeMatchResult from payee_names_match (score, normalized forms, script)
  - CBSActivityResult.outcome (PROCEED / RETURN / CBS_UNAVAILABLE)
  - Decision + who made it (STP auto vs human review)
  - NGCH outcome (ACCEPTED / REJECTED_*)
  - MinIO image path for the instrument
"""
from __future__ import annotations
import pytest

from modules.cts.feedback.signal_extractor import (
    extract_payee_signal,
    extract_micr_signal,
    FeedbackSignal,
    SignalSource,
)


class TestExtractPayeeSignal:
    def test_stp_confirm_at_high_score_is_clean(self):
        sig = extract_payee_signal(
            instrument_id="CHQ-001",
            bank_id="saraswat-coop",
            ocr_payee="Ramesh Kumar",
            name_match_score=0.94,
            threshold=0.82,
            script="latin",
            workflow_decision="STP_CONFIRM",
            human_approved=False,
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-001.tiff",
        )
        assert sig.source == SignalSource.STP_AUTO
        assert sig.name_match_score == 0.94
        assert sig.add_to_corpus is False

    def test_human_review_approved_with_borderline_score(self):
        sig = extract_payee_signal(
            instrument_id="CHQ-002",
            bank_id="saraswat-coop",
            ocr_payee="देशपांडे",
            name_match_score=0.77,
            threshold=0.82,
            script="devanagari",
            workflow_decision="HUMAN_REVIEW",
            human_approved=True,
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-002.tiff",
        )
        assert sig.source == SignalSource.HUMAN_REVIEW
        assert sig.human_approved is True
        assert sig.add_to_corpus is False   # threshold/xlit issue, not OCR

    def test_very_low_score_stp_return_is_corpus_candidate(self):
        # Score so low it shouldn't have even been attempted → OCR character error
        sig = extract_payee_signal(
            instrument_id="CHQ-003",
            bank_id="saraswat-coop",
            ocr_payee="रामश्वर",
            name_match_score=0.39,
            threshold=0.82,
            script="devanagari",
            workflow_decision="STP_RETURN",
            human_approved=False,
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-003.tiff",
        )
        assert sig.add_to_corpus is True
        assert sig.image_path == "minio://cts-images/saraswat-coop/2026/08/CHQ-003.tiff"

    def test_cbs_unavailable_excluded_from_corpus(self):
        # Cannot generate reliable feedback if CBS was unreachable — score may be stale
        sig = extract_payee_signal(
            instrument_id="CHQ-004",
            bank_id="saraswat-coop",
            ocr_payee="Krishnan Nair",
            name_match_score=0.55,
            threshold=0.82,
            script="latin",
            workflow_decision="HUMAN_REVIEW",
            human_approved=None,        # reviewer not reached yet
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-004.tiff",
            cbs_degraded=True,
        )
        assert sig.add_to_corpus is False   # unreliable signal

    def test_signal_contains_failure_mode(self):
        sig = extract_payee_signal(
            instrument_id="CHQ-005",
            bank_id="saraswat-coop",
            ocr_payee="रामश्वर",
            name_match_score=0.39,
            threshold=0.82,
            script="devanagari",
            workflow_decision="STP_RETURN",
            human_approved=False,
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-005.tiff",
        )
        from modules.cts.feedback.failure_classifier import FailureMode
        assert sig.failure_mode is not None
        assert sig.failure_mode in list(FailureMode)

    def test_malayalam_christian_name_lexicon_gap_signal(self):
        sig = extract_payee_signal(
            instrument_id="CHQ-006",
            bank_id="federal-bank",
            ocr_payee="ജോർജ്ജ്",
            name_match_score=0.52,
            threshold=0.82,
            script="malayalam",
            workflow_decision="HUMAN_REVIEW",
            human_approved=True,
            image_path="minio://cts-images/federal-bank/2026/08/CHQ-006.tiff",
            cbs_display_initial="G",
        )
        from modules.cts.feedback.failure_classifier import FailureMode
        assert sig.failure_mode == FailureMode.LEXICON_GAP
        assert sig.add_to_corpus is False

    def test_instrument_id_and_bank_id_preserved(self):
        sig = extract_payee_signal(
            instrument_id="CHQ-007",
            bank_id="saraswat-coop",
            ocr_payee="Suresh",
            name_match_score=0.91,
            threshold=0.82,
            script="latin",
            workflow_decision="STP_CONFIRM",
            human_approved=False,
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-007.tiff",
        )
        assert sig.instrument_id == "CHQ-007"
        assert sig.bank_id == "saraswat-coop"


class TestExtractMicrSignal:
    def test_ngch_accepted_is_positive_micr_signal(self):
        sig = extract_micr_signal(
            instrument_id="CHQ-010",
            bank_id="saraswat-coop",
            ngch_outcome="ACCEPTED",
            micr_fields={"account_number": "****4521", "ifsc": "SRCB0000001"},
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-010.tiff",
        )
        assert sig.add_to_corpus is True    # NGCH accepted = strong positive label
        assert sig.corpus_label == "positive"

    def test_ngch_rejected_micr_is_negative_corpus_signal(self):
        sig = extract_micr_signal(
            instrument_id="CHQ-011",
            bank_id="saraswat-coop",
            ngch_outcome="REJECTED_MICR_ERROR",
            micr_fields={"account_number": "****9999", "ifsc": "SRCB0000001"},
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-011.tiff",
        )
        assert sig.add_to_corpus is True
        assert sig.corpus_label == "negative"

    def test_ngch_network_error_excluded(self):
        sig = extract_micr_signal(
            instrument_id="CHQ-012",
            bank_id="saraswat-coop",
            ngch_outcome="NETWORK_ERROR",
            micr_fields={"account_number": "****1234"},
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-012.tiff",
        )
        assert sig.add_to_corpus is False   # unreliable — not a MICR verdict

    def test_micr_signal_preserves_masked_fields(self):
        sig = extract_micr_signal(
            instrument_id="CHQ-013",
            bank_id="saraswat-coop",
            ngch_outcome="ACCEPTED",
            micr_fields={"account_number": "****4521", "ifsc": "SRCB0000001"},
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-013.tiff",
        )
        # Raw account number must NOT appear in signal
        assert "****4521" in str(sig.micr_fields)
        assert not any(
            len(v) > 4 and v.isdigit()
            for v in sig.micr_fields.values()
            if isinstance(v, str)
        )


class TestFeedbackSignalSchema:
    def test_feedback_signal_is_dataclass_or_pydantic(self):
        import dataclasses
        assert dataclasses.is_dataclass(FeedbackSignal) or hasattr(FeedbackSignal, "model_fields")

    def test_signal_source_enum_has_expected_values(self):
        values = {s.value for s in SignalSource}
        assert "STP_AUTO" in values
        assert "HUMAN_REVIEW" in values
        assert "NGCH_OUTCOME" in values
