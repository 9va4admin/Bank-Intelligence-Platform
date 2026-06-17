"""
Tests for modules/ej/workflows/activities/llm_parse.py

Wraps the EJ LLM parser as a Temporal activity.
Reads raw log from object store, delegates to llm_parser.parse_ej_log.
"""
import pytest
from unittest.mock import AsyncMock


def _make_input(
    raw_log_hash="abc123",
    oem_fingerprint="NCR_SELFSERV",
    atm_id="ATM001",
    bank_id="test-bank",
    object_key="ej/test-bank/ATM001/abc123.log",
):
    from modules.ej.workflows.activities.llm_parse import EJLLMParseActivityInput
    return EJLLMParseActivityInput(
        raw_log_hash=raw_log_hash,
        oem_fingerprint=oem_fingerprint,
        atm_id=atm_id,
        bank_id=bank_id,
        object_key=object_key,
    )


def _make_vllm_canonical():
    return {
        "transaction_type": {"value": "DISPENSE", "confidence": 0.98},
        "amount": {"value": 5000.0, "confidence": 0.97},
        "status": {"value": "SUCCESS", "confidence": 0.99},
        "timestamp": {"value": "2026-06-17T10:30:00+05:30", "confidence": 0.96},
        "error_code": {"value": None, "confidence": 0.99},
    }


class TestEJLLMParseActivityInput:
    def test_requires_raw_log_hash(self):
        from modules.ej.workflows.activities.llm_parse import EJLLMParseActivityInput
        with pytest.raises(Exception):
            EJLLMParseActivityInput(oem_fingerprint="NCR", atm_id="ATM1", bank_id="b", object_key="k")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.atm_id = "other"


class TestEJLLMParseActivityHappyPath:
    @pytest.mark.asyncio
    async def test_returns_normalised_outcome(self):
        from modules.ej.workflows.activities.llm_parse import llm_parse_ej

        mock_store = AsyncMock()
        mock_store.get = AsyncMock(return_value="[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK")

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await llm_parse_ej(_make_input(), object_store=mock_store, vllm_client=mock_vllm, min_confidence=0.85)
        assert result.outcome == "NORMALISED"

    @pytest.mark.asyncio
    async def test_result_has_canonical_record(self):
        from modules.ej.workflows.activities.llm_parse import llm_parse_ej

        mock_store = AsyncMock()
        mock_store.get = AsyncMock(return_value="[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK")

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await llm_parse_ej(_make_input(), object_store=mock_store, vllm_client=mock_vllm, min_confidence=0.85)
        assert result.canonical_record is not None
        assert result.canonical_record.get("transaction_type") == "DISPENSE"

    @pytest.mark.asyncio
    async def test_result_has_canonical_hash(self):
        from modules.ej.workflows.activities.llm_parse import llm_parse_ej

        mock_store = AsyncMock()
        mock_store.get = AsyncMock(return_value="log content")

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await llm_parse_ej(_make_input(), object_store=mock_store, vllm_client=mock_vllm, min_confidence=0.85)
        assert result.canonical_hash is not None
        assert len(result.canonical_hash) == 64


class TestEJLLMParseActivityDegradation:
    @pytest.mark.asyncio
    async def test_object_store_failure_returns_parse_failed(self):
        from modules.ej.workflows.activities.llm_parse import llm_parse_ej

        mock_store = AsyncMock()
        mock_store.get = AsyncMock(side_effect=RuntimeError("MinIO unreachable"))

        mock_vllm = AsyncMock()

        result = await llm_parse_ej(_make_input(), object_store=mock_store, vllm_client=mock_vllm, min_confidence=0.85)
        assert result.outcome == "PARSE_FAILED"

    @pytest.mark.asyncio
    async def test_vllm_failure_returns_parse_failed(self):
        from modules.ej.workflows.activities.llm_parse import llm_parse_ej

        mock_store = AsyncMock()
        mock_store.get = AsyncMock(return_value="raw log content")

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(side_effect=RuntimeError("GPU OOM"))

        result = await llm_parse_ej(_make_input(), object_store=mock_store, vllm_client=mock_vllm, min_confidence=0.85)
        assert result.outcome == "PARSE_FAILED"

    @pytest.mark.asyncio
    async def test_failure_does_not_raise(self):
        from modules.ej.workflows.activities.llm_parse import llm_parse_ej

        mock_store = AsyncMock()
        mock_store.get = AsyncMock(side_effect=ConnectionError("timeout"))

        result = await llm_parse_ej(_make_input(), object_store=mock_store, vllm_client=AsyncMock(), min_confidence=0.85)
        assert result is not None
