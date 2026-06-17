"""
Tests for modules/cts/workflows/activities/alteration.py

Qwen2-VL detects physical alterations (overwriting, erasure, correction fluid,
ink mismatch) on cheque fields. Detected alteration → STP_RETURN in decision activity.

vLLM unavailable → graceful degradation to HUMAN_REVIEW.
"""
from unittest.mock import AsyncMock
import pytest


def _make_input(image_url="s3://bucket/INST001.jpg", instrument_id="INST001", bank_id="test-bank"):
    from modules.cts.workflows.activities.alteration import AlterationActivityInput
    return AlterationActivityInput(image_url=image_url, instrument_id=instrument_id, bank_id=bank_id)


class TestAlterationInput:
    def test_requires_image_url(self):
        from modules.cts.workflows.activities.alteration import AlterationActivityInput
        with pytest.raises(Exception):
            AlterationActivityInput(instrument_id="I", bank_id="b")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.image_url = "other"


class TestAlterationClean:
    @pytest.mark.asyncio
    async def test_clean_cheque_alteration_not_detected(self):
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(return_value={
            "alteration_detected": False,
            "tamper_risk": 0.02,
            "fields_checked": ["amount_figures", "amount_words", "date", "payee"],
        })

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result.alteration_detected is False

    @pytest.mark.asyncio
    async def test_clean_cheque_risk_score_low(self):
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(return_value={
            "alteration_detected": False,
            "tamper_risk": 0.03,
            "fields_checked": ["amount_figures"],
        })

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result.tamper_risk_score < 0.5


class TestAlterationDetected:
    @pytest.mark.asyncio
    async def test_alteration_detected_flag_true(self):
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(return_value={
            "alteration_detected": True,
            "tamper_risk": 0.92,
            "altered_fields": ["amount_figures"],
        })

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result.alteration_detected is True

    @pytest.mark.asyncio
    async def test_alteration_returns_altered_fields(self):
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(return_value={
            "alteration_detected": True,
            "tamper_risk": 0.88,
            "altered_fields": ["amount_figures", "date"],
        })

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert "amount_figures" in result.altered_fields

    @pytest.mark.asyncio
    async def test_alteration_high_risk_score(self):
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(return_value={
            "alteration_detected": True,
            "tamper_risk": 0.91,
            "altered_fields": ["payee"],
        })

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result.tamper_risk_score > 0.5


class TestAlterationDegradation:
    @pytest.mark.asyncio
    async def test_vllm_unavailable_does_not_raise(self):
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(side_effect=Exception("vLLM down"))

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result is not None

    @pytest.mark.asyncio
    async def test_vllm_unavailable_degraded_flag_set(self):
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(side_effect=ConnectionError("GPU unreachable"))

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_vllm_unavailable_alteration_not_detected(self):
        """On model failure, do NOT assume alteration — escalate to human instead."""
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(side_effect=TimeoutError("timeout"))

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result.alteration_detected is False

    @pytest.mark.asyncio
    async def test_vllm_unavailable_requires_human_review(self):
        """Degraded alteration check must flag for human review."""
        from modules.cts.workflows.activities.alteration import detect_alteration

        mock_vllm = AsyncMock()
        mock_vllm.analyse = AsyncMock(side_effect=RuntimeError("model error"))

        result = await detect_alteration(_make_input(), vllm_client=mock_vllm)
        assert result.requires_human_review is True
