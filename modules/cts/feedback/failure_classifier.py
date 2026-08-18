"""Automated OCR failure mode classifier — zero human input required.

Classifies every payee mismatch event using signals already present in the
CTS workflow output. Determines the root cause and the correct automated
action without any labeling task.

Decision tree (fully automated):

  score >= threshold          → CLEAN       (no action)
  NGCH rejected MICR          → OCR_CHAR_ERROR  (retrain MICR model)
  NGCH accepted               → CLEAN

  For payee name mismatches:
    score ∈ [threshold-0.10, threshold)
      AND human_approved OR (human_approved is None)
                            → THRESHOLD_ISSUE  (adjust config, no retrain)

    script = "malayalam"
      AND cbs_display_initial known
      AND lexicon would produce word starting with that initial
                            → LEXICON_GAP      (extend lexicon, no retrain)

    score ∈ [0.50, threshold-0.10)
      AND human_approved    → XLIT_GAP         (improve transliteration)

    score < 0.50            → OCR_CHAR_ERROR   (add to training corpus)

    script is None          → INDETERMINATE    (skip)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FailureMode(str, Enum):
    CLEAN            = "CLEAN"
    THRESHOLD_ISSUE  = "THRESHOLD_ISSUE"
    LEXICON_GAP      = "LEXICON_GAP"
    XLIT_GAP         = "XLIT_GAP"
    OCR_CHAR_ERROR   = "OCR_CHAR_ERROR"
    INDETERMINATE    = "INDETERMINATE"


_ACTION_MAP: dict[FailureMode, str] = {
    FailureMode.CLEAN:           "none",
    FailureMode.THRESHOLD_ISSUE: "adjust_threshold",
    FailureMode.LEXICON_GAP:     "extend_lexicon",
    FailureMode.XLIT_GAP:        "improve_xlit",
    FailureMode.OCR_CHAR_ERROR:  "retrain_ocr",
    FailureMode.INDETERMINATE:   "skip",
}

_CORPUS_MODES: frozenset[FailureMode] = frozenset({FailureMode.OCR_CHAR_ERROR})


@dataclass(frozen=True)
class ClassificationResult:
    mode: FailureMode
    score: float
    suggested_action: str
    add_to_corpus: bool
    rationale: str


def classify_failure(
    ocr_payee: str,
    name_match_score: float,
    threshold: float,
    script: Optional[str],
    *,
    ngch_outcome: Optional[str] = None,
    human_approved: Optional[bool] = None,
    cbs_display_initial: Optional[str] = None,
) -> ClassificationResult:
    """Classify the failure mode from signals available without human labeling.

    Parameters
    ----------
    ocr_payee:
        Raw text from the OCR engine for the payee field.
    name_match_score:
        Jaro-Winkler score from payee_names_match (0.0–1.0).
    threshold:
        The configured payee_match_threshold for this bank (from config_service).
    script:
        Script detected by identify_indic_script, or None if detection failed.
    ngch_outcome:
        If set, overrides payee-score logic. "ACCEPTED" → CLEAN;
        "REJECTED_MICR_ERROR" → OCR_CHAR_ERROR.
    human_approved:
        True if human reviewer approved the instrument; False if returned;
        None if no human review took place.
    cbs_display_initial:
        First letter of the CBS holder name (masked — only initial available).
        Used for lexicon gap detection.
    """
    # ── NGCH path — MICR field feedback ─────────────────────────────────────
    if ngch_outcome is not None:
        if ngch_outcome == "ACCEPTED":
            return _result(FailureMode.CLEAN, name_match_score, "ngch accepted — micr correct")
        if ngch_outcome == "REJECTED_MICR_ERROR":
            return _result(FailureMode.OCR_CHAR_ERROR, name_match_score, "ngch rejected micr")
        # Network error or other non-MICR rejection → indeterminate
        return _result(FailureMode.INDETERMINATE, name_match_score, f"ngch outcome={ngch_outcome}")

    # ── Script unknown ───────────────────────────────────────────────────────
    if script is None:
        return _result(FailureMode.INDETERMINATE, name_match_score, "script detection failed")

    # ── Score above threshold ────────────────────────────────────────────────
    if name_match_score >= threshold:
        return _result(FailureMode.CLEAN, name_match_score, "score above threshold")

    gap = threshold - name_match_score

    # ── Threshold zone (score just below, human approved or untested) ────────
    if gap < 0.10 and human_approved is not False:
        return _result(
            FailureMode.THRESHOLD_ISSUE, name_match_score,
            f"score {name_match_score:.3f} within 0.10 of threshold {threshold:.3f}",
        )

    # ── Malayalam lexicon gap ────────────────────────────────────────────────
    if script == "malayalam" and _lexicon_would_fix(ocr_payee, cbs_display_initial):
        return _result(
            FailureMode.LEXICON_GAP, name_match_score,
            "malayalam name likely in lexicon — extend name_lexicon.py",
        )

    # ── Human approved borderline — xlit issue, not OCR ─────────────────────
    if human_approved is True and name_match_score >= 0.50:
        return _result(
            FailureMode.XLIT_GAP, name_match_score,
            "human approved despite low score — transliteration gap, not OCR error",
        )

    # ── Very low score — OCR character error ────────────────────────────────
    if name_match_score < 0.50:
        return _result(
            FailureMode.OCR_CHAR_ERROR, name_match_score,
            f"score {name_match_score:.3f} below 0.50 — likely OCR character substitution",
        )

    # ── Mid-range score, no human signal, xlit gap ──────────────────────────
    return _result(
        FailureMode.XLIT_GAP, name_match_score,
        "mid-range score without definitive signal — probable transliteration gap",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _result(mode: FailureMode, score: float, rationale: str) -> ClassificationResult:
    return ClassificationResult(
        mode=mode,
        score=score,
        suggested_action=_ACTION_MAP[mode],
        add_to_corpus=mode in _CORPUS_MODES,
        rationale=rationale,
    )


def _lexicon_would_fix(ocr_payee: str, cbs_initial: Optional[str]) -> bool:
    """Heuristic: Malayalam Christian name in lexicon would bring score to 1.0.

    Checks whether the OCR token appears in the Malayalam lexicon AND (if we
    have the CBS initial) whether the lexicon form starts with that initial.
    This avoids false positives (matching a Hindu name that happens to be in the
    lexicon list) by cross-referencing with the CBS holder's known first letter.
    """
    if not ocr_payee:
        return False
    try:
        from modules.cts.preprocessing.name_lexicon import _MALAYALAM_LEXICON
    except ImportError:
        return False

    tokens = ocr_payee.strip().split()
    for token in tokens:
        canonical = _MALAYALAM_LEXICON.get(token)
        if canonical is None:
            continue
        if cbs_initial is None:
            return True  # no initial to cross-check — assume lexicon gap
        if canonical[0].lower() == cbs_initial.strip().lower():
            return True
    return False
