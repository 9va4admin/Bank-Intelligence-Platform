"""
Alteration detection activity — Qwen2-VL analyses cheque image for tampering.

Detects: overwriting, erasure, correction fluid, ink mismatch per field.
alteration_detected=True → STP_RETURN in decision activity.
Model unavailable → degraded=True, requires_human_review=True (not auto-return).
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class AlterationActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    instrument_id: str
    bank_id: str


class AlterationActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    alteration_detected: bool
    tamper_risk_score: float = 0.0
    altered_fields: list[str] = []
    requires_human_review: bool = False
    degraded: bool = False


async def detect_alteration(
    inp: AlterationActivityInput,
    vllm_client=None,
) -> AlterationActivityResult:
    """
    Detect physical cheque alterations using Qwen2-VL vision model.
    Degrades gracefully on model failure — never assumes alteration without evidence.
    """
    try:
        data = await vllm_client.analyse(inp.image_url)
    except Exception as exc:
        log.warning(
            "alteration_activity.model_unavailable",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return AlterationActivityResult(
            alteration_detected=False,
            tamper_risk_score=0.0,
            requires_human_review=True,
            degraded=True,
        )

    return AlterationActivityResult(
        alteration_detected=data.get("alteration_detected", False),
        tamper_risk_score=data.get("tamper_risk", 0.0),
        altered_fields=data.get("altered_fields", []),
        requires_human_review=data.get("alteration_detected", False),
    )
