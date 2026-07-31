"""
Tests for CTS-2010 security feature presence activity.

Item 5: Detect void pantograph, ₹ symbol, micro-lettering via Vision LLM.

Outcomes:
  PROCEED   — all mandatory features detected above min_confidence
  HUMAN_REVIEW — one or more features absent or below confidence
  DEGRADED  — vLLM unavailable (graceful degradation — never blocks clearing)

Tests cover: happy path, each missing feature, all missing, model down,
Langfuse lifecycle, no hardcoded thresholds (config_service used).
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_inp(**kwargs):
    from modules.cts.workflows.activities.security_features import SecurityFeaturesInput
    defaults = dict(
        instrument_id="INST-SF-001",
        bank_id="saraswat-coop",
        image_url="minio://cts/outward/INST-SF-001_front.tiff",
    )
    defaults.update(kwargs)
    return SecurityFeaturesInput(**defaults)


def _make_vllm_response(
    void_present=True, void_conf=0.92,
    rupee_present=True, rupee_conf=0.95,
    micro_present=True, micro_conf=0.88,
):
    """Build a fake vLLM response with structured JSON for the three features."""
    payload = {
        "void_pantograph": {"present": void_present, "confidence": void_conf},
        "rupee_symbol": {"present": rupee_present, "confidence": rupee_conf},
        "micro_lettering": {"present": micro_present, "confidence": micro_conf},
    }
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_vllm_client(response):
    """Async vLLM client mock returning the given response."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def _ai_config():
    return {
        "cts.security_features.min_confidence": 0.75,
    }


# ── happy path ────────────────────────────────────────────────────────────────

class TestSecurityFeaturesHappyPath:
    @pytest.mark.asyncio
    async def test_all_features_present_returns_proceed(self):
        from modules.cts.workflows.activities.security_features import check_security_features

        vllm = _make_vllm_client(_make_vllm_response())
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        trace = MagicMock()
        gen = MagicMock()
        gen.end = MagicMock()
        trace.generation = MagicMock(return_value=gen)
        langfuse.trace = MagicMock(return_value=trace)

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "PROCEED"
        assert result.degraded is False
        assert result.missing_features == []
        assert result.features_detected["void_pantograph"] is True
        assert result.features_detected["rupee_symbol"] is True
        assert result.features_detected["micro_lettering"] is True

    @pytest.mark.asyncio
    async def test_langfuse_generation_end_always_called(self):
        """Langfuse gen.end() must be called even on happy path."""
        from modules.cts.workflows.activities.security_features import check_security_features

        vllm = _make_vllm_client(_make_vllm_response())
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        gen = MagicMock()
        gen.end = MagicMock()
        trace = MagicMock()
        trace.generation = MagicMock(return_value=gen)
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=trace)

        await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        gen.end.assert_called_once()

    @pytest.mark.asyncio
    async def test_vllm_queue_is_explicit_cts_vision(self):
        """extra_body must specify queue='cts-vision' — never default queue."""
        from modules.cts.workflows.activities.security_features import check_security_features

        vllm = _make_vllm_client(_make_vllm_response())
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=MagicMock(end=MagicMock()))))

        await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        call_kwargs = vllm.chat.completions.create.call_args[1]
        assert "extra_body" in call_kwargs
        assert call_kwargs["extra_body"].get("queue") == "cts-vision"


# ── missing feature paths ─────────────────────────────────────────────────────

class TestMissingFeatures:
    @pytest.mark.asyncio
    async def test_void_pantograph_absent_routes_human_review(self):
        from modules.cts.workflows.activities.security_features import check_security_features

        vllm = _make_vllm_client(_make_vllm_response(void_present=False, void_conf=0.90))
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=MagicMock(end=MagicMock()))))

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "HUMAN_REVIEW"
        assert "void_pantograph" in result.missing_features

    @pytest.mark.asyncio
    async def test_rupee_symbol_absent_routes_human_review(self):
        from modules.cts.workflows.activities.security_features import check_security_features

        vllm = _make_vllm_client(_make_vllm_response(rupee_present=False, rupee_conf=0.91))
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=MagicMock(end=MagicMock()))))

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "HUMAN_REVIEW"
        assert "rupee_symbol" in result.missing_features

    @pytest.mark.asyncio
    async def test_micro_lettering_absent_routes_human_review(self):
        from modules.cts.workflows.activities.security_features import check_security_features

        vllm = _make_vllm_client(_make_vllm_response(micro_present=False, micro_conf=0.88))
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=MagicMock(end=MagicMock()))))

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "HUMAN_REVIEW"
        assert "micro_lettering" in result.missing_features

    @pytest.mark.asyncio
    async def test_low_confidence_present_counts_as_missing(self):
        """present=True but confidence below min_confidence → treated as missing."""
        from modules.cts.workflows.activities.security_features import check_security_features

        # void confidence 0.60 < min 0.75 → counts as missing even though present=True
        vllm = _make_vllm_client(_make_vllm_response(void_present=True, void_conf=0.60))
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=MagicMock(end=MagicMock()))))

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "HUMAN_REVIEW"
        assert "void_pantograph" in result.missing_features

    @pytest.mark.asyncio
    async def test_all_features_missing_human_review_with_all_in_missing(self):
        from modules.cts.workflows.activities.security_features import check_security_features

        vllm = _make_vllm_client(
            _make_vllm_response(
                void_present=False, void_conf=0.95,
                rupee_present=False, rupee_conf=0.92,
                micro_present=False, micro_conf=0.89,
            )
        )
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=MagicMock(end=MagicMock()))))

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "HUMAN_REVIEW"
        assert set(result.missing_features) == {"void_pantograph", "rupee_symbol", "micro_lettering"}


# ── degradation paths ─────────────────────────────────────────────────────────

class TestDegradation:
    @pytest.mark.asyncio
    async def test_no_vllm_client_returns_degraded(self):
        """Activity called without vllm_client → DEGRADED, never blocks clearing."""
        from modules.cts.workflows.activities.security_features import check_security_features

        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())

        result = await check_security_features(_make_inp(), vllm_client=None, config_service=config_service, langfuse=None)
        assert result.outcome == "DEGRADED"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_vllm_timeout_returns_degraded(self):
        """vLLM throws TimeoutError → DEGRADED, never raises."""
        from modules.cts.workflows.activities.security_features import check_security_features
        import asyncio

        vllm = _make_vllm_client(None)
        vllm.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError("timeout"))
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        gen = MagicMock(); gen.end = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=gen)))

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "DEGRADED"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_malformed_json_response_returns_degraded(self):
        """Model returns non-JSON → DEGRADED, never crashes."""
        from modules.cts.workflows.activities.security_features import check_security_features

        bad_msg = MagicMock(); bad_msg.content = "Sorry, I cannot analyse this image."
        bad_choice = MagicMock(); bad_choice.message = bad_msg
        bad_resp = MagicMock(); bad_resp.choices = [bad_choice]
        vllm = _make_vllm_client(bad_resp)
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        langfuse = MagicMock()
        gen = MagicMock(); gen.end = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=gen)))

        result = await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        assert result.outcome == "DEGRADED"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_langfuse_end_called_even_on_degradation(self):
        """gen.end() must be called even when vLLM fails."""
        from modules.cts.workflows.activities.security_features import check_security_features
        import asyncio

        vllm = _make_vllm_client(None)
        vllm.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError("t/o"))
        config_service = MagicMock()
        config_service.get_ai_config = AsyncMock(return_value=_ai_config())
        gen = MagicMock(); gen.end = MagicMock()
        langfuse = MagicMock()
        langfuse.trace = MagicMock(return_value=MagicMock(generation=MagicMock(return_value=gen)))

        await check_security_features(_make_inp(), vllm_client=vllm, config_service=config_service, langfuse=langfuse)
        gen.end.assert_called_once()
