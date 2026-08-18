"""Passive OCR feedback signal extractor.

Derives training-relevant signals from CTS workflow outputs that already
exist for every cheque processed — no extra human actions required.

Payee signal sources (automatic, passive):
  - payee_names_match score (from outward_payee_check or inward CBS comparison)
  - Workflow final decision (STP_CONFIRM / STP_RETURN / HUMAN_REVIEW / ...)
  - Human reviewer outcome if human review occurred (approve / return)
  - CBS degraded flag (excludes unreliable signals)
  - CBS holder first initial (masked — available from payee_display "G***")

MICR signal sources (automatic, passive):
  - NGCH outcome: ACCEPTED = strong positive label; REJECTED_MICR_ERROR = negative
  - Masked MICR fields (account last-4, IFSC) — raw account number never stored
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from modules.cts.feedback.failure_classifier import (
    classify_failure,
    FailureMode,
)


class SignalSource(str, Enum):
    STP_AUTO     = "STP_AUTO"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    NGCH_OUTCOME = "NGCH_OUTCOME"


@dataclass
class FeedbackSignal:
    # Identity
    instrument_id: str
    bank_id: str
    source: SignalSource

    # OCR artifact
    ocr_payee: str
    image_path: str

    # Match quality
    name_match_score: float
    failure_mode: Optional[FailureMode]

    # Corpus flag
    add_to_corpus: bool

    # Human signal (None = no human review)
    human_approved: Optional[bool] = None

    # MICR-specific
    micr_fields: dict = field(default_factory=dict)
    corpus_label: str = ""       # "positive" | "negative" | ""

    # Diagnostics
    rationale: str = ""


def extract_payee_signal(
    *,
    instrument_id: str,
    bank_id: str,
    ocr_payee: str,
    name_match_score: float,
    threshold: float,
    script: Optional[str],
    workflow_decision: str,
    human_approved: Optional[bool],
    image_path: str,
    cbs_degraded: bool = False,
    cbs_display_initial: Optional[str] = None,
) -> FeedbackSignal:
    """Extract a payee OCR feedback signal from a processed cheque's outputs.

    If CBS was degraded (unreachable), the name_match_score is unreliable and
    the signal is marked add_to_corpus=False regardless of the score.
    """
    source = (
        SignalSource.HUMAN_REVIEW
        if workflow_decision == "HUMAN_REVIEW"
        else SignalSource.STP_AUTO
    )

    # Unreliable signal — CBS down means score may be stale/wrong
    if cbs_degraded:
        return FeedbackSignal(
            instrument_id=instrument_id,
            bank_id=bank_id,
            source=source,
            ocr_payee=ocr_payee,
            image_path=image_path,
            name_match_score=name_match_score,
            failure_mode=FailureMode.INDETERMINATE,
            add_to_corpus=False,
            human_approved=human_approved,
            rationale="cbs_degraded — signal excluded",
        )

    classification = classify_failure(
        ocr_payee=ocr_payee,
        name_match_score=name_match_score,
        threshold=threshold,
        script=script,
        human_approved=human_approved,
        cbs_display_initial=cbs_display_initial,
    )

    return FeedbackSignal(
        instrument_id=instrument_id,
        bank_id=bank_id,
        source=source,
        ocr_payee=ocr_payee,
        image_path=image_path,
        name_match_score=name_match_score,
        failure_mode=classification.mode,
        add_to_corpus=classification.add_to_corpus,
        human_approved=human_approved,
        rationale=classification.rationale,
    )


def extract_micr_signal(
    *,
    instrument_id: str,
    bank_id: str,
    ngch_outcome: str,
    micr_fields: dict,
    image_path: str,
) -> FeedbackSignal:
    """Extract a MICR OCR feedback signal from NGCH filing outcome.

    NGCH acceptance/rejection is the strongest automated ground truth for
    MICR field accuracy — no human needed.

    micr_fields must contain masked values only (account last-4, not full number).
    """
    _assert_no_raw_account_numbers(micr_fields)

    is_positive = ngch_outcome == "ACCEPTED"
    is_negative = ngch_outcome == "REJECTED_MICR_ERROR"
    reliable    = is_positive or is_negative

    classification = classify_failure(
        ocr_payee="",
        name_match_score=1.0 if is_positive else 0.0,
        threshold=0.82,
        script="latin",
        ngch_outcome=ngch_outcome,
    )

    return FeedbackSignal(
        instrument_id=instrument_id,
        bank_id=bank_id,
        source=SignalSource.NGCH_OUTCOME,
        ocr_payee="",
        image_path=image_path,
        name_match_score=1.0 if is_positive else 0.0,
        failure_mode=classification.mode,
        add_to_corpus=reliable,
        micr_fields=micr_fields,
        corpus_label="positive" if is_positive else ("negative" if is_negative else ""),
        rationale=f"ngch_outcome={ngch_outcome}",
    )


def _assert_no_raw_account_numbers(fields: dict) -> None:
    import re
    for v in fields.values():
        if isinstance(v, str) and re.search(r'\d{10,}', v):
            raise ValueError(
                "Raw account number detected in micr_fields — mask to last-4 before calling"
            )
