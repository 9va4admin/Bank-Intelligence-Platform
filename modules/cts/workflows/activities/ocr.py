"""
OCR activity — extract cheque fields via GOT-OCR2.0 (vLLM, cts-ocr queue).

Fields: MICR line, amount in figures, amount in words, date, payee, drawer.
Confidence below min_confidence → HUMAN_REVIEW.
vLLM unavailable → HUMAN_REVIEW (degraded), never crashes workflow.
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class OCRActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    instrument_id: str
    bank_id: str


class OCRActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "PROCEED" | "HUMAN_REVIEW"
    micr_line: Optional[str] = None
    amount_figures: Optional[str] = None
    amount_words: Optional[str] = None
    date: Optional[str] = None
    payee: Optional[str] = None
    overall_confidence: float = 0.0
    low_confidence_reason: Optional[str] = None
    degraded: bool = False


async def ocr_extract(
    inp: OCRActivityInput,
    vllm_client=None,
    min_confidence: float = 0.85,
) -> OCRActivityResult:
    """
    Extract cheque fields using GOT-OCR2.0.
    Degrades to HUMAN_REVIEW on model failure or low confidence.
    """
    try:
        data = await vllm_client.extract(inp.image_url)
    except Exception as exc:
        log.warning(
            "ocr_activity.model_unavailable",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            degraded=True,
            low_confidence_reason="MODEL_UNAVAILABLE",
        )

    confidences = [
        v["confidence"]
        for v in data.values()
        if isinstance(v, dict) and "confidence" in v
    ]
    overall = sum(confidences) / len(confidences) if confidences else 0.0

    low_fields = [k for k, v in data.items() if isinstance(v, dict) and v.get("confidence", 1.0) < min_confidence]

    if low_fields:
        log.info(
            "ocr_activity.low_confidence",
            instrument_id=inp.instrument_id,
            low_fields=low_fields,
        )
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=data.get("micr_line", {}).get("value"),
            amount_figures=data.get("amount_figures", {}).get("value"),
            overall_confidence=overall,
            low_confidence_reason=f"low_confidence_fields: {low_fields}",
        )

    return OCRActivityResult(
        outcome="PROCEED",
        micr_line=data.get("micr_line", {}).get("value"),
        amount_figures=data.get("amount_figures", {}).get("value"),
        amount_words=data.get("amount_words", {}).get("value"),
        date=data.get("date", {}).get("value"),
        payee=data.get("payee", {}).get("value"),
        overall_confidence=overall,
    )
