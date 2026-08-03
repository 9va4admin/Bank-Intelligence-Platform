"""
AI Model Cascade Orchestrator — Gemini Fix A.

L1 Guard (7B, fast, ~100ms) → confidence gate → L2 Full (72B, forensic, ~500ms).

Escalation rules:
  1. L1 confidence < config["ai.cascade.l1_confidence_threshold"]  → escalate to L2
  2. cheque_amount >= config["ai.cascade.high_value_threshold"]     → always L2 (mandatory)
  3. L1 vLLM unavailable (exception)                                → fall through to L2
  4. config["ai.cascade.l2_escalation_enabled"] == False            → always use L1 result

Result: ~90% of cheques clear via L1 in <100ms. Only risky/high-value go to L2.
SLA impact: reduces average wall-clock from ~500ms to ~150ms per cheque.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()
tracer = trace.get_tracer("astra.ai.cascade")


class CascadeResult(BaseModel):
    """Result from the cascade orchestrator — carries which model was used and why."""
    model_config = ConfigDict(frozen=True, protected_namespaces=())

    content: str                # raw JSON string from the winning model
    confidence: float = Field(ge=0.0, le=1.0)
    cascade_level: int          # 1 = L1 used, 2 = L2 used
    model_used: str             # e.g. "qwen2-vl-7b" or "qwen2-vl-72b"
    escalated: bool             # True if L2 was used (whether by confidence or high-value rule)
    escalation_reason: Optional[str] = None  # "low_confidence" | "high_value" | "l1_unavailable"


class CascadeOrchestrator:
    """
    Shared orchestrator used by alteration.py and ocr.py activities.

    Both vision (Qwen2-VL) and OCR (GOT-OCR2.0) follow the same cascade pattern.
    The caller provides l1_client and l2_client — both are vLLM AsyncOpenAI clients
    pointing to different model endpoints (different queues, different GPU tiers).
    """

    def __init__(
        self,
        l1_client: Any,
        l2_client: Any,
        config: dict[str, Any],
        bank_id: str,
    ) -> None:
        self._l1 = l1_client
        self._l2 = l2_client
        self._config = config
        self._bank_id = bank_id

    # ── Public interface ────────────────────────────────────────────────────

    async def call_vision(
        self,
        image_url: str,
        prompt: str,
        cheque_amount: float,
        extra_context: Optional[dict] = None,
    ) -> CascadeResult:
        """Cascade call for vision/alteration (Qwen2-VL family)."""
        l1_model = self._config.get("ai.cascade.l1_model_vision", "qwen2-vl-7b")
        l2_model = self._config.get("ai.cascade.l2_model_vision", "qwen2-vl-72b")
        l1_queue = "cts-vision-l1"
        l2_queue = "cts-vision-l2"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        return await self._cascade(
            messages=messages,
            cheque_amount=cheque_amount,
            l1_model=l1_model,
            l2_model=l2_model,
            l1_queue=l1_queue,
            l2_queue=l2_queue,
            call_type="vision",
        )

    async def call_ocr(
        self,
        image_url: str,
        prompt: str,
        cheque_amount: float,
    ) -> CascadeResult:
        """Cascade call for OCR/MICR extraction (GOT-OCR2.0 family)."""
        l1_model = self._config.get("ai.cascade.l1_model_ocr", "got-ocr2-7b")
        l2_model = self._config.get("ai.cascade.l2_model_ocr", "got-ocr2-full")
        l1_queue = "cts-ocr-l1"
        l2_queue = "cts-ocr-l2"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        return await self._cascade(
            messages=messages,
            cheque_amount=cheque_amount,
            l1_model=l1_model,
            l2_model=l2_model,
            l1_queue=l1_queue,
            l2_queue=l2_queue,
            call_type="ocr",
        )

    # ── Internal cascade logic ──────────────────────────────────────────────

    async def _cascade(
        self,
        messages: list[dict],
        cheque_amount: float,
        l1_model: str,
        l2_model: str,
        l1_queue: str,
        l2_queue: str,
        call_type: str,
    ) -> CascadeResult:
        l1_threshold: float = self._config.get("ai.cascade.l1_confidence_threshold", 0.85)
        high_value_limit: float = self._config.get("ai.cascade.high_value_threshold", 5_000_000.0)
        l2_enabled: bool = self._config.get("ai.cascade.l2_escalation_enabled", True)

        is_high_value = cheque_amount >= high_value_limit

        with tracer.start_as_current_span(f"ai.cascade.{call_type}.l1") as span:
            span.set_attribute("bank_id", self._bank_id)
            span.set_attribute("model", l1_model)
            span.set_attribute("queue", l1_queue)
            span.set_attribute("cheque_amount", cheque_amount)
            span.set_attribute("is_high_value", is_high_value)

            l1_result = await self._call_model(self._l1, messages, l1_model, l1_queue)

        if l1_result is None:
            # L1 failed — fall through to L2
            log.warning(
                "ai.cascade.l1_unavailable",
                bank_id=self._bank_id,
                call_type=call_type,
                fallback="l2",
            )
            return await self._call_l2(
                messages, l2_model, l2_queue, call_type,
                reason="l1_unavailable",
            )

        l1_content = l1_result.choices[0].message.content
        l1_confidence: float = getattr(l1_result, "confidence", 1.0)

        # Decision: use L1 or escalate
        if not l2_enabled:
            log.info("ai.cascade.l2_disabled", bank_id=self._bank_id, model=l1_model)
            return CascadeResult(
                content=l1_content,
                confidence=l1_confidence,
                cascade_level=1,
                model_used=l1_model,
                escalated=False,
            )

        if is_high_value:
            log.info(
                "ai.cascade.escalating_high_value",
                bank_id=self._bank_id,
                cheque_amount=cheque_amount,
                threshold=high_value_limit,
            )
            return await self._call_l2(
                messages, l2_model, l2_queue, call_type,
                reason="high_value",
            )

        if l1_confidence < l1_threshold:
            log.info(
                "ai.cascade.escalating_low_confidence",
                bank_id=self._bank_id,
                l1_confidence=l1_confidence,
                threshold=l1_threshold,
            )
            return await self._call_l2(
                messages, l2_model, l2_queue, call_type,
                reason="low_confidence",
            )

        # L1 sufficient
        log.info(
            "ai.cascade.l1_sufficient",
            bank_id=self._bank_id,
            model=l1_model,
            confidence=l1_confidence,
        )
        return CascadeResult(
            content=l1_content,
            confidence=l1_confidence,
            cascade_level=1,
            model_used=l1_model,
            escalated=False,
        )

    async def _call_l2(
        self,
        messages: list[dict],
        l2_model: str,
        l2_queue: str,
        call_type: str,
        reason: str,
    ) -> CascadeResult:
        with tracer.start_as_current_span(f"ai.cascade.{call_type}.l2") as span:
            span.set_attribute("bank_id", self._bank_id)
            span.set_attribute("model", l2_model)
            span.set_attribute("queue", l2_queue)
            span.set_attribute("escalation_reason", reason)

            l2_result = await self._call_model(self._l2, messages, l2_model, l2_queue)

        if l2_result is None:
            raise RuntimeError(
                f"Both L1 and L2 vLLM unavailable for {call_type} cascade "
                f"(bank_id={self._bank_id})"
            )

        l2_content = l2_result.choices[0].message.content
        l2_confidence: float = getattr(l2_result, "confidence", 1.0)

        return CascadeResult(
            content=l2_content,
            confidence=l2_confidence,
            cascade_level=2,
            model_used=l2_model,
            escalated=True,
            escalation_reason=reason,
        )

    @staticmethod
    async def _call_model(client: Any, messages: list[dict], model: str, queue: str) -> Any:
        """Call a vLLM endpoint. Returns None on failure (caller decides fallback)."""
        try:
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                extra_body={"queue": queue},
                timeout=120,
            )
        except Exception as exc:
            log.warning(
                "ai.cascade.model_call_failed",
                model=model,
                queue=queue,
                error=str(exc),
            )
            return None
