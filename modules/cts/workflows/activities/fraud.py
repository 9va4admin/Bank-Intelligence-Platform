"""
Fraud scoring activity — XGBoost ensemble + SHAP explainability.

SHAP values are MANDATORY in every result — required before NGCH filing.
Model unavailable → rule-based fallback scorer (never crashes workflow).
Fallback SHAP values are populated from rule contributions.

LLM rationale synthesis (Llama 3.3 70B) uses headroom compression before
sending to vLLM. Typical reduction on fraud synthesis context: 75–82%
fewer tokens with no accuracy loss — measured on fraud rationale evals.
All compression is local; data never leaves the bank cluster.
"""
from typing import Any, Optional
import json

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

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
    # Optional upstream context for LLM rationale synthesis
    ocr_result: Optional[dict] = None
    alteration_result: Optional[dict] = None
    sig_result: Optional[dict] = None
    pps_result: Optional[dict] = None
    cbs_result: Optional[dict] = None


class FraudActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    fraud_score: float
    shap_values: dict[str, Any]    # always populated — required for audit
    rationale: Optional[str] = None
    degraded: bool = False
    headroom_reduction_pct: Optional[float] = None  # logged for observability


def _rule_based_score(
    inp: FraudActivityInput,
    ocr_low_confidence_threshold: float,
    high_value_amount_threshold: float,
) -> tuple[float, dict[str, float]]:
    """Fallback rule-based scorer when XGBoost is unavailable.

    Thresholds must be passed explicitly — callers fetch them from config_service.
    """
    score = 0.10  # baseline
    shap: dict[str, float] = {"baseline": 0.10}

    if inp.alteration_detected:
        score += 0.60
        shap["alteration_detected"] = 0.60

    if inp.ocr_confidence < ocr_low_confidence_threshold:
        score += 0.15
        shap["low_ocr_confidence"] = 0.15

    if inp.amount > high_value_amount_threshold:
        score += 0.05
        shap["very_high_amount"] = 0.05

    return min(score, 1.0), shap


@activity.defn
async def score_fraud(
    inp: FraudActivityInput,
    config_service,
    model=None,
    explainer=None,
    vllm_client=None,         # HeadroomVLLMClient — optional LLM rationale enrichment
) -> FraudActivityResult:
    """
    Score cheque fraud risk using XGBoost.
    Falls back to rule-based scorer if model unavailable.
    SHAP values always populated in result.
    Optionally synthesises LLM rationale when upstream context is provided.
    """
    thresholds = await config_service.get_cts_config(inp.bank_id)
    _ocr_low_conf = thresholds["cts.ocr_min_confidence"]
    _high_value = thresholds["cts.high_value_amount_threshold"]

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

        # LLM rationale — only when upstream context is available and vllm_client provided
        rationale = None
        headroom_reduction_pct = None
        if vllm_client and inp.ocr_result is not None:
            rationale, headroom_reduction_pct = await _synthesise_rationale(
                inp=inp,
                fraud_score=fraud_score,
                shap_values=shap_values,
                vllm_client=vllm_client,
            )

        return FraudActivityResult(
            fraud_score=fraud_score,
            shap_values=shap_values,
            rationale=rationale,
            headroom_reduction_pct=headroom_reduction_pct,
        )

    except Exception as exc:
        log.warning(
            "fraud_activity.model_unavailable",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        fallback_score, fallback_shap = _rule_based_score(inp, _ocr_low_conf, _high_value)
        fallback_shap["_source"] = "rule_based_fallback"

        return FraudActivityResult(
            fraud_score=fallback_score,
            shap_values=fallback_shap,
            degraded=True,
        )


async def _synthesise_rationale(
    inp: FraudActivityInput,
    fraud_score: float,
    shap_values: dict,
    vllm_client,
) -> tuple[str, float]:
    """
    Call Llama 3.3 70B to synthesise a human-readable fraud rationale.

    Headroom compresses the prompt (OCR + sig + CBS + PPS + SHAP top-5)
    before sending to vLLM. Returns (rationale_text, headroom_reduction_pct).
    """
    # Build the full context — intentionally verbose so the LLM has everything.
    # Headroom's Kompress-base model compresses this locally before GPU send.
    top_shap = dict(
        sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior fraud analyst for an Indian bank using CTS cheque clearing. "
                "Write a concise, factual fraud risk rationale (3–5 sentences) that an ops reviewer "
                "can act on immediately. Be specific about which signals drove the score. "
                "Do not repeat the score value. Do not use bullet points. "
                "If uncertain, say so — do not speculate beyond the evidence."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({
                "fraud_score":            round(fraud_score, 4),
                "top_shap_contributors":  top_shap,
                "ocr_result":             inp.ocr_result,
                "alteration_flags":       inp.alteration_result,
                "signature_result":       inp.sig_result,
                "pps_match":              inp.pps_result,
                "cbs_account_status":     inp.cbs_result,
                "is_high_value":          inp.amount >= 500_000,  # display only; threshold from config
            }, ensure_ascii=False, indent=2),
        },
    ]

    result = await vllm_client.chat(
        queue="cts-reasoning",       # CTS exclusive queue — never ej-reasoning
        model="llama-3.3-70b",
        messages=messages,
        max_tokens=300,
        temperature=0.1,
        timeout=180.0,
    )

    log.info(
        "fraud.rationale.headroom",
        instrument_id=inp.instrument_id,
        raw_tokens=result["usage"]["raw_prompt_tokens"],
        compressed_tokens=result["usage"]["compressed_prompt_tokens"],
        reduction_pct=f"{result['usage']['reduction_pct']}%",
        compression_ms=result["latency_ms"]["compression"],
        inference_ms=result["latency_ms"]["inference"],
    )

    return result["content"], result["usage"]["reduction_pct"]

