"""
TDD — RED phase: tests for shared/ai/model_cascade.py

Tests the Cascaded AI Model pattern (Gemini Fix A):
  L1 Guard (7B, fast) → confidence check → L2 Full (72B, forensic) if needed
  High-value cheques (≥ ₹50L) always escalate to L2 regardless of L1 confidence.
  Kill switch KC skips cascade entirely (already handled in alteration.py).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cascade_config(
    l1_threshold: float = 0.85,
    high_value_threshold: float = 5_000_000.0,
    l2_enabled: bool = True,
) -> dict:
    return {
        "ai.cascade.l1_confidence_threshold": l1_threshold,
        "ai.cascade.high_value_threshold": high_value_threshold,
        "ai.cascade.l2_escalation_enabled": l2_enabled,
        "ai.cascade.l1_model_vision": "qwen2-vl-7b",
        "ai.cascade.l2_model_vision": "qwen2-vl-72b",
        "ai.cascade.l1_model_ocr": "got-ocr2-7b",
        "ai.cascade.l2_model_ocr": "got-ocr2-full",
    }


def _make_l1_response(confidence: float, content: str = '{"result": "ok"}'):
    """Simulate an L1 vLLM response."""
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.confidence = confidence
    return resp


# ---------------------------------------------------------------------------
# CascadeResult model
# ---------------------------------------------------------------------------

class TestCascadeResult:
    def test_cascade_result_has_model_used(self):
        from shared.ai.model_cascade import CascadeResult
        r = CascadeResult(
            content='{"ok": 1}',
            confidence=0.95,
            cascade_level=1,
            model_used="qwen2-vl-7b",
            escalated=False,
        )
        assert r.model_used == "qwen2-vl-7b"
        assert r.cascade_level == 1
        assert r.escalated is False

    def test_cascade_result_level_2_marks_escalated(self):
        from shared.ai.model_cascade import CascadeResult
        r = CascadeResult(
            content='{"ok": 1}',
            confidence=0.70,
            cascade_level=2,
            model_used="qwen2-vl-72b",
            escalated=True,
        )
        assert r.escalated is True
        assert r.cascade_level == 2


# ---------------------------------------------------------------------------
# CascadeOrchestrator — Vision cascade
# ---------------------------------------------------------------------------

class TestVisionCascadeL1Sufficient:
    @pytest.mark.asyncio
    async def test_high_confidence_l1_does_not_call_l2(self):
        """L1 confidence ≥ threshold AND standard value → L2 must NOT be called."""
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"tamper_risk": 0.01}'
        l1_resp.confidence = 0.95
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/INST001.jpg",
            prompt="Analyse this cheque",
            cheque_amount=50_000.0,   # standard value — well below ₹50L
        )
        l2_client.chat.completions.create.assert_not_called()
        assert result.cascade_level == 1
        assert result.model_used == "qwen2-vl-7b"
        assert result.escalated is False

    @pytest.mark.asyncio
    async def test_l1_result_content_returned(self):
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"tamper_risk": 0.03, "fields": []}'
        l1_resp.confidence = 0.92
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/INST001.jpg",
            prompt="Analyse",
            cheque_amount=100_000.0,
        )
        assert result.content == '{"tamper_risk": 0.03, "fields": []}'


class TestVisionCascadeL2Escalation:
    @pytest.mark.asyncio
    async def test_low_l1_confidence_escalates_to_l2(self):
        """L1 confidence < threshold → L2 must be called."""
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"tamper_risk": 0.5}'
        l1_resp.confidence = 0.70   # below 0.85 threshold
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        l2_resp = MagicMock()
        l2_resp.choices[0].message.content = '{"tamper_risk": 0.02, "fields": []}'
        l2_resp.confidence = 0.96
        l2_client.chat.completions.create = AsyncMock(return_value=l2_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/INST001.jpg",
            prompt="Analyse",
            cheque_amount=50_000.0,
        )
        l2_client.chat.completions.create.assert_called_once()
        assert result.cascade_level == 2
        assert result.model_used == "qwen2-vl-72b"
        assert result.escalated is True

    @pytest.mark.asyncio
    async def test_high_value_always_escalates_regardless_of_l1_confidence(self):
        """Amount ≥ ₹50L → L2 mandatory even if L1 is high-confidence."""
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"tamper_risk": 0.01}'
        l1_resp.confidence = 0.99   # very high — but amount is high-value
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        l2_resp = MagicMock()
        l2_resp.choices[0].message.content = '{"tamper_risk": 0.01, "fields": []}'
        l2_resp.confidence = 0.99
        l2_client.chat.completions.create = AsyncMock(return_value=l2_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/INST001.jpg",
            prompt="Analyse",
            cheque_amount=6_000_000.0,   # ₹60L — exceeds ₹50L threshold
        )
        l2_client.chat.completions.create.assert_called_once()
        assert result.cascade_level == 2
        assert result.escalated is True

    @pytest.mark.asyncio
    async def test_l2_result_content_returned_when_escalated(self):
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"tamper_risk": 0.5}'
        l1_resp.confidence = 0.65
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        l2_resp = MagicMock()
        l2_resp.choices[0].message.content = '{"tamper_risk": 0.02, "final": true}'
        l2_resp.confidence = 0.97
        l2_client.chat.completions.create = AsyncMock(return_value=l2_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/X.jpg",
            prompt="Analyse",
            cheque_amount=50_000.0,
        )
        assert result.content == '{"tamper_risk": 0.02, "final": true}'
        assert result.confidence == 0.97

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_does_not_escalate(self):
        """Confidence exactly == threshold: L1 sufficient (threshold is inclusive lower bound)."""
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"ok": 1}'
        l1_resp.confidence = 0.85   # exactly at threshold
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(l1_threshold=0.85),
                                    bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/X.jpg", prompt="A", cheque_amount=50_000.0
        )
        l2_client.chat.completions.create.assert_not_called()
        assert result.cascade_level == 1


class TestVisionCascadeL2Disabled:
    @pytest.mark.asyncio
    async def test_l2_disabled_uses_l1_even_for_low_confidence(self):
        """When l2_escalation_enabled=False, always use L1 result (even if low confidence)."""
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"tamper_risk": 0.5}'
        l1_resp.confidence = 0.50   # low — but L2 disabled
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(l2_enabled=False),
                                    bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/X.jpg", prompt="A", cheque_amount=50_000.0
        )
        l2_client.chat.completions.create.assert_not_called()
        assert result.cascade_level == 1


# ---------------------------------------------------------------------------
# CascadeOrchestrator — OCR cascade (same pattern)
# ---------------------------------------------------------------------------

class TestOCRCascade:
    @pytest.mark.asyncio
    async def test_high_confidence_ocr_l1_skips_l2(self):
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"micr": "123456789"}'
        l1_resp.confidence = 0.96
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_ocr(
            image_url="s3://bucket/INST001.jpg",
            prompt="Extract MICR",
            cheque_amount=50_000.0,
        )
        l2_client.chat.completions.create.assert_not_called()
        assert result.cascade_level == 1
        assert result.model_used == "got-ocr2-7b"

    @pytest.mark.asyncio
    async def test_low_confidence_ocr_escalates_to_l2(self):
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_resp = MagicMock()
        l1_resp.choices[0].message.content = '{"micr": "?"}'
        l1_resp.confidence = 0.60
        l1_client.chat.completions.create = AsyncMock(return_value=l1_resp)

        l2_resp = MagicMock()
        l2_resp.choices[0].message.content = '{"micr": "123456789"}'
        l2_resp.confidence = 0.97
        l2_client.chat.completions.create = AsyncMock(return_value=l2_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_ocr(
            image_url="s3://bucket/INST001.jpg",
            prompt="Extract MICR",
            cheque_amount=50_000.0,
        )
        l2_client.chat.completions.create.assert_called_once()
        assert result.cascade_level == 2
        assert result.model_used == "got-ocr2-full"


# ---------------------------------------------------------------------------
# L1 client failure — graceful degradation
# ---------------------------------------------------------------------------

class TestCascadeGracefulDegradation:
    @pytest.mark.asyncio
    async def test_l1_failure_falls_back_to_l2(self):
        """If L1 vLLM is unavailable, cascade falls through to L2."""
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_client.chat.completions.create = AsyncMock(
            side_effect=Exception("L1 vLLM unavailable")
        )
        l2_resp = MagicMock()
        l2_resp.choices[0].message.content = '{"tamper_risk": 0.01}'
        l2_resp.confidence = 0.96
        l2_client.chat.completions.create = AsyncMock(return_value=l2_resp)

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        result = await orch.call_vision(
            image_url="s3://bucket/X.jpg", prompt="A", cheque_amount=50_000.0
        )
        l2_client.chat.completions.create.assert_called_once()
        assert result.cascade_level == 2
        assert result.escalated is True

    @pytest.mark.asyncio
    async def test_both_l1_and_l2_failure_raises(self):
        """If both L1 and L2 fail, raise exception (caller handles graceful degradation)."""
        from shared.ai.model_cascade import CascadeOrchestrator
        l1_client = AsyncMock()
        l2_client = AsyncMock()
        l1_client.chat.completions.create = AsyncMock(
            side_effect=Exception("L1 unavailable")
        )
        l2_client.chat.completions.create = AsyncMock(
            side_effect=Exception("L2 unavailable")
        )

        orch = CascadeOrchestrator(l1_client=l1_client, l2_client=l2_client,
                                    config=_make_cascade_config(), bank_id="test-bank")
        with pytest.raises(Exception):
            await orch.call_vision(
                image_url="s3://bucket/X.jpg", prompt="A", cheque_amount=50_000.0
            )


# ---------------------------------------------------------------------------
# OTel span attributes
# ---------------------------------------------------------------------------

class TestCascadeOTelAttributes:
    @pytest.mark.asyncio
    async def test_result_carries_otel_span_attributes(self):
        """CascadeResult must expose attributes for OTel span enrichment."""
        from shared.ai.model_cascade import CascadeResult
        r = CascadeResult(
            content='{"ok": 1}',
            confidence=0.96,
            cascade_level=1,
            model_used="qwen2-vl-7b",
            escalated=False,
        )
        # Caller will set these on span:
        assert hasattr(r, "cascade_level")
        assert hasattr(r, "model_used")
        assert hasattr(r, "escalated")
        assert hasattr(r, "confidence")
