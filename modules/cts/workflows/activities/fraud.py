"""
Fraud scoring activity — XGBoost ensemble + SHAP explainability.

SHAP values are MANDATORY in every result — required before NGCH filing.
Model unavailable → rule-based fallback scorer (never crashes workflow).
Fallback SHAP values are populated from rule contributions.
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class FraudActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    amount: float
    micr_line: str
    ocr_confidence: float
    alteration_detected: bool
    account_last4: str


class FraudActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    fraud_score: float
    shap_values: dict[str, Any]    # always populated — required for audit
    degraded: bool = False


def _rule_based_score(inp: FraudActivityInput) -> tuple[float, dict[str, float]]:
    """Fallback rule-based scorer when XGBoost is unavailable."""
    score = 0.10  # baseline
    shap: dict[str, float] = {"baseline": 0.10}

    if inp.alteration_detected:
        score += 0.60
        shap["alteration_detected"] = 0.60

    if inp.ocr_confidence < 0.70:
        score += 0.15
        shap["low_ocr_confidence"] = 0.15

    if inp.amount > 5_000_000:
        score += 0.05
        shap["very_high_amount"] = 0.05

    return min(score, 1.0), shap


async def score_fraud(
    inp: FraudActivityInput,
    model=None,
    explainer=None,
) -> FraudActivityResult:
    """
    Score cheque fraud risk using XGBoost.
    Falls back to rule-based scorer if model unavailable.
    SHAP values always populated in result.
    """
    features = [inp.amount, inp.ocr_confidence, 1.0 if inp.alteration_detected else 0.0]
    feature_names = getattr(model, "feature_names", ["amount", "ocr_confidence", "alteration_flag"])

    try:
        proba = model.predict_proba([features])[0]
        fraud_score = float(proba[1])

        raw_shap = explainer.shap_values([features])
        shap_values = {
            feature_names[i]: float(raw_shap[0][i])
            for i in range(len(feature_names))
        }

        return FraudActivityResult(fraud_score=fraud_score, shap_values=shap_values)

    except Exception as exc:
        log.warning(
            "fraud_activity.model_unavailable",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        fallback_score, fallback_shap = _rule_based_score(inp)
        fallback_shap["_source"] = "rule_based_fallback"

        return FraudActivityResult(
            fraud_score=fallback_score,
            shap_values=fallback_shap,
            degraded=True,
        )
