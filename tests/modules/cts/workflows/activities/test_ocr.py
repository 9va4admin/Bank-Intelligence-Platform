"""
Tests for modules/cts/workflows/activities/ocr.py

GOT-OCR2.0 via cascade orchestrator: extracts MICR line, amount in figures, amount in
words, date, and payee name from cheque image.

Thresholds from config_service. Low confidence → HUMAN_REVIEW.
Orchestrator unavailable → graceful degradation, never crashes workflow.
"""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_input(image_url="s3://bucket/INST001.jpg", instrument_id="INST001", bank_id="test-bank"):
    from modules.cts.workflows.activities.ocr import OCRActivityInput
    return OCRActivityInput(image_url=image_url, instrument_id=instrument_id, bank_id=bank_id)


def _make_vllm_response(confidence=0.97, micr="123456789012345"):
    """Build the dict a real OCR model would return as its JSON payload."""
    return {
        "micr_line": {"value": micr, "confidence": confidence},
        "amount_figures": {"value": "10000.00", "confidence": confidence},
        "amount_words": {"value": "Ten Thousand Only", "confidence": confidence},
        "date": {"value": "17/06/2026", "confidence": confidence},
        "payee": {"value": "ACME Corp", "confidence": confidence},
    }


def _mock_orchestrator(data: dict, confidence=0.97):
    """Return a CascadeOrchestrator mock whose call_ocr returns JSON payload."""
    from shared.ai.model_cascade import CascadeResult
    cascade_result = CascadeResult(
        content=json.dumps(data),
        confidence=confidence,
        cascade_level=1,
        model_used="got-ocr2-7b",
        escalated=False,
    )
    orchestrator = AsyncMock()
    orchestrator.call_ocr = AsyncMock(return_value=cascade_result)
    return orchestrator


def _mock_config(min_confidence=0.85):
    """Return a config_service mock satisfying ocr_extract's get_ai_config call."""
    config = AsyncMock()
    config.get_ai_config = AsyncMock(return_value={"ai.ocr.min_confidence": min_confidence})
    return config


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

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.98)),
            config_service=_mock_config(),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_returns_extracted_micr(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(micr="111222333444555")),
            config_service=_mock_config(),
        )
        assert result.micr_line == "111222333444555"

    @pytest.mark.asyncio
    async def test_returns_extracted_amount_figures(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response()),
            config_service=_mock_config(),
        )
        assert result.amount_figures == "10000.00"

    @pytest.mark.asyncio
    async def test_returns_overall_confidence(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.97)),
            config_service=_mock_config(),
        )
        assert result.overall_confidence > 0.0


class TestOCRLowConfidence:
    @pytest.mark.asyncio
    async def test_low_confidence_outcome_human_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.70)),
            config_service=_mock_config(),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_low_confidence_reason_set(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.70)),
            config_service=_mock_config(),
        )
        assert result.low_confidence_reason is not None

    @pytest.mark.asyncio
    async def test_threshold_from_config_not_hardcoded(self):
        """Different config thresholds change the decision — not hardcoded in code."""
        from modules.cts.workflows.activities.ocr import ocr_extract

        # confidence=0.80 in payload
        data = _make_vllm_response(confidence=0.80)

        # Loose threshold (0.75): should PROCEED
        result_loose = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(data),
            config_service=_mock_config(min_confidence=0.75),
        )
        # Tight threshold (0.90): same data, should HUMAN_REVIEW
        result_tight = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(data),
            config_service=_mock_config(min_confidence=0.90),
        )

        assert result_loose.outcome == "PROCEED"
        assert result_tight.outcome == "HUMAN_REVIEW"


class TestOCRDegradation:
    @pytest.mark.asyncio
    async def test_model_unavailable_outcome_human_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(side_effect=Exception("vLLM connection refused"))

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_model_unavailable_does_not_raise(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(side_effect=TimeoutError("GPU timeout"))

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result is not None

    @pytest.mark.asyncio
    async def test_model_unavailable_degraded_flag_set(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(side_effect=ConnectionError("down"))

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_model_unavailable_micr_is_none(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(side_effect=RuntimeError("model not loaded"))

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.micr_line is None


# ---------------------------------------------------------------------------
# _route_micr exception path (lines 165-189)
# ---------------------------------------------------------------------------

class TestRouteMicrException:
    """Cover _route_micr: MICRPrefixRouter raises → fallback to DIRECT."""

    def test_route_micr_exception_returns_direct(self):
        """When MICRPrefixRouter.identify raises, returns DIRECT and None."""
        from modules.cts.workflows.activities.ocr import _route_micr
        from unittest.mock import patch, MagicMock

        with patch(
            "modules.cts.workflows.activities.ocr.MICRPrefixRouter",
            side_effect=Exception("routing table corrupt"),
        ):
            tag, smb = _route_micr(
                micr_line="123456789012345",
                routing_table={"prefix": "123"},
                instrument_id="INST001",
            )
        from modules.cts.workflows.activities.ocr import PrincipalTag
        assert tag == PrincipalTag.DIRECT.value
        assert smb is None

    def test_route_micr_identify_raises_returns_direct(self):
        """MICRPrefixRouter instantiates OK but identify() raises → fallback."""
        from modules.cts.workflows.activities.ocr import _route_micr
        from unittest.mock import patch, MagicMock

        mock_router = MagicMock()
        mock_router.identify = MagicMock(side_effect=ValueError("unknown prefix"))

        with patch(
            "modules.cts.workflows.activities.ocr.MICRPrefixRouter",
            return_value=mock_router,
        ):
            tag, smb = _route_micr(
                micr_line="999999999999999",
                routing_table={"prefix": "123"},
                instrument_id="INST002",
            )
        from modules.cts.workflows.activities.ocr import PrincipalTag
        assert tag == PrincipalTag.DIRECT.value
        assert smb is None

    def test_route_micr_with_sub_member_returns_id(self):
        """Happy path with sub_member: returns tag.value and sub_member_id."""
        from modules.cts.workflows.activities.ocr import _route_micr
        from unittest.mock import patch, MagicMock

        mock_smb = MagicMock()
        mock_smb.sub_member_id = "SMB-001"
        mock_tag = MagicMock()
        mock_tag.value = "SPONSOR"

        mock_router = MagicMock()
        mock_router.identify = MagicMock(return_value=(mock_tag, mock_smb))

        with patch(
            "modules.cts.workflows.activities.ocr.MICRPrefixRouter",
            return_value=mock_router,
        ):
            tag, smb = _route_micr(
                micr_line="123456789012345",
                routing_table={"prefix": "123"},
                instrument_id="INST003",
            )
        assert tag == "SPONSOR"
        assert smb == "SMB-001"


# ---------------------------------------------------------------------------
# Cascade orchestrator wiring (Fix A — Gemini)
# ---------------------------------------------------------------------------

class TestOCRCascadeWiring:
    def _make_cascade_content(self, confidence=0.97, micr="123456789012345"):
        """Build the JSON string a real vLLM OCR model would return."""
        return json.dumps({
            "micr_line": {"value": micr, "confidence": confidence},
            "amount_figures": {"value": "10000.00", "confidence": confidence},
            "amount_words": {"value": "Ten Thousand Only", "confidence": confidence},
            "date": {"value": "17/06/2026", "confidence": confidence},
            "payee": {"value": "ACME Corp", "confidence": confidence},
        })

    @pytest.mark.asyncio
    async def test_cascade_orchestrator_called_when_provided(self):
        """call_ocr must be invoked — it is the only inference path."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=self._make_cascade_content(confidence=0.97),
            confidence=0.97,
            cascade_level=1,
            model_used="got-ocr2-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=cascade_result)

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        orchestrator.call_ocr.assert_called_once()
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_cascade_micr_extracted_from_content(self):
        """MICR line is correctly parsed from the cascade result's JSON content."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=self._make_cascade_content(micr="999888777666555"),
            confidence=0.97,
            cascade_level=1,
            model_used="got-ocr2-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=cascade_result)

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.micr_line == "999888777666555"

    @pytest.mark.asyncio
    async def test_cascade_level_in_ocr_result(self):
        """result.cascade_level reflects which model was used."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=self._make_cascade_content(),
            confidence=0.97,
            cascade_level=1,
            model_used="got-ocr2-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=cascade_result)

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.cascade_level == 1

    @pytest.mark.asyncio
    async def test_cascade_l2_level_reflected(self):
        """When cascade uses L2, result.cascade_level == 2."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=self._make_cascade_content(),
            confidence=0.96,
            cascade_level=2,
            model_used="got-ocr2-full",
            escalated=True,
            escalation_reason="low_confidence",
        )
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=cascade_result)

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.cascade_level == 2

    @pytest.mark.asyncio
    async def test_cascade_exception_degrades_gracefully(self):
        """If cascade raises (all models down), result is degraded human review."""
        from modules.cts.workflows.activities.ocr import ocr_extract

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(side_effect=RuntimeError("All OCR models down"))

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_orchestrator_call_ocr_is_always_used(self):
        """Orchestrator is the only inference path — call_ocr must be called exactly once."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=self._make_cascade_content(confidence=0.97),
            confidence=0.97,
            cascade_level=1,
            model_used="got-ocr2-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=cascade_result)

        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        orchestrator.call_ocr.assert_called_once()
        assert result.outcome == "PROCEED"
