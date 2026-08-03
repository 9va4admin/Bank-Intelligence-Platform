"""
CTS-2010 security feature presence activity — Vision LLM check.

Item 5: Detect whether the scanned cheque carries the mandatory RBI CTS-2010
security features:
  1. void_pantograph      — latent anti-photocopy "VOID" pattern
  2. rupee_symbol         — ₹ symbol security print / watermark
  3. micro_lettering      — micro-text (fine repeated text, typically "CTS" / bank name)
  4. printer_name_cts2010 — "CTS-2010" or NPCI-approved printer name printed on cheque

Applied primarily on the outward (presentee) path where the physical cheque is
available. Inward (drawee) path may also run this check but against the
NGCH-transmitted image (features may be harder to detect at transmission quality).

Outcomes:
  PROCEED      — all three features detected above min_confidence
  HUMAN_REVIEW — one or more features absent or confidence below threshold
  DEGRADED     — vLLM unavailable / JSON parse failure (never blocks clearing)

Graceful degradation: always returns DEGRADED (not raises) on any AI failure,
consistent with the "LLM down → human review" invariant from CLAUDE.md §12.

Mandatory AI rules (ai-inference.md):
  - OTel span with bank_id, model, queue attributes
  - Langfuse trace + gen.end() on every path (including degraded)
  - explicit queue='cts-vision' in extra_body
  - explicit timeout
  - thresholds from config_service, never hardcoded
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.security_features")

_MANDATORY_FEATURES = (
    "void_pantograph",
    "rupee_symbol",
    "micro_lettering",
    "printer_name_cts2010",
)

_VISION_PROMPT = """You are analysing an Indian bank cheque image for RBI CTS-2010 mandatory security features.

Examine the cheque carefully and report whether each of these four security features is present:

1. void_pantograph — a latent anti-photocopy pattern (usually shows "VOID" when photocopied, subtle on the original; look for a fine dot/line lattice background)
2. rupee_symbol — a ₹ (Rupee) symbol printed as a security element or watermark on the cheque
3. micro_lettering — very fine micro-text, often repeating "CTS" or the bank name, visible under magnification
4. printer_name_cts2010 — the text "CTS-2010" or the name of a NPCI-approved security printer printed on the cheque (commonly at the bottom-left or on the back; indicates the cheque was produced by a certified printer)

Respond ONLY with this exact JSON (no markdown, no explanation):
{
  "void_pantograph": {"present": true_or_false, "confidence": 0.0_to_1.0},
  "rupee_symbol": {"present": true_or_false, "confidence": 0.0_to_1.0},
  "micro_lettering": {"present": true_or_false, "confidence": 0.0_to_1.0},
  "printer_name_cts2010": {"present": true_or_false, "confidence": 0.0_to_1.0}
}

Set "present" to true only if the feature is clearly visible. Set "confidence" to reflect how certain you are.
If the image quality makes it impossible to determine, set "present" to false and "confidence" to 0.5."""


class SecurityFeaturesInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    image_url: str              # MinIO URL to front cheque image
    smb_id: Optional[str] = None


class SecurityFeaturesResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                                # "PROCEED" | "HUMAN_REVIEW" | "DEGRADED"
    features_detected: dict[str, bool] = {}     # e.g. {"void_pantograph": True, ...}
    missing_features: list[str] = []            # features absent or below confidence
    degraded: bool = False


@activity.defn
async def check_security_features(
    inp: SecurityFeaturesInput,
    vllm_client=None,
    config_service=None,
    langfuse=None,
) -> SecurityFeaturesResult:
    """
    Detect CTS-2010 security features on cheque image via Qwen2-VL.

    Never raises — degrades to DEGRADED on any AI failure.
    """
    with tracer.start_as_current_span("activity.check_security_features") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("model", "qwen2-vl-72b")
        span.set_attribute("queue", "cts-vision")

        if vllm_client is None:
            log.warning(
                "security_features.no_vllm_client",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            )
            span.set_attribute("ai.degraded", True)
            return SecurityFeaturesResult(outcome="DEGRADED", degraded=True)

        # Load thresholds from config_service (never hardcoded)
        ai_config = {}
        if config_service is not None:
            try:
                ai_config = await config_service.get_ai_config(inp.bank_id)
            except Exception:
                ai_config = {}
        min_confidence = float(ai_config.get("cts.security_features.min_confidence", 0.75))

        # Langfuse trace setup
        trace_obj = None
        gen = None
        if langfuse is not None:
            trace_obj = langfuse.trace(
                name="check_security_features",
                metadata={"bank_id": inp.bank_id, "instrument_id": inp.instrument_id},
            )
            gen = trace_obj.generation(
                name="qwen2vl_security_features",
                model="qwen2-vl-72b",
                input={"image_url": inp.image_url},
            )

        raw_content: Optional[str] = None
        try:
            response = await vllm_client.chat.completions.create(
                model="qwen2-vl-72b",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": inp.image_url},
                            },
                            {
                                "type": "text",
                                "text": _VISION_PROMPT,
                            },
                        ],
                    }
                ],
                extra_body={"queue": "cts-vision"},
                timeout=90.0,
            )
            raw_content = response.choices[0].message.content
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning(
                "security_features.vllm_error",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            if gen is not None:
                gen.end()
            span.set_attribute("ai.degraded", True)
            return SecurityFeaturesResult(outcome="DEGRADED", degraded=True)

        # Parse JSON response
        parsed: dict = {}
        try:
            # Strip markdown code fences if present
            content = raw_content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError, IndexError) as exc:
            log.warning(
                "security_features.parse_error",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                raw=raw_content[:200] if raw_content else "",
                error=str(exc),
            )
            if gen is not None:
                gen.end()
            span.set_attribute("ai.degraded", True)
            return SecurityFeaturesResult(outcome="DEGRADED", degraded=True)

        # Evaluate each mandatory feature
        features_detected: dict[str, bool] = {}
        missing_features: list[str] = []

        for feature in _MANDATORY_FEATURES:
            feature_data = parsed.get(feature, {})
            present = bool(feature_data.get("present", False))
            confidence = float(feature_data.get("confidence", 0.0))
            # Feature is "detected" only if present=True AND confidence >= min_confidence
            detected = present and confidence >= min_confidence
            features_detected[feature] = detected
            if not detected:
                missing_features.append(feature)

        if gen is not None:
            gen.end()

        outcome = "PROCEED" if not missing_features else "HUMAN_REVIEW"

        log.info(
            "security_features.result",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            outcome=outcome,
            missing=missing_features,
        )
        span.set_attribute("security_features.outcome", outcome)
        span.set_attribute("security_features.missing_count", len(missing_features))

        return SecurityFeaturesResult(
            outcome=outcome,
            features_detected=features_detected,
            missing_features=missing_features,
        )
