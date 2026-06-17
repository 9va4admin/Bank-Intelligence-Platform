"""
Tests for modules/ej/parser/llm_parser.py

LLM-based EJ normalisation: Llama 3.3 70B (ej-reasoning queue) converts
OEM-specific raw EJ text into canonical EJ schema records.

Rules:
- OEM fingerprint must be included in every prompt
- Low confidence fields → None value + warning flag
- Confidence thresholds from config, never hardcoded
- Every result has canonical_hash (SHA-256 of normalised content)
- Never cached (each log is unique)
"""
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_input(
    raw_log="[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
    oem_fingerprint="NCR_SELFSERV",
    atm_id="ATM001",
    bank_id="test-bank",
    raw_log_hash="abc123",
):
    from modules.ej.parser.llm_parser import EJParseInput
    return EJParseInput(
        raw_log=raw_log,
        oem_fingerprint=oem_fingerprint,
        atm_id=atm_id,
        bank_id=bank_id,
        raw_log_hash=raw_log_hash,
    )


def _make_vllm_canonical():
    return {
        "transaction_type": {"value": "DISPENSE", "confidence": 0.98},
        "amount": {"value": 5000.0, "confidence": 0.97},
        "status": {"value": "SUCCESS", "confidence": 0.99},
        "timestamp": {"value": "2026-06-17T10:30:00+05:30", "confidence": 0.96},
        "error_code": {"value": None, "confidence": 0.99},
    }


class TestEJParseInput:
    def test_requires_raw_log(self):
        from modules.ej.parser.llm_parser import EJParseInput
        with pytest.raises(Exception):
            EJParseInput(oem_fingerprint="NCR", atm_id="ATM1", bank_id="b", raw_log_hash="h")

    def test_requires_oem_fingerprint(self):
        from modules.ej.parser.llm_parser import EJParseInput
        with pytest.raises(Exception):
            EJParseInput(raw_log="...", atm_id="ATM1", bank_id="b", raw_log_hash="h")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.raw_log = "other"


class TestLLMParserHappyPath:
    @pytest.mark.asyncio
    async def test_high_confidence_parse_succeeds(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.outcome == "PARSED"

    @pytest.mark.asyncio
    async def test_result_has_canonical_hash(self):
        """Every EJ canonical record must have SHA-256 hash of normalised content."""
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.canonical_hash is not None
        assert len(result.canonical_hash) == 64  # SHA-256 hex digest

    @pytest.mark.asyncio
    async def test_canonical_hash_is_sha256(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        # Verify it's a valid hex string
        int(result.canonical_hash, 16)

    @pytest.mark.asyncio
    async def test_extracts_transaction_type(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.canonical_record["transaction_type"] == "DISPENSE"

    @pytest.mark.asyncio
    async def test_extracts_amount_as_float(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.canonical_record["amount"] == 5000.0

    @pytest.mark.asyncio
    async def test_oem_fingerprint_in_prompt(self):
        """OEM fingerprint must appear in every LLM prompt."""
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=_make_vllm_canonical())

        await parse_ej_log(_make_input(oem_fingerprint="NCR_SELFSERV"), vllm_client=mock_vllm, min_confidence=0.85)
        call_prompt = mock_vllm.parse.call_args[0][0] if mock_vllm.parse.call_args[0] else \
                      mock_vllm.parse.call_args[1].get("prompt", "")
        assert "NCR_SELFSERV" in call_prompt


class TestLLMParserLowConfidence:
    @pytest.mark.asyncio
    async def test_low_confidence_field_set_to_none(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        low_conf_response = _make_vllm_canonical()
        low_conf_response["amount"] = {"value": 5000.0, "confidence": 0.60}  # below threshold

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=low_conf_response)

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.canonical_record.get("amount") is None

    @pytest.mark.asyncio
    async def test_low_confidence_field_has_warning(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        low_conf_response = _make_vllm_canonical()
        low_conf_response["amount"] = {"value": 5000.0, "confidence": 0.60}

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=low_conf_response)

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert "amount" in result.low_confidence_fields

    @pytest.mark.asyncio
    async def test_too_many_low_confidence_fields_parse_failed(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        # All fields low confidence
        bad_response = {
            k: {"value": v["value"], "confidence": 0.50}
            for k, v in _make_vllm_canonical().items()
        }

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=bad_response)

        result = await parse_ej_log(
            _make_input(), vllm_client=mock_vllm, min_confidence=0.85, max_weak_fields=2
        )
        assert result.outcome == "PARSE_FAILED"

    @pytest.mark.asyncio
    async def test_threshold_from_parameter_not_hardcoded(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        medium_conf = _make_vllm_canonical()
        medium_conf["amount"] = {"value": 5000.0, "confidence": 0.80}

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(return_value=medium_conf)

        # Loose threshold: 0.80 is OK → PARSED
        result_loose = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.75)
        mock_vllm.parse = AsyncMock(return_value=medium_conf)
        # Tight threshold: 0.80 fails → warning
        result_tight = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)

        assert "amount" not in (result_loose.low_confidence_fields or [])
        assert "amount" in (result_tight.low_confidence_fields or [])


class TestLLMParserDegradation:
    @pytest.mark.asyncio
    async def test_vllm_unavailable_outcome_parse_failed(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(side_effect=Exception("LLM server down"))

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.outcome == "PARSE_FAILED"

    @pytest.mark.asyncio
    async def test_vllm_unavailable_does_not_raise(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(side_effect=TimeoutError("GPU timeout"))

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result is not None

    @pytest.mark.asyncio
    async def test_vllm_unavailable_canonical_record_empty(self):
        from modules.ej.parser.llm_parser import parse_ej_log

        mock_vllm = AsyncMock()
        mock_vllm.parse = AsyncMock(side_effect=RuntimeError("CUDA OOM"))

        result = await parse_ej_log(_make_input(), vllm_client=mock_vllm, min_confidence=0.85)
        assert result.canonical_record == {}
