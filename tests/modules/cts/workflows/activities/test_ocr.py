"""
Tests for modules/cts/workflows/activities/ocr.py

GOT-OCR2.0 via vLLM: extracts MICR line, amount in figures, amount in words,
date, payee name, and drawer name from cheque image.

Thresholds from config_service. Low confidence → HUMAN_REVIEW.
vLLM unavailable → graceful degradation, never crashes workflow.
"""
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_input(image_url="s3://bucket/INST001.jpg", instrument_id="INST001", bank_id="test-bank"):
    from modules.cts.workflows.activities.ocr import OCRActivityInput
    return OCRActivityInput(image_url=image_url, instrument_id=instrument_id, bank_id=bank_id)


def _make_vllm_response(confidence=0.97, micr="123456789012345"):
    return {
        "micr_line": {"value": micr, "confidence": confidence},
        "amount_figures": {"value": "10000.00", "confidence": confidence},
        "amount_words": {"value": "Ten Thousand Only", "confidence": confidence},
        "date": {"value": "17/06/2026", "confidence": confidence},
        "payee": {"value": "ACME Corp", "confidence": confidence},
        "drawer": {"value": "J***", "confidence": confidence},
    }


class TestOCRInput:
    def test_requires_image_url(self):
        from modules.cts.workflows.activities.ocr import OCRActivityInput
        with pytest.raises(Exception):
            OCRActivityInput(instrument_id="I", bank_id="b")

    def test_requires_instrument_id(self):
        from modules.cts.workflows.activities.ocr import OCRActivityInput
        with pytest.raises(Exception):
            OCRActivityInput(image_url="s3://x", bank_id="b")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.image_url = "s3://other"


class TestOCRHappyPath:
    @pytest.mark.asyncio
    async def test_high_confidence_outcome_proceed(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response(confidence=0.98))

        result = await ocr_extract(
            _make_input(),
            vllm_client=mock_vllm,
            min_confidence=0.85,
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_returns_extracted_micr(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response(micr="111222333444555"))

        result = await ocr_extract(
            _make_input(),
            vllm_client=mock_vllm,
            min_confidence=0.85,
        )
        assert result.micr_line == "111222333444555"

    @pytest.mark.asyncio
    async def test_returns_extracted_amount_figures(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response())

        result = await ocr_extract(
            _make_input(),
            vllm_client=mock_vllm,
            min_confidence=0.85,
        )
        assert result.amount_figures == "10000.00"

    @pytest.mark.asyncio
    async def test_returns_overall_confidence(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response(confidence=0.97))

        result = await ocr_extract(
            _make_input(),
            vllm_client=mock_vllm,
            min_confidence=0.85,
        )
        assert result.overall_confidence > 0.0


class TestOCRLowConfidence:
    @pytest.mark.asyncio
    async def test_low_confidence_outcome_human_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response(confidence=0.70))

        result = await ocr_extract(
            _make_input(),
            vllm_client=mock_vllm,
            min_confidence=0.85,
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_low_confidence_reason_set(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response(confidence=0.70))

        result = await ocr_extract(
            _make_input(),
            vllm_client=mock_vllm,
            min_confidence=0.85,
        )
        assert result.low_confidence_reason is not None

    @pytest.mark.asyncio
    async def test_threshold_from_parameter_not_hardcoded(self):
        """Different min_confidence values change the decision."""
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response(confidence=0.80))

        # With loose threshold: PROCEED
        result_loose = await ocr_extract(_make_input(), vllm_client=mock_vllm, min_confidence=0.75)
        # With tight threshold: HUMAN_REVIEW
        mock_vllm.extract = AsyncMock(return_value=_make_vllm_response(confidence=0.80))
        result_tight = await ocr_extract(_make_input(), vllm_client=mock_vllm, min_confidence=0.90)

        assert result_loose.outcome == "PROCEED"
        assert result_tight.outcome == "HUMAN_REVIEW"


class TestOCRDegradation:
    @pytest.mark.asyncio
    async def test_vllm_unavailable_outcome_human_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(side_effect=Exception("vLLM connection refused"))

        result = await ocr_extract(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vllm_unavailable_does_not_raise(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(side_effect=TimeoutError("GPU timeout"))

        result = await ocr_extract(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result is not None

    @pytest.mark.asyncio
    async def test_vllm_unavailable_degraded_flag_set(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(side_effect=ConnectionError("down"))

        result = await ocr_extract(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_vllm_unavailable_micr_is_none(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        mock_vllm = AsyncMock()
        mock_vllm.extract = AsyncMock(side_effect=RuntimeError("model not loaded"))

        result = await ocr_extract(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.micr_line is None
