"""
OCR activity — extract cheque fields via GOT-OCR2.0 (vLLM, cts-ocr queue).

Fields: MICR line, amount in figures, amount in words, date, payee, drawer.
Confidence below min_confidence → HUMAN_REVIEW.
vLLM unavailable → HUMAN_REVIEW (degraded), never crashes workflow.
"""
import json
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.sub_member.models import PrincipalTag
from modules.cts.sub_member.router import MICRPrefixRouter
from modules.cts.workflows.activities.amount_words_parser import amounts_match
from shared.ai.model_cascade import CascadeOrchestrator
from shared.utils.masking import mask_amount

log = structlog.get_logger()


class OCRActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    instrument_id: str
    bank_id: str


_OCR_PROMPT = """
Extract all printed fields from this cheque image. Return JSON only, no explanation:
{
  "micr_line": {"value": "...", "confidence": 0.0},
  "amount_figures": {"value": "...", "confidence": 0.0},
  "amount_words": {"value": "...", "confidence": 0.0},
  "date": {"value": "...", "confidence": 0.0},
  "payee": {"value": "...", "confidence": 0.0}
}
If a field is illegible, set value to null and confidence to 0.0.
Confidence range: 0.0 (illegible) to 1.0 (perfectly clear).
"""


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
    cascade_level: int = 2              # 1 = L1 used (7B fast), 2 = L2 used (full model)
    principal_tag: Optional[str] = None   # "DIRECT" | "SUB_MEMBER"
    sub_member_id: Optional[str] = None   # populated when principal_tag == "SUB_MEMBER"
    amount_mismatch: bool = False         # True when figures and words disagree


@activity.defn
async def ocr_extract(
    inp: OCRActivityInput,
    orchestrator: CascadeOrchestrator,
    config_service,
    routing_table: Optional[dict] = None,
) -> OCRActivityResult:
    """
    Extract cheque fields using GOT-OCR2.0 via the L1/L2 cascade orchestrator.
    Degrades to HUMAN_REVIEW on model failure or low confidence.
    """
    ai_config = await config_service.get_ai_config(inp.bank_id)
    min_confidence = ai_config["ai.ocr.min_confidence"]

    resolved_cascade_level = 2

    try:
        cascade_result = await orchestrator.call_ocr(
            image_url=inp.image_url,
            prompt=_OCR_PROMPT,
            cheque_amount=0.0,  # amount unknown at OCR time — only confidence gate applies
        )
        data = json.loads(cascade_result.content)
        resolved_cascade_level = cascade_result.cascade_level
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

    micr_line = data.get("micr_line", {}).get("value")
    principal_tag, sub_member_id = _route_micr(micr_line, routing_table, inp.instrument_id)

    if low_fields:
        log.info(
            "ocr_activity.low_confidence",
            instrument_id=inp.instrument_id,
            low_fields=low_fields,
        )
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=data.get("amount_figures", {}).get("value"),
            overall_confidence=overall,
            low_confidence_reason=f"low_confidence_fields: {low_fields}",
            cascade_level=resolved_cascade_level,
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
        )

    amount_figures_val = data.get("amount_figures", {}).get("value")
    amount_words_val = data.get("amount_words", {}).get("value")

    # Cross-check: amount in figures must match amount in words
    # None result means words were illegible — treat as unknown, continue to human review
    match = amounts_match(figures=amount_figures_val, words=amount_words_val)
    if match is False:
        log.info(
            "ocr_activity.amount_mismatch",
            instrument_id=inp.instrument_id,
        )
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=amount_figures_val,
            amount_words=amount_words_val,
            overall_confidence=overall,
            low_confidence_reason="amount_figures_words_mismatch",
            cascade_level=resolved_cascade_level,
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
            amount_mismatch=True,
        )

    return OCRActivityResult(
        outcome="PROCEED",
        micr_line=micr_line,
        amount_figures=amount_figures_val,
        amount_words=amount_words_val,
        date=data.get("date", {}).get("value"),
        payee=data.get("payee", {}).get("value"),
        overall_confidence=overall,
        cascade_level=resolved_cascade_level,
        principal_tag=principal_tag,
        sub_member_id=sub_member_id,
    )


def _route_micr(
    micr_line: Optional[str],
    routing_table: Optional[dict],
    instrument_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Identify principal tag from MICR line using MICRPrefixRouter.
    Returns (principal_tag_str, sub_member_id_str).
    Defaults to DIRECT when no micr_line or no routing_table is provided.
    """
    if not micr_line or not routing_table:
        return PrincipalTag.DIRECT.value, None

    try:
        router = MICRPrefixRouter(routing_table)
        tag, smb = router.identify(micr_line)
        sub_member_id = smb.sub_member_id if smb is not None else None
        return tag.value, sub_member_id
    except Exception as exc:
        log.warning(
            "ocr_activity.micr_routing_failed",
            instrument_id=instrument_id,
            error=str(exc),
        )
        return PrincipalTag.DIRECT.value, None
