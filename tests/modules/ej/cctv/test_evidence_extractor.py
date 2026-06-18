"""
Tests for modules/ej/cctv/evidence_extractor.py

TDD: these tests are written before implementation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestCCTVExtractionInput:
    def test_frozen_model(self):
        from modules.ej.cctv.evidence_extractor import CCTVExtractionInput
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        with pytest.raises(Exception):
            inp.bank_id = "other"  # frozen — must raise

    def test_fields_present(self):
        from modules.ej.cctv.evidence_extractor import CCTVExtractionInput
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        assert inp.bank_id == "test-bank"
        assert inp.atm_id == "ATM001"
        assert inp.branch_id == "BR001"
        assert inp.timestamp == "2026-06-17T10:30:00Z"
        assert inp.claim_id == "CLAIM-001"


class TestCCTVExtractionResult:
    def test_frozen_model(self):
        from modules.ej.cctv.evidence_extractor import CCTVExtractionResult
        result = CCTVExtractionResult(
            outcome="EXTRACTED",
            object_key="cctv/test-bank/ATM001/CLAIM-001.mp4",
            clip_duration_seconds=30,
            frame_count=750,
            bank_id="test-bank",
        )
        with pytest.raises(Exception):
            result.outcome = "NO_FOOTAGE"  # frozen

    def test_optional_fields(self):
        from modules.ej.cctv.evidence_extractor import CCTVExtractionResult
        result = CCTVExtractionResult(outcome="NO_FOOTAGE", bank_id="test-bank")
        assert result.object_key is None
        assert result.clip_duration_seconds is None
        assert result.frame_count is None


class TestExtractCctvEvidence:
    @pytest.mark.asyncio
    async def test_happy_path_returns_extracted(self):
        from modules.ej.cctv.evidence_extractor import (
            CCTVExtractionInput,
            extract_cctv_evidence,
        )
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        cctv_adapter = AsyncMock()
        cctv_adapter.fetch_clip.return_value = {
            "clip_bytes": b"fake_video_data",
            "duration_seconds": 30,
            "frame_count": 750,
        }
        object_store = AsyncMock()
        object_store.put.return_value = {"object_key": "cctv/test-bank/ATM001/CLAIM-001.mp4"}

        result = await extract_cctv_evidence(inp, cctv_adapter=cctv_adapter, object_store=object_store)

        assert result.outcome == "EXTRACTED"
        assert result.bank_id == "test-bank"
        assert result.clip_duration_seconds == 30
        assert result.frame_count == 750
        assert result.object_key is not None

    @pytest.mark.asyncio
    async def test_object_key_format(self):
        from modules.ej.cctv.evidence_extractor import (
            CCTVExtractionInput,
            extract_cctv_evidence,
        )
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        cctv_adapter = AsyncMock()
        cctv_adapter.fetch_clip.return_value = {
            "clip_bytes": b"data",
            "duration_seconds": 10,
            "frame_count": 250,
        }
        object_store = AsyncMock()
        object_store.put.return_value = {}

        await extract_cctv_evidence(inp, cctv_adapter=cctv_adapter, object_store=object_store)

        # Verify put was called with correct key format
        call_kwargs = object_store.put.call_args
        assert call_kwargs is not None
        key_used = call_kwargs.kwargs.get("key") or call_kwargs.args[0]
        assert "cctv/test-bank/ATM001/CLAIM-001.mp4" in str(key_used)

    @pytest.mark.asyncio
    async def test_no_footage_error_returns_no_footage(self):
        from modules.ej.cctv.evidence_extractor import (
            CCTVExtractionInput,
            NoFootageError,
            extract_cctv_evidence,
        )
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        cctv_adapter = AsyncMock()
        cctv_adapter.fetch_clip.side_effect = NoFootageError("no footage available")
        object_store = AsyncMock()

        result = await extract_cctv_evidence(inp, cctv_adapter=cctv_adapter, object_store=object_store)

        assert result.outcome == "NO_FOOTAGE"
        assert result.bank_id == "test-bank"
        assert result.object_key is None

    @pytest.mark.asyncio
    async def test_generic_exception_returns_adapter_error(self):
        from modules.ej.cctv.evidence_extractor import (
            CCTVExtractionInput,
            extract_cctv_evidence,
        )
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        cctv_adapter = AsyncMock()
        cctv_adapter.fetch_clip.side_effect = ConnectionError("CCTV adapter unreachable")
        object_store = AsyncMock()

        result = await extract_cctv_evidence(inp, cctv_adapter=cctv_adapter, object_store=object_store)

        assert result.outcome == "ADAPTER_ERROR"
        assert result.bank_id == "test-bank"

    @pytest.mark.asyncio
    async def test_adapter_error_does_not_raise(self):
        """ADAPTER_ERROR must not propagate the exception — graceful degradation."""
        from modules.ej.cctv.evidence_extractor import (
            CCTVExtractionInput,
            extract_cctv_evidence,
        )
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        cctv_adapter = AsyncMock()
        cctv_adapter.fetch_clip.side_effect = RuntimeError("unexpected error")
        object_store = AsyncMock()

        # Should not raise
        result = await extract_cctv_evidence(inp, cctv_adapter=cctv_adapter, object_store=object_store)
        assert result.outcome == "ADAPTER_ERROR"

    @pytest.mark.asyncio
    async def test_result_is_frozen(self):
        from modules.ej.cctv.evidence_extractor import (
            CCTVExtractionInput,
            extract_cctv_evidence,
        )
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        cctv_adapter = AsyncMock()
        cctv_adapter.fetch_clip.return_value = {
            "clip_bytes": b"data",
            "duration_seconds": 5,
            "frame_count": 125,
        }
        object_store = AsyncMock()
        object_store.put.return_value = {}

        result = await extract_cctv_evidence(inp, cctv_adapter=cctv_adapter, object_store=object_store)

        with pytest.raises(Exception):
            result.outcome = "MODIFIED"  # frozen model must raise

    @pytest.mark.asyncio
    async def test_object_store_error_returns_adapter_error(self):
        """If object store fails after successful clip fetch → ADAPTER_ERROR."""
        from modules.ej.cctv.evidence_extractor import (
            CCTVExtractionInput,
            extract_cctv_evidence,
        )
        inp = CCTVExtractionInput(
            bank_id="test-bank",
            atm_id="ATM001",
            branch_id="BR001",
            timestamp="2026-06-17T10:30:00Z",
            claim_id="CLAIM-001",
        )
        cctv_adapter = AsyncMock()
        cctv_adapter.fetch_clip.return_value = {
            "clip_bytes": b"data",
            "duration_seconds": 10,
            "frame_count": 250,
        }
        object_store = AsyncMock()
        object_store.put.side_effect = IOError("MinIO write failed")

        result = await extract_cctv_evidence(inp, cctv_adapter=cctv_adapter, object_store=object_store)

        assert result.outcome == "ADAPTER_ERROR"
        assert result.bank_id == "test-bank"
