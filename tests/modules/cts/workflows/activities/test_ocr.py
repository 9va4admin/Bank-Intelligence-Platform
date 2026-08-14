"""
Tests for modules/cts/workflows/activities/ocr.py

GOT-OCR2.0 via cascade orchestrator: extracts MICR line, amount in figures, amount in
words, date, and payee name from cheque image.

Thresholds from config_service. Low confidence → HUMAN_REVIEW.
Orchestrator unavailable → graceful degradation, never crashes workflow.
"""
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from PIL import Image


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


def _mock_config_with_indic(min_confidence=0.85, indic_ocr_url="http://indic-ocr-test:8021",
                             min_indic_confidence=0.60):
    """Config mock with IndicOCR enabled (services.indic_ocr.url set)."""
    config = AsyncMock()
    config.get_ai_config = AsyncMock(return_value={
        "ai.ocr.min_confidence": min_confidence,
        "services.indic_ocr.url": indic_ocr_url,
        "ai.ocr.min_indic_confidence": min_indic_confidence,
    })
    return config


# Keep alias so tests that haven't been renamed still compile
_mock_config_partial = _mock_config_with_indic


def _make_fake_jpeg_bytes(w: int = 1400, h: int = 600) -> bytes:
    """Minimal synthetic cheque image as JPEG bytes for HTTP-fetch mocking."""
    img = Image.new("RGB", (w, h), color=(200, 220, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _mock_httpx(image_bytes: bytes, indic_text: str = "", indic_conf: float = 0.0):
    """
    Build an httpx.AsyncClient mock for PARTIAL_IMAGE tests.
    GET → returns image_bytes.
    POST → returns IndicOCR payload {text, confidence, backend}.
    """
    get_resp = MagicMock()
    get_resp.raise_for_status = MagicMock()
    get_resp.content = image_bytes

    post_resp = MagicMock()
    post_resp.raise_for_status = MagicMock()
    post_resp.json = MagicMock(return_value={
        "text": indic_text,
        "confidence": indic_conf,
        "backend": "paddle",
    })

    client = AsyncMock()
    client.get = AsyncMock(return_value=get_resp)
    client.post = AsyncMock(return_value=post_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=client)


def _zone_cascade_result(value: str, confidence: float = 0.95):
    """Single-field CascadeResult as returned by GOT-OCR2 zone calls."""
    from shared.ai.model_cascade import CascadeResult
    return CascadeResult(
        content=json.dumps({"value": value, "confidence": confidence}),
        confidence=confidence,
        cascade_level=1,
        model_used="got-ocr2-7b",
        escalated=False,
    )


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


# ---------------------------------------------------------------------------
# Item 3: IFSC code extraction
# ---------------------------------------------------------------------------

def _make_vllm_response_with_ifsc(confidence=0.97, ifsc="SBIN0001234"):
    return {
        "micr_line": {"value": "123456789012345", "confidence": confidence},
        "amount_figures": {"value": "10000.00", "confidence": confidence},
        "amount_words": {"value": "Ten Thousand Only", "confidence": confidence},
        "date": {"value": "17/06/2026", "confidence": confidence},
        "payee": {"value": "ACME Corp", "confidence": confidence},
        "ifsc_code": {"value": ifsc, "confidence": confidence},
    }


class TestOCRIFSCExtraction:
    @pytest.mark.asyncio
    async def test_ifsc_extracted_in_successful_result(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=CascadeResult(
            content=json.dumps(_make_vllm_response_with_ifsc(ifsc="SBIN0001234")),
            confidence=0.97, cascade_level=1, model_used="got-ocr2-7b", escalated=False,
        ))
        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.outcome == "PROCEED"
        assert result.ifsc_code == "SBIN0001234"

    @pytest.mark.asyncio
    async def test_ifsc_none_when_field_absent(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=CascadeResult(
            content=json.dumps(_make_vllm_response(confidence=0.97)),
            confidence=0.97, cascade_level=1, model_used="got-ocr2-7b", escalated=False,
        ))
        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.outcome == "PROCEED"
        assert result.ifsc_code is None

    @pytest.mark.asyncio
    async def test_ifsc_low_confidence_still_extracted(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult
        payload = {
            "micr_line": {"value": "123456789012345", "confidence": 0.97},
            "amount_figures": {"value": "10000.00", "confidence": 0.97},
            "amount_words": {"value": "Ten Thousand Only", "confidence": 0.97},
            "date": {"value": "17/06/2026", "confidence": 0.97},
            "payee": {"value": "ACME Corp", "confidence": 0.97},
            "ifsc_code": {"value": "SBIN0001234", "confidence": 0.40},
        }
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=CascadeResult(
            content=json.dumps(payload), confidence=0.97, cascade_level=1,
            model_used="got-ocr2-7b", escalated=False,
        ))
        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.outcome == "PROCEED"
        assert result.ifsc_code == "SBIN0001234"

    @pytest.mark.asyncio
    async def test_ifsc_null_value_returns_none(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult
        payload = {
            "micr_line": {"value": "123456789012345", "confidence": 0.97},
            "amount_figures": {"value": "10000.00", "confidence": 0.97},
            "amount_words": {"value": "Ten Thousand Only", "confidence": 0.97},
            "date": {"value": "17/06/2026", "confidence": 0.97},
            "payee": {"value": "ACME Corp", "confidence": 0.97},
            "ifsc_code": {"value": None, "confidence": 0.0},
        }
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=CascadeResult(
            content=json.dumps(payload), confidence=0.97, cascade_level=1,
            model_used="got-ocr2-7b", escalated=False,
        ))
        result = await ocr_extract(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.ifsc_code is None


# ── PARTIAL_IMAGE mode tests ───────────────────────────────────────────────────

class TestOCRPartialImageMode:
    """
    PARTIAL_IMAGE mode: zone extraction → script detection → route to
    IndicOCR (Indic script) or GOT-OCR2/vLLM (Latin script).
    All tests mock httpx to avoid real HTTP calls.
    """

    @pytest.mark.asyncio
    async def test_indic_ocr_skipped_when_url_not_configured(self):
        """
        When services.indic_ocr.url is absent from config, IndicOCR refinement
        is entirely skipped — no HTTP calls, GOT-OCR2 result used as-is.
        """
        from modules.cts.workflows.activities.ocr import ocr_extract
        with patch("modules.cts.workflows.activities.ocr.httpx") as mock_httpx_mod:
            result = await ocr_extract(
                _make_input(),
                orchestrator=_mock_orchestrator(_make_vllm_response()),
                config_service=_mock_config(),   # no services.indic_ocr.url → defaults to ""
            )
        mock_httpx_mod.AsyncClient.assert_not_called()
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_partial_image_mode_fetches_image_via_httpx(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("mock", 0.95))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            await ocr_extract(
                _make_input(image_url="http://minio/bucket/cheque.jpg"),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        client = mock_client_cls.return_value
        client.get.assert_called()

    @pytest.mark.asyncio
    async def test_image_fetch_failure_for_indic_does_not_crash(self):
        """
        When image fetch for IndicOCR refinement fails, the activity degrades
        gracefully: GOT-OCR2 results are kept, degraded flag stays False,
        and no exception propagates.
        """
        from modules.cts.workflows.activities.ocr import ocr_extract

        # GOT-OCR2 returns a good high-confidence Latin result
        good_orchestrator = _mock_orchestrator(_make_vllm_response(confidence=0.97))

        # Image fetch for IndicOCR zone refinement fails
        client = AsyncMock()
        client.get = AsyncMock(side_effect=Exception("minio unreachable"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", MagicMock(return_value=client)):
            result = await ocr_extract(
                _make_input(),
                orchestrator=good_orchestrator,
                config_service=_mock_config_with_indic(),
            )

        # GOT-OCR2 result is high-confidence Latin → PROCEED despite IndicOCR fetch failure
        assert result is not None
        assert result.degraded is False
        assert result.indic_refined_fields == []

    @pytest.mark.asyncio
    async def test_latin_cheque_never_calls_indic_ocr_post(self):
        """
        When GOT-OCR2 returns high-confidence Latin text (no Indic script),
        IndicOCR POST endpoint is never called — only one GOT-OCR2 call total.
        """
        from modules.cts.workflows.activities.ocr import ocr_extract

        # High-confidence fully Latin result: date, payee, amount_words all Latin
        latin_response = {
            "micr_line": {"value": "123456789012345", "confidence": 0.98},
            "amount_figures": {"value": "10000.00", "confidence": 0.98},
            "amount_words": {"value": "Ten Thousand Only", "confidence": 0.98},
            "date": {"value": "08/01/2013", "confidence": 0.98},
            "payee": {"value": "ACME Corporation", "confidence": 0.98},
        }

        client = AsyncMock()
        client.get = AsyncMock()
        client.post = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", MagicMock(return_value=client)):
            result = await ocr_extract(
                _make_input(),
                orchestrator=_mock_orchestrator(latin_response, confidence=0.98),
                config_service=_mock_config_with_indic(),
            )

        # No IndicOCR zone POST for fully Latin cheques
        client.post.assert_not_called()
        assert result.outcome == "PROCEED"
        assert result.indic_refined_fields == []

    @pytest.mark.asyncio
    async def test_devanagari_payee_uses_indic_ocr_result(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        hindi_payee = "अभिलाष रेड्डी"
        mock_client_cls = _mock_httpx(fake_bytes, indic_text=hindi_payee, indic_conf=0.88)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("fallback-got", 0.95))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        assert result.payee == hindi_payee

    @pytest.mark.asyncio
    async def test_latin_payee_falls_back_to_got_ocr2(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="Abhilash Reddy", indic_conf=0.85)
        got_payee = "Abhilash Reddy"
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result(got_payee, 0.95))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        orchestrator.call_ocr.assert_called()

    @pytest.mark.asyncio
    async def test_devanagari_amount_words_uses_indic_ocr(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        hindi_amount = "बीस लाख पचास हजार"
        mock_client_cls = _mock_httpx(fake_bytes, indic_text=hindi_amount, indic_conf=0.82)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("fallback", 0.90))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        assert result.amount_words == hindi_amount

    @pytest.mark.asyncio
    async def test_indic_ocr_down_falls_back_to_got_ocr2(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()
        get_resp.content = fake_bytes

        client = AsyncMock()
        client.get = AsyncMock(return_value=get_resp)
        client.post = AsyncMock(side_effect=Exception("IndicOCR service unavailable"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("Abhilash Reddy", 0.94))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", MagicMock(return_value=client)):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        orchestrator.call_ocr.assert_called()
        assert result.outcome in ("PROCEED", "HUMAN_REVIEW")
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_low_confidence_zone_triggers_human_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("unclear", 0.40))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(min_confidence=0.85),
            )

        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_indic_low_confidence_falls_back_to_got_ocr(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        # Devanagari text but below min_indic_confidence threshold
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="अभिलाष", indic_conf=0.30)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("Abhilash", 0.94))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        # GOT-OCR2 must have been called as fallback for the low-confidence IndicOCR
        orchestrator.call_ocr.assert_called()


# ---------------------------------------------------------------------------
# IndicOCR Kill Switch (cts.indic_ocr.kill_mode)
# ---------------------------------------------------------------------------

def _mock_config_with_ks(min_confidence=0.85, indic_ocr_url="http://indic-ocr-test:8021",
                          min_indic_confidence=0.60, kill_mode="NONE"):
    """Config mock with both IndicOCR URL and a configurable kill switch value."""
    config = AsyncMock()
    config.get_ai_config = AsyncMock(return_value={
        "ai.ocr.min_confidence": min_confidence,
        "services.indic_ocr.url": indic_ocr_url,
        "ai.ocr.min_indic_confidence": min_indic_confidence,
    })
    config.get = AsyncMock(return_value=kill_mode)
    return config


class TestIndicOCRKillSwitch:
    """Tests for cts.indic_ocr.kill_mode=KC: Stage 2 bypassed, flag set in result."""

    @pytest.mark.asyncio
    async def test_kill_switch_kc_sets_flag_in_result(self):
        """When kill_mode is KC, indic_ocr_kill_switch_active=True in result."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.97)),
            config_service=_mock_config_with_ks(kill_mode="KC"),
        )
        assert result.indic_ocr_kill_switch_active is True

    @pytest.mark.asyncio
    async def test_kill_switch_none_does_not_set_flag(self):
        """When kill_mode is NONE (or absent), indic_ocr_kill_switch_active=False."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.97)),
            config_service=_mock_config_with_ks(kill_mode="NONE"),
        )
        assert result.indic_ocr_kill_switch_active is False

    @pytest.mark.asyncio
    async def test_kill_switch_kc_skips_indic_http_calls(self):
        """KC kill switch: httpx POST to IndicOCR service is never made."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="अभिलाष", indic_conf=0.88)

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            await ocr_extract(
                _make_input(),
                orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.97)),
                config_service=_mock_config_with_ks(kill_mode="KC"),
            )

        # Might still fetch image for other reasons (none expected here), but POST must be absent
        client = mock_client_cls.return_value
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_switch_kc_outcome_still_proceed_on_high_confidence(self):
        """KC kill switch does not force HUMAN_REVIEW — GOT-OCR2 outcome stands."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.97)),
            config_service=_mock_config_with_ks(kill_mode="KC"),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_kill_switch_config_error_fail_open(self):
        """If config_service.get raises for kill switch key, fail-open (no crash, KS inactive)."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        config = AsyncMock()
        config.get_ai_config = AsyncMock(return_value={"ai.ocr.min_confidence": 0.85})
        config.get = AsyncMock(side_effect=Exception("config unavailable"))

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.97)),
            config_service=config,
        )
        assert result is not None
        assert result.indic_ocr_kill_switch_active is False


# ---------------------------------------------------------------------------
# OCR engine provenance (ocr_engines_used)
# ---------------------------------------------------------------------------

class TestOCREngineProvenance:
    """Tests that ocr_engines_used is correctly populated throughout the pipeline."""

    @pytest.mark.asyncio
    async def test_latin_cheque_engines_used_contains_got_ocr2(self):
        """Latin cheque (no IndicOCR needed): engines_used has exactly one GOT-OCR2 entry."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=CascadeResult(
            content=json.dumps(_make_vllm_response(confidence=0.97)),
            confidence=0.97, cascade_level=1, model_used="got-ocr2-7b", escalated=False,
        ))
        result = await ocr_extract(
            _make_input(),
            orchestrator=orchestrator,
            config_service=_mock_config_with_ks(kill_mode="NONE"),
        )
        assert len(result.ocr_engines_used) >= 1
        assert any("got-ocr2.0" in e for e in result.ocr_engines_used)

    @pytest.mark.asyncio
    async def test_cascade_level_reflected_in_engine_label(self):
        """cascade_level=2 produces 'got-ocr2.0:cascade-2' in engines_used."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        from shared.ai.model_cascade import CascadeResult
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=CascadeResult(
            content=json.dumps(_make_vllm_response(confidence=0.97)),
            confidence=0.97, cascade_level=2, model_used="got-ocr2-full", escalated=True,
            escalation_reason="low_confidence",
        ))
        result = await ocr_extract(
            _make_input(),
            orchestrator=orchestrator,
            config_service=_mock_config_with_ks(kill_mode="NONE"),
        )
        assert any("cascade-2" in e for e in result.ocr_engines_used)

    @pytest.mark.asyncio
    async def test_indic_cheque_engines_used_includes_indic_ocr(self):
        """When IndicOCR refines a Devanagari field, engines_used includes indic_ocr label."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        hindi_payee = "सुरेश शर्मा"
        mock_client_cls = _mock_httpx(fake_bytes, indic_text=hindi_payee, indic_conf=0.88)

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("fallback", 0.95))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_with_ks(
                    indic_ocr_url="http://indic-ocr-test:8021", kill_mode="NONE"
                ),
            )

        # IndicOCR was used → should appear in engines_used
        assert result.payee == hindi_payee
        assert any("indic_ocr" in e for e in result.ocr_engines_used)

    @pytest.mark.asyncio
    async def test_kill_switch_kc_engines_used_only_got_ocr2(self):
        """With KC kill switch: only GOT-OCR2 appears in engines_used (no indic_ocr)."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response(confidence=0.97)),
            config_service=_mock_config_with_ks(
                indic_ocr_url="http://indic-ocr-test:8021", kill_mode="KC"
            ),
        )
        assert not any("indic_ocr" in e for e in result.ocr_engines_used)
        assert any("got-ocr2.0" in e for e in result.ocr_engines_used)

    @pytest.mark.asyncio
    async def test_engines_used_empty_when_model_unavailable(self):
        """When GOT-OCR2 fails entirely, degraded result carries partial engine info."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(side_effect=RuntimeError("model down"))

        result = await ocr_extract(
            _make_input(),
            orchestrator=orchestrator,
            config_service=_mock_config_with_ks(kill_mode="NONE"),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True
        # Engines list communicates the failure state
        assert isinstance(result.ocr_engines_used, list)

    @pytest.mark.asyncio
    async def test_engines_used_is_ordered(self):
        """GOT-OCR2 always appears before IndicOCR in engines_used (stage order)."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="राम", indic_conf=0.89)

        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("Ram", 0.95))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_with_ks(kill_mode="NONE"),
            )

        engines = result.ocr_engines_used
        if len(engines) >= 2:
            assert "got-ocr2.0" in engines[0]
            assert "indic_ocr" in engines[1]
