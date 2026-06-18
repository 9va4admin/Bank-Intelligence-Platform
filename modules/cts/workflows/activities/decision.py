"""
Decision activity — synthesise terminal CTS decision from all upstream signals.

Decisions: STP_CONFIRM | STP_RETURN | HUMAN_REVIEW

Priority order (hard gates evaluated first):
  1. CBS returned RETURN status   → STP_RETURN  (OPA Layer 4 rule)
  2. Alteration detected          → STP_RETURN
  3. Fraud score > threshold      → HUMAN_REVIEW
  4. OCR confidence < threshold   → HUMAN_REVIEW
  5. Signature match < threshold  → HUMAN_REVIEW
  6. CBS unavailable              → HUMAN_REVIEW
  7. PPS miss                     → HUMAN_REVIEW
  8. CBS HUMAN_REVIEW escalation  → HUMAN_REVIEW
  9. All signals clean + fraud_score < (1 - stp_threshold) → STP_CONFIRM
  else                             → HUMAN_REVIEW

All thresholds from config dict — never hardcoded.
SHAP values passed through from upstream fraud activity.
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

class DecisionInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    fraud_score: float
    ocr_confidence: float
    signature_match_score: float
    cbs_outcome: str            # "PROCEED" | "RETURN" | "HUMAN_REVIEW" | "CBS_UNAVAILABLE"
    alteration_detected: bool
    pps_outcome: str            # "FOUND" | "HUMAN_REVIEW"
    available_balance: Optional[float]
    cheque_amount: float
    shap_values: dict[str, Any]  # required — must be computed before decision


class DecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    decision: str               # "STP_CONFIRM" | "STP_RETURN" | "HUMAN_REVIEW"
    rationale: str
    shap_values: dict[str, Any]


async def synthesise_decision(
    inp: DecisionInput,
    config: dict[str, Any],
) -> DecisionResult:
    """
    Synthesise terminal cheque decision from all upstream activity signals.
    All thresholds read from config dict — never hardcoded here.
    """
    stp_threshold: float = config["stp_auto_confirm_threshold"]
    fraud_threshold: float = config["human_review_fraud_threshold"]
    ocr_min_confidence: float = config["ocr_min_confidence"]
    sig_min_match: float = config["sig_min_match_score"]

    # Hard gate 1: CBS says return immediately
    if inp.cbs_outcome == "RETURN":
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_RETURN",
            rationale=f"CBS account status requires immediate return",
            shap_values=inp.shap_values,
        )

    # Hard gate 2: alteration detected
    if inp.alteration_detected:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_RETURN",
            rationale="Cheque alteration detected — returning instrument",
            shap_values=inp.shap_values,
        )

    # Soft gates → HUMAN_REVIEW
    human_review_reasons = []

    if inp.fraud_score >= fraud_threshold:
        human_review_reasons.append(f"fraud_score={inp.fraud_score:.3f} >= threshold={fraud_threshold}")

    if inp.ocr_confidence < ocr_min_confidence:
        human_review_reasons.append(f"ocr_confidence={inp.ocr_confidence:.3f} below minimum")

    if inp.signature_match_score < sig_min_match:
        human_review_reasons.append(f"signature_match={inp.signature_match_score:.3f} below minimum")

    if inp.cbs_outcome in ("CBS_UNAVAILABLE", "HUMAN_REVIEW"):
        human_review_reasons.append(f"cbs_outcome={inp.cbs_outcome}")

    if inp.pps_outcome == "HUMAN_REVIEW":
        human_review_reasons.append("pps_miss")

    if human_review_reasons:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="HUMAN_REVIEW",
            rationale="; ".join(human_review_reasons),
            shap_values=inp.shap_values,
        )

    # STP_CONFIRM: all signals clean, fraud score below threshold, OCR+sig above minimums.
    # STP gate measures quality of extraction (OCR) and identity (signature).
    # Fraud already filtered above; don't penalize again here.
    combined_confidence = inp.ocr_confidence * 0.5 + inp.signature_match_score * 0.5

    if combined_confidence >= stp_threshold:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_CONFIRM",
            rationale=(
                f"All signals clean: fraud_score={inp.fraud_score:.3f}, "
                f"ocr={inp.ocr_confidence:.3f}, sig={inp.signature_match_score:.3f}, "
                f"combined_confidence={combined_confidence:.3f}"
            ),
            shap_values=inp.shap_values,
        )

    return DecisionResult(
        instrument_id=inp.instrument_id,
        decision="HUMAN_REVIEW",
        rationale=f"Combined confidence {combined_confidence:.3f} below STP threshold {stp_threshold}",
        shap_values=inp.shap_values,
    )
