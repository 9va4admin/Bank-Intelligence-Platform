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


def _mock_config_partial(min_confidence=0.85, indic_ocr_url="http://indic-ocr-test:8021"):
    """Config mock with PARTIAL_IMAGE mode enabled."""
    config = AsyncMock()
    config.get_ai_config = AsyncMock(return_value={
        "ai.ocr.min_confidence": min_confidence,
        "ocr.mode": "PARTIAL_IMAGE",
        "services.indic_ocr.url": indic_ocr_url,
        "ai.ocr.min_indic_confidence": 0.60,
    })
    return config


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
    async def test_full_image_mode_is_default_when_key_absent(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        with patch("modules.cts.workflows.activities.ocr.httpx") as mock_httpx_mod:
            result = await ocr_extract(
                _make_input(),
                orchestrator=_mock_orchestrator(_make_vllm_response()),
                config_service=_mock_config(),
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
    async def test_image_fetch_failure_returns_human_review_degraded(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        client = AsyncMock()
        client.get = AsyncMock(side_effect=Exception("connection refused"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", MagicMock(return_value=client)):
            result = await ocr_extract(
                _make_input(),
                orchestrator=AsyncMock(),
                config_service=_mock_config_partial(),
            )

        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True
        assert "IMAGE_FETCH_FAILED" in (result.low_confidence_reason or "")

    @pytest.mark.asyncio
    async def test_date_zone_routed_to_got_ocr_not_indic_ocr(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("08/01/2013", 0.97))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls):
            await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        orchestrator.call_ocr.assert_called()
        # All image_urls for zone calls must be data URIs — not the original S3 URL
        for call in orchestrator.call_ocr.call_args_list:
            img_url = call.kwargs.get("image_url") or (call.args[0] if call.args else "")
            assert img_url.startswith("data:image/")

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
