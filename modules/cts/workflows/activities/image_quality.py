"""check_image_quality - return reason code 39 candidate. Deterministic, model-free, never raises."""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field
from temporalio import activity

from modules.cts.preprocessing.image_quality import IQAThresholds, assess_image_quality
from shared.observability.otel_setup import get_tracer
from shared.storage.image_fetch import fetch_image_bytes

log = structlog.get_logger()
tracer = get_tracer(__name__)


class IQAInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    instrument_id: str
    bank_id: str


class IQAActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                       # PASS | FAIL | UNAVAILABLE
    reason: Optional[str] = None
    metrics: dict = Field(default_factory=dict)


async def _thresholds(config_service) -> IQAThresholds:
    d = IQAThresholds()

    async def get(key, default, cast):
        try:
            v = await config_service.get(key)
            return cast(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
        except Exception:
            return default

    return IQAThresholds(
        min_width=await get("cts.iqa_min_width", d.min_width, int),
        min_height=await get("cts.iqa_min_height", d.min_height, int),
        min_sharpness=await get("cts.iqa_min_sharpness", d.min_sharpness, float),
        min_contrast=await get("cts.iqa_min_contrast", d.min_contrast, float),
        min_std=d.min_std,
    )


@activity.defn
async def check_image_quality(inp: IQAInput, config_service: Any = None) -> IQAActivityResult:
    with tracer.start_as_current_span("activity.check_image_quality") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        try:
            raw = await fetch_image_bytes(inp.image_url)
        except Exception as exc:
            log.warning("iqa.fetch_failed", instrument_id=inp.instrument_id, error=str(exc)[:120])
            return IQAActivityResult(outcome="UNAVAILABLE")
        r = assess_image_quality(raw, await _thresholds(config_service))
        if r.outcome == "FAIL":
            log.info("iqa.fail", instrument_id=inp.instrument_id, bank_id=inp.bank_id, reason=r.reason, **r.metrics)
        return IQAActivityResult(outcome=r.outcome, reason=r.reason, metrics=r.metrics)
