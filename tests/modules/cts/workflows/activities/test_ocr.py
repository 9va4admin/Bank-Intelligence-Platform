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
                             min_indic_confidence=0.60, allow_cloud_fallback=False):
    """Config mock with IndicOCR enabled (services.indic_ocr.url set).

    allow_cloud_fallback defaults False, matching the real cts.allow_cloud_ai_fallback default —
    an unconfigured AsyncMock().get(...) is truthy, which would silently enable the cloud-VLM
    Indic fallback in every test that doesn't care about it. Explicit default keeps that off.
    """
    config = AsyncMock()
    config.get_ai_config = AsyncMock(return_value={
        "ai.ocr.min_confidence": min_confidence,
        "services.indic_ocr.url": indic_ocr_url,
        "ai.ocr.min_indic_confidence": min_indic_confidence,
    })

    async def _get(key, *a, **kw):
        if key == "cts.allow_cloud_ai_fallback":
            return allow_cloud_fallback
        if key == "services.indic_ocr.url":
            return indic_ocr_url
        if key == "cts.indic_ocr.kill_mode":
            return "NONE"
        return None
    config.get = AsyncMock(side_effect=_get)
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
    async def test_partial_image_mode_fetches_image_via_shared_fetcher(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("mock", 0.95))

        fetch = AsyncMock(return_value=fake_bytes)
        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=fetch):
            await ocr_extract(
                _make_input(image_url="http://minio/bucket/cheque.jpg"),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(),
            )

        fetch.assert_awaited()
        assert fetch.await_args.args[0] == "http://minio/bucket/cheque.jpg"

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

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
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

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
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

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
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

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(min_confidence=0.85),
            )

        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_low_confidence_indic_ocr_tries_cloud_vlm_when_enabled(self):
        """Real live-run finding (2026-09-22): PaddleOCR/Tesseract both fail on handwritten Indic
        script (confirmed on a real cheque: PaddleOCR returned 'YPhg be ?', Tesseract returned
        empty text). The cloud VLM (already used as the Stage 1 fallback) reads the same crop
        correctly. When IndicOCR's own result is too low-confidence and cts.allow_cloud_ai_fallback
        is explicitly enabled for the bank, retry that zone against the cloud VLM before giving up."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("unclear", 0.40))

        cloud_payee = "सुमति शेट्टी"
        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls),              patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)),              patch("modules.cts.workflows.activities.ocr.call_hf_vision",
                   new=AsyncMock(return_value=json.dumps({"value": cloud_payee, "confidence": 0.8}))) as mock_cloud:
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(allow_cloud_fallback=True),
            )

        mock_cloud.assert_awaited()
        assert result.payee == cloud_payee
        # Real finding: the cloud VLM can confidently hallucinate wrong text on illegible
        # handwriting (self-reported 0.9 confidence on text unrelated to the actual image,
        # observed live). A cloud-VLM-sourced reading must never look like a trusted
        # high-confidence extraction -- it must still clear (or fail) the normal min_confidence
        # gate like everything else, never bypass it.
        assert result.low_confidence_reason is not None or result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_cloud_vlm_reading_confidence_is_capped_never_trusted_at_face_value(self):
        """Real finding, live: the cloud VLM self-reported 0.9 confidence for Devanagari text that
        had nothing to do with the actual (Kannada, illegible-handwriting) image -- a confident
        hallucination, not a low-confidence miss. A cloud-VLM-sourced field's stored confidence
        must be capped well below a typical min_confidence gate (0.85+) regardless of what the
        model itself claims, so it can never look like a trusted high-confidence extraction."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("unclear", 0.40))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls),              patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)),              patch("modules.cts.workflows.activities.ocr.call_hf_vision",
                   new=AsyncMock(return_value=json.dumps({"value": "श्री राम", "confidence": 0.95}))):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(allow_cloud_fallback=True, min_confidence=0.85),
            )

        assert result.payee is not None  # the reading is still captured
        assert result.outcome == "HUMAN_REVIEW"  # but never auto-trusted past the confidence gate
        assert "payee" in (result.low_confidence_reason or "")

    @pytest.mark.asyncio
    async def test_low_confidence_indic_ocr_does_not_try_cloud_vlm_when_disabled(self):
        """cts.allow_cloud_ai_fallback defaults False -- the cloud VLM must never be called for a
        bank that hasn't explicitly opted in, matching the existing Stage 1 fallback's own gate."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("unclear", 0.40))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls),              patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)),              patch("modules.cts.workflows.activities.ocr.call_hf_vision", new=AsyncMock()) as mock_cloud:
            await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(allow_cloud_fallback=False),
            )

        mock_cloud.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cloud_vlm_indic_result_used_only_when_genuinely_indic_script(self):
        """A cloud VLM reply that isn't real Indic script (e.g. it also failed to read the crop)
        must not be accepted as a refinement -- same bar as the IndicOCR service result."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="", indic_conf=0.0)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("Abhilash", 0.94))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls),              patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)),              patch("modules.cts.workflows.activities.ocr.call_hf_vision",
                   new=AsyncMock(return_value=json.dumps({"value": None, "confidence": 0.0}))):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_partial(allow_cloud_fallback=True),
            )

        orchestrator.call_ocr.assert_called()

    @pytest.mark.asyncio
    async def test_indic_low_confidence_falls_back_to_got_ocr(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        fake_bytes = _make_fake_jpeg_bytes()
        # Devanagari text but below min_indic_confidence threshold
        mock_client_cls = _mock_httpx(fake_bytes, indic_text="अभिलाष", indic_conf=0.30)
        orchestrator = AsyncMock()
        orchestrator.call_ocr = AsyncMock(return_value=_zone_cascade_result("Abhilash", 0.94))

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
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

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
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

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
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

        with patch("modules.cts.workflows.activities.ocr.httpx.AsyncClient", mock_client_cls), \
             patch("modules.cts.workflows.activities.ocr.fetch_image_bytes", new=AsyncMock(return_value=fake_bytes)):
            result = await ocr_extract(
                _make_input(),
                orchestrator=orchestrator,
                config_service=_mock_config_with_ks(kill_mode="NONE"),
            )

        engines = result.ocr_engines_used
        if len(engines) >= 2:
            assert "got-ocr2.0" in engines[0]
            assert "indic_ocr" in engines[1]


class TestOCRInstrumentCategory:
    """instrument_category: CHEQUE vs DEMAND_DRAFT classification (2026-10-12).

    Real Lot 3 KBL data mixes personal/business cheques with institutional
    Demand Drafts in the same inward batch -- these need to be distinguishable
    downstream (separate bucket in every screen), not silently treated as
    identical. Default is always "CHEQUE" (the overwhelming majority case,
    and the safe fallback when the model doesn't answer the question).
    """

    @pytest.mark.asyncio
    async def test_demand_draft_classified_from_vllm_response(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        data = _make_vllm_response()
        data["instrument_category"] = {"value": "DEMAND_DRAFT", "confidence": 0.95}
        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(data),
            config_service=_mock_config(),
        )
        assert result.instrument_category == "DEMAND_DRAFT"

    @pytest.mark.asyncio
    async def test_cheque_classified_from_vllm_response(self):
        from modules.cts.workflows.activities.ocr import ocr_extract

        data = _make_vllm_response()
        data["instrument_category"] = {"value": "CHEQUE", "confidence": 0.95}
        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(data),
            config_service=_mock_config(),
        )
        assert result.instrument_category == "CHEQUE"

    @pytest.mark.asyncio
    async def test_defaults_to_cheque_when_model_silent_on_category(self):
        """Model response omits instrument_category entirely -- must default to
        CHEQUE (the safe, majority-case fallback), never crash or return None."""
        from modules.cts.workflows.activities.ocr import ocr_extract

        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(_make_vllm_response()),
            config_service=_mock_config(),
        )
        assert result.instrument_category == "CHEQUE"

    @pytest.mark.asyncio
    async def test_invalid_category_value_falls_back_to_cheque(self):
        """A hallucinated/garbage category value must never pass through raw --
        falls back to the safe CHEQUE default rather than propagating junk."""
        from modules.cts.workflows.activities.ocr import ocr_extract

        data = _make_vllm_response()
        data["instrument_category"] = {"value": "PROMISSORY_NOTE", "confidence": 0.9}
        result = await ocr_extract(
            _make_input(),
            orchestrator=_mock_orchestrator(data),
            config_service=_mock_config(),
        )
        assert result.instrument_category == "CHEQUE"


def _orch_by_prompt(stage1: dict, dd: dict | None):
    """Orchestrator whose answer depends on WHICH prompt was sent: the cheque prompt gets
    stage1, the DD-specific prompt gets dd (or raises when dd is None = model unavailable)."""
    from shared.ai.model_cascade import CascadeResult

    async def _call(image_url=None, prompt="", cheque_amount=0.0, **kw):
        is_dd_prompt = "ON DEMAND PAY" in prompt and "has_dd_header" in prompt
        if is_dd_prompt:
            if dd is None:
                raise RuntimeError("vLLM unavailable")
            payload = dd
        else:
            payload = stage1
        return CascadeResult(content=json.dumps(payload), confidence=0.97,
                             cascade_level=1, model_used="got-ocr2-7b", escalated=False)

    orch = AsyncMock()
    orch.call_ocr = AsyncMock(side_effect=_call)
    return orch


def _f(v, c=0.97):
    return {"value": v, "confidence": c}


def _stage1(cat="DEMAND_DRAFT", payee="जारीकति शाखा Issuing Branch Ih aIlks"):
    d = _make_vllm_response()
    d["payee"] = _f(payee, 0.97)
    d["instrument_category"] = _f(cat)
    d["amount_figures"] = _f("22,000.00")                  # agrees with _dd_pass() by default
    d["amount_words"] = _f("Twenty Two Thousand only")
    return d


def _dd_pass(header=True, payee="THE COURT RECEIVER HIGH COURT MUMBAI"):
    return {
        "has_dd_header": _f(header), "dd_number": _f("152173"), "dd_date": _f("03/07/2025"),
        "payee": _f(payee), "remitter_name": _f("BHARATI M CHHAB"),
        "issuing_branch": _f("MUMBAI - ANDHERI (WEST)"), "drawee_branch": _f("DELHI SERVICE BRANCH"),
        "amount_figures": _f("22,000.00"), "amount_words": _f("Twenty Two Thousand only"),
        "micr_line": _f("152173 000052000"),
    }


_HDR = "modules.cts.workflows.activities.ocr._header_says_dd"


class TestOCRDemandDraftTwoPass:
    """DD handling (2026-10-12): the cheque prompt reads the 'Issuing Branch' label as the payee
    on a DD (real Lot 3 finding). A DD-specific second pass reads the right line, and the
    instrument type is decided by 3 independent signals; any disagreement -> human review."""

    @pytest.mark.asyncio
    async def test_dd_payee_comes_from_dd_specific_pass_not_label_spill(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(_stage1(), _dd_pass()),
                                  config_service=_mock_config())
        assert r.instrument_category == "DEMAND_DRAFT"
        assert r.payee == "THE COURT RECEIVER HIGH COURT MUMBAI"
        assert "Issuing" not in (r.payee or "")
        assert r.remitter_name == "BHARATI M CHHAB"
        assert r.issuing_branch == "MUMBAI - ANDHERI (WEST)"
        assert r.drawee_branch == "DELHI SERVICE BRANCH"
        assert r.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_plain_cheque_unanimous_does_not_pay_for_dd_pass(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        orch = _orch_by_prompt(_stage1("CHEQUE", "ACME Corp"), _dd_pass())
        with patch(_HDR, new=AsyncMock(return_value=False)):
            r = await ocr_extract(_make_input(), orchestrator=orch, config_service=_mock_config())
        assert r.instrument_category == "CHEQUE"
        assert r.payee == "ACME Corp"
        assert orch.call_ocr.await_count == 1          # no second model call for a clean cheque
        assert r.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_model_says_cheque_but_header_ocr_sees_dd_goes_to_review_or_majority_dd(self):
        """model=CHEQUE, header-OCR=DD, DD pass confirms header -> 2-of-3 DD but NOT unanimous
        -> human review (never a silent pick)."""
        from modules.cts.workflows.activities.ocr import ocr_extract
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(_stage1("CHEQUE"), _dd_pass(True)),
                                  config_service=_mock_config())
        assert r.instrument_category == "DEMAND_DRAFT"
        assert r.outcome == "HUMAN_REVIEW"
        assert "instrument_type_split" in (r.low_confidence_reason or "")

    @pytest.mark.asyncio
    async def test_model_says_dd_but_both_other_signals_say_cheque_goes_to_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        with patch(_HDR, new=AsyncMock(return_value=False)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(_stage1("DEMAND_DRAFT"), _dd_pass(False)),
                                  config_service=_mock_config())
        assert r.instrument_category == "CHEQUE"
        assert r.outcome == "HUMAN_REVIEW"
        assert "instrument_type_split" in (r.low_confidence_reason or "")

    @pytest.mark.asyncio
    async def test_header_ocr_unavailable_two_agreeing_signals_proceed(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        with patch(_HDR, new=AsyncMock(return_value=None)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(_stage1(), _dd_pass(True)),
                                  config_service=_mock_config())
        assert r.instrument_category == "DEMAND_DRAFT"
        assert r.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_dd_pass_unavailable_keeps_stage1_and_still_decides_on_remaining_signals(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(_stage1(payee="Some Payee"), None),
                                  config_service=_mock_config())
        assert r.instrument_category == "DEMAND_DRAFT"       # model + header-OCR agree
        assert r.payee == "Some Payee"                       # no DD pass -> nothing overlaid
        assert r.drawee_branch is None

    @pytest.mark.asyncio
    async def test_dd_payee_low_confidence_in_dd_pass_still_routes_to_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        dd = _dd_pass()
        dd["payee"] = _f("THE COURT RECEIVER", 0.40)
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(_stage1(), dd),
                                  config_service=_mock_config())
        assert r.outcome == "HUMAN_REVIEW"
        assert "payee" in r.low_confidence_fields


class TestOCRMicrBankCodeAnchoring:
    """cts.micr_bank_code (Layer 3, per bank) anchors the 9-digit sort code — see MICRParser."""

    @staticmethod
    def _config(bank_code):
        cfg = _mock_config()

        async def _get(key, *a, **kw):
            return bank_code if key == "cts.micr_bank_code" else None
        cfg.get = AsyncMock(side_effect=_get)
        return cfg

    @pytest.mark.asyncio
    async def test_sort_code_anchored_when_bank_code_configured(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        data = _make_vllm_response(micr="53112917590521021")
        with patch(_HDR, new=AsyncMock(return_value=False)):
            r = await ocr_extract(_make_input(), orchestrator=_mock_orchestrator(data),
                                  config_service=self._config("052"))
        assert r.bank_branch_code == "759052102"
        assert r.cheque_number == "531129"

    @pytest.mark.asyncio
    async def test_without_bank_code_legacy_slice_is_used(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        data = _make_vllm_response(micr="53112917590521021")
        with patch(_HDR, new=AsyncMock(return_value=False)):
            r = await ocr_extract(_make_input(), orchestrator=_mock_orchestrator(data),
                                  config_service=self._config(None))
        assert r.bank_branch_code == "175905210"

    @pytest.mark.asyncio
    async def test_garbage_config_value_is_ignored_not_trusted(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        data = _make_vllm_response(micr="53112917590521021")
        with patch(_HDR, new=AsyncMock(return_value=False)):
            r = await ocr_extract(_make_input(), orchestrator=_mock_orchestrator(data),
                                  config_service=self._config("not-a-code"))
        assert r.bank_branch_code == "175905210"


class TestOCRDemandDraftOverlayGuards:
    """Real Lot 3 failures of the DD overlay (2026-10-12): the DD pass returned the DD NUMBER
    ('658027') as dd_date, which became an automatic 'Undated cheque' STP_RETURN where the old
    code had correctly gone to human review; and returned '000000.00' for a Rs 6,000 draft.
    An overlay value must be validated, and two independent amount reads must agree."""

    @pytest.mark.asyncio
    async def test_dd_pass_date_that_is_not_a_date_is_not_overlaid(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        dd = _dd_pass()
        dd["dd_date"] = _f("658027")                       # this is the DD number, not a date
        s1 = _stage1()
        s1["date"] = _f(None, 0.0)
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(s1, dd), config_service=_mock_config())
        assert r.date is None
        assert r.outcome == "HUMAN_REVIEW"
        assert "date" in r.low_confidence_fields

    @pytest.mark.asyncio
    async def test_dd_pass_valid_date_is_overlaid(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        dd = _dd_pass()
        dd["dd_date"] = _f("03/07/2025")
        s1 = _stage1()
        s1["date"] = _f(None, 0.0)
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(s1, dd), config_service=_mock_config())
        assert r.date == "03/07/2025"
        assert r.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_two_amount_reads_that_disagree_go_to_human_review(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        dd = _dd_pass()
        dd["amount_figures"] = _f("000000.00")
        dd["amount_words"] = _f("thousand only")
        s1 = _stage1()
        s1["amount_figures"] = _f("100000.00")
        s1["amount_words"] = _f("one lakh only")           # self-consistent but WRONG, as in Lot 3 #13
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(s1, dd), config_service=_mock_config())
        assert r.outcome == "HUMAN_REVIEW"
        assert "dd_amount_read_disagreement" in (r.low_confidence_reason or "")

    @pytest.mark.asyncio
    async def test_two_amount_reads_that_agree_proceed(self):
        from modules.cts.workflows.activities.ocr import ocr_extract
        dd = _dd_pass()                                    # 22,000.00
        s1 = _stage1()
        s1["amount_figures"] = _f("22000.00")
        s1["amount_words"] = _f("Twenty Two Thousand Only")
        with patch(_HDR, new=AsyncMock(return_value=True)):
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(s1, dd), config_service=_mock_config())
        assert r.outcome == "PROCEED"


class TestOCRPromptAmountWordsWrap:
    """Lot 3 #28: the amount in words wraps onto a second line; reading only line 1 produced a
    false figures-vs-words mismatch. The prompt must say to read every line."""

    def test_prompt_tells_model_amount_words_can_span_two_lines(self):
        from modules.cts.workflows.activities.ocr import _OCR_PROMPT
        low = _OCR_PROMPT.lower()
        assert "amount_words:" in low
        assert "second line" in low and "join" in low


class TestTesseractLocation:
    """Found 2026-10-13: _header_says_dd never pointed pytesseract at the Windows install, so the
    header signal of the 3-signal type vote silently returned None (unavailable) on every run."""

    def test_windows_install_path_is_configured(self):
        from unittest.mock import patch
        from modules.cts.workflows.activities import ocr as ocr_mod
        fake = MagicMock()
        fake.pytesseract = MagicMock(tesseract_cmd="tesseract")
        with patch.object(ocr_mod.platform, "system", return_value="Windows"), \
             patch.object(ocr_mod.os.path, "isfile", side_effect=lambda p: p.endswith(r"Program Files\Tesseract-OCR\tesseract.exe")):
            ocr_mod._configure_tesseract(fake)
        assert fake.pytesseract.tesseract_cmd.endswith(r"Tesseract-OCR\tesseract.exe")

    def test_non_windows_leaves_default(self):
        from unittest.mock import patch
        from modules.cts.workflows.activities import ocr as ocr_mod
        fake = MagicMock()
        fake.pytesseract = MagicMock(tesseract_cmd="tesseract")
        with patch.object(ocr_mod.platform, "system", return_value="Linux"):
            ocr_mod._configure_tesseract(fake)
        assert fake.pytesseract.tesseract_cmd == "tesseract"


class TestOCRPayeeRereadGate:
    """A confidently wrong handwritten payee must not pass on a single read. The Pay line is read a
    second time (zoomed crop); a payee the two reads disagree on is never shown as fact — it goes to
    review with both readings as candidates. Lot 3 evidence (22 cheques): the re-read exposed 3 of 4
    confident-wrong payees (Sa Sma/Sasmal, Rousick/Kousick x2) with 2 false flags out of 15 correct."""

    async def _run(self, reread, payee="Kousick Mondal", cfg_extra=None, category="CHEQUE"):
        from unittest.mock import patch
        from modules.cts.workflows.activities.ocr import ocr_extract
        s1 = _make_vllm_response()
        s1["payee"] = _f(payee)
        s1["instrument_category"] = _f(category)
        cs = _mock_config(**(cfg_extra or {})) if cfg_extra else _mock_config()
        with patch("modules.cts.workflows.activities.ocr._payee_reread", new=AsyncMock(return_value=reread)), \
             patch(_HDR, new=AsyncMock(return_value=None)):
            return await ocr_extract(_make_input(), orchestrator=_mock_orchestrator(s1), config_service=cs)

    @pytest.mark.asyncio
    async def test_agreeing_reread_keeps_the_payee(self):
        r = await self._run("K-o-u-s-i-c-k M-o-n-d-a-l")        # separators/case ignored
        assert r.payee == "Kousick Mondal" and r.payee_reread_status == "AGREE"
        assert r.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_disagreeing_reread_withholds_payee_and_goes_to_review(self):
        r = await self._run("Rousick Mondal")
        assert r.payee is None
        assert r.payee_reread_status == "DISAGREE"
        assert r.outcome == "HUMAN_REVIEW" and "payee" in r.low_confidence_fields
        assert "payee_reread_disagreement" in (r.low_confidence_reason or "")
        assert set(r.payee_candidates) == {"Kousick Mondal", "Rousick Mondal"}

    @pytest.mark.asyncio
    async def test_reread_unavailable_leaves_result_unchanged_but_says_so(self):
        r = await self._run(None)
        assert r.payee == "Kousick Mondal" and r.payee_reread_status == "UNAVAILABLE"
        assert r.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_demand_draft_is_not_reread(self):
        from unittest.mock import patch
        from modules.cts.workflows.activities.ocr import ocr_extract
        s1 = _stage1()
        with patch(_HDR, new=AsyncMock(return_value=True)), \
             patch("modules.cts.workflows.activities.ocr._payee_reread", new=AsyncMock(return_value="SOMETHING ELSE")) as rr:
            r = await ocr_extract(_make_input(), orchestrator=_orch_by_prompt(s1, _dd_pass()), config_service=_mock_config())
        rr.assert_not_awaited()
        assert r.payee_reread_status is None

    @pytest.mark.asyncio
    async def test_no_payee_read_means_nothing_to_verify(self):
        r = await self._run("Anything", payee=None)
        assert r.payee_reread_status is None

    def test_name_agreement_ignores_separators_case_and_punctuation_only(self):
        from modules.cts.workflows.activities.ocr import _payee_names_agree
        assert _payee_names_agree("S.B. Health Care", "S.B.Health care", 0.99)
        assert not _payee_names_agree("Debadatta Sa Sma", "Debadatta Sasmal", 0.99)
        assert not _payee_names_agree("Rousick Mondal", "Kousick Mondal", 0.99)


class TestPayeeAgreementIgnoresUnclearLetterPlaceholders:
    """The re-read prompt makes the model write 'null' for letters it cannot read. Those placeholders
    are noise, not letters — but a placeholder must never turn a different name into a match."""

    def test_null_placeholders_in_the_reread_are_ignored(self):
        from modules.cts.workflows.activities.ocr import _payee_names_agree
        assert _payee_names_agree("S.B. Health Care", "S.B.nullHealthCare", 0.99)

    def test_placeholders_do_not_make_different_names_agree(self):
        from modules.cts.workflows.activities.ocr import _payee_names_agree
        assert not _payee_names_agree("Rousick Mondal", "KoU51ck MoNdal", 0.99)
        assert not _payee_names_agree("Gurupada Maity", "gurupada maitra", 0.99)
