"""
UV Security Analysis Activity — CTS Outward (Presentee Bank).

Analyses the UV-wavelength scan of a cheque to verify three mandatory
physical security features embedded during paper manufacturing:

  1. PENTOGRAPH (pantograph)
     Background security print using UV-reactive ink.
     Authentic cheques show a specific UV-ink response pattern.
     Forged cheques (colour photocopies, inkjet prints) lack this pattern
     or show uniform UV fluorescence where the pattern should be differential.

  2. SECURITY THREAD
     Plastic or metallic strip embedded in the paper during manufacture.
     UV-fluorescent threads glow bright under UV lamp.
     Metallic threads appear as dark non-fluorescent stripe.
     Absence or wrong position indicates paper substitution / forgery.

  3. UV WATERMARK
     Bank-specific ghost image embedded in the paper by the paper mill.
     Only visible under UV light (invisible to photocopiers and scanners
     under normal light). Each bank has a unique watermark design.
     Forged cheques printed on plain paper lack this entirely.

ALL THREE must pass for uv_security_passed=True.

Graceful degradation:
  - UV image absent (scanner has no UV lamp): degraded=True,
    requires_human_review=True — cannot certify, cannot fail.
  - vLLM/HF model unavailable: same degradation.
  - Malformed JSON from model: same degradation.

High-value cheques (above config threshold) always trigger human review
regardless of UV result — extra eyes on large-value instruments.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field
from temporalio import activity

log = structlog.get_logger()

_HIGH_VALUE_FALLBACK = 500_000.0  # used only when config_service is absent (tests)


# ── Prompt ────────────────────────────────────────────────────────────────────

_UV_SECURITY_PROMPT = """You are a forensic document security specialist analysing
a UV (ultraviolet) wavelength scan of a bank cheque.

Under UV light, genuine Indian bank cheques (CTS-2010 standard) show THREE
distinct security features. Analyse each one carefully:

1. PENTOGRAPH (background security pattern)
   - Authentic cheques: differential UV-ink response creating a latent pattern
     (typically shows bank name or "VOID" under copy/UV).
   - Forged (colour photocopy): uniform fluorescence, no pattern variation.
   - Forged (inkjet): random fluorescent speckles, no structured pattern.
   Assess: Is the UV-ink differential pattern present and consistent?

2. SECURITY THREAD
   - Embedded strip in the paper (not printed on surface).
   - UV-fluorescent type: glows as a bright continuous vertical stripe.
   - Metallic type: appears as a dark non-fluorescent vertical stripe.
   - Position: typically 1/3 from left edge on CTS paper.
   - Forged (plain paper): no thread, or printed line on surface only.
   Assess: Is a genuine embedded thread present? Where is it?

3. UV WATERMARK
   - Ghost image embedded during paper manufacture, visible ONLY under UV.
   - Genuine: clear ghost image, usually bank name or RBI emblem.
   - Forged (inkjet/laser print): absent entirely, or faint uniform glow.
   - Photocopied: absent — the copy machine cannot reproduce UV-embedded features.
   Assess: Is the watermark ghost image clearly visible and authentic-looking?

Return ONLY valid JSON in this exact structure:
{
  "pentograph": {
    "authentic": true,
    "confidence": 0.96,
    "notes": "brief observation"
  },
  "security_thread": {
    "present": true,
    "confidence": 0.98,
    "position": "vertical_center_left_third",
    "notes": "brief observation"
  },
  "uv_watermark": {
    "present": true,
    "confidence": 0.94,
    "notes": "brief observation"
  },
  "overall_uv_risk_score": 0.03,
  "requires_human_review": false
}

overall_uv_risk_score: 0.0 = definitely genuine, 1.0 = definite forgery.
If any feature is absent or suspicious, set requires_human_review to true.
Return JSON only — no prose before or after."""


# ── Models ────────────────────────────────────────────────────────────────────

class UVSecurityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    uv_image_url: str               # MinIO URL of UV scan
    cheque_amount: float = 0.0      # for high-value routing


class UVSecurityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Per-check results
    pentograph_authentic: bool = False
    pentograph_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pentograph_notes: str = ""

    security_thread_present: bool = False
    security_thread_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    security_thread_position: Optional[str] = None
    security_thread_notes: str = ""

    uv_watermark_present: bool = False
    uv_watermark_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uv_watermark_notes: str = ""

    # Overall
    uv_security_passed: bool = False    # True only when ALL three checks pass
    uv_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_human_review: bool = False
    degraded: bool = False              # model/image unavailable


# ── Activity ──────────────────────────────────────────────────────────────────

@activity.defn
async def analyze_uv_security(
    inp: UVSecurityInput,
    orchestrator: Any = None,       # worker-level DI: CascadeOrchestrator
    config_service: Any = None,     # worker-level DI: ConfigService
) -> UVSecurityResult:
    """
    Run UV security checks on the UV-wavelength cheque image.

    Uses vision LLM (cts-vision queue) to analyse three physical security
    features. Gracefully degrades if the model or image is unavailable.
    """
    cts_config = {}
    if config_service is not None:
        try:
            cts_config = await config_service.get_cts_config(inp.bank_id)
        except Exception:
            pass
    high_value_limit: float = float(cts_config.get("high_value_amount_threshold", _HIGH_VALUE_FALLBACK))

    if orchestrator is None:
        log.warning(
            "uv_security.no_orchestrator",
            instrument_id=inp.instrument_id,
        )
        return UVSecurityResult(degraded=True, requires_human_review=True)

    # ── call vision LLM ───────────────────────────────────────────────────
    try:
        vision_result = await orchestrator.call_vision(
            image_url=inp.uv_image_url,
            prompt=_UV_SECURITY_PROMPT,
            cheque_amount=inp.cheque_amount,
        )
        data = json.loads(vision_result.content)
    except Exception as exc:
        log.warning(
            "uv_security.model_failed",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return UVSecurityResult(degraded=True, requires_human_review=True)

    # ── parse per-check results ───────────────────────────────────────────
    try:
        pento   = data.get("pentograph", {})
        thread  = data.get("security_thread", {})
        wm      = data.get("uv_watermark", {})

        pentograph_authentic     = bool(pento.get("authentic", False))
        pentograph_confidence    = _clamp(float(pento.get("confidence", 0.0)))
        pentograph_notes         = str(pento.get("notes", ""))

        thread_present           = bool(thread.get("present", False))
        thread_confidence        = _clamp(float(thread.get("confidence", 0.0)))
        thread_position          = thread.get("position") or None
        thread_notes             = str(thread.get("notes", ""))

        watermark_present        = bool(wm.get("present", False))
        watermark_confidence     = _clamp(float(wm.get("confidence", 0.0)))
        watermark_notes          = str(wm.get("notes", ""))

        uv_risk_score            = _clamp(float(data.get("overall_uv_risk_score", 0.0)))
        model_wants_review       = bool(data.get("requires_human_review", False))

    except Exception as exc:
        log.warning(
            "uv_security.parse_failed",
            instrument_id=inp.instrument_id,
            error=str(exc),
        )
        return UVSecurityResult(degraded=True, requires_human_review=True)

    # ── all three must pass ───────────────────────────────────────────────
    uv_passed = pentograph_authentic and thread_present and watermark_present

    # high-value always requires human review regardless of UV result
    is_high_value = inp.cheque_amount >= high_value_limit
    requires_review = model_wants_review or not uv_passed or is_high_value

    log.info(
        "uv_security.complete",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        uv_passed=uv_passed,
        uv_risk_score=uv_risk_score,
        pentograph_ok=pentograph_authentic,
        thread_ok=thread_present,
        watermark_ok=watermark_present,
        requires_review=requires_review,
    )

    return UVSecurityResult(
        pentograph_authentic=pentograph_authentic,
        pentograph_confidence=pentograph_confidence,
        pentograph_notes=pentograph_notes,
        security_thread_present=thread_present,
        security_thread_confidence=thread_confidence,
        security_thread_position=thread_position,
        security_thread_notes=thread_notes,
        uv_watermark_present=watermark_present,
        uv_watermark_confidence=watermark_confidence,
        uv_watermark_notes=watermark_notes,
        uv_security_passed=uv_passed,
        uv_risk_score=uv_risk_score,
        requires_human_review=requires_review,
        degraded=False,
    )


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))
