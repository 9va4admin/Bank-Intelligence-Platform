"""
Tests for modules/ej/workflows/activities/cctv_extract.py

CCTV evidence extraction for dispute resolution.
Rules:
- CCTV clips stored in MinIO only — never inline in DB
- Dispute resolution requires CCTV evidence before auto-resolution
"""
import pytest
from unittest.mock import AsyncMock


def _make_input(bank_id="test-bank", atm_id="ATM001", dispute_timestamp="2026-06-17T10:30:00+05:30"):
    from modules.ej.workflows.activities.cctv_extract import CCTVExtractInput
    return CCTVExtractInput(
        bank_id=bank_id,
        atm_id=atm_id,
        dispute_timestamp=dispute_timestamp,
        npci_claim_id="CLAIM001",
        window_seconds=120,
    )


class TestCCTVExtractInput:
    def test_requires_atm_id(self):
        from modules.ej.workflows.activities.cctv_extract import CCTVExtractInput
        with pytest.raises(Exception):
            CCTVExtractInput(bank_id="b", dispute_timestamp="ts", npci_claim_id="c", window_seconds=60)

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.atm_id = "other"


class TestCCTVExtractHappyPath:
    @pytest.mark.asyncio
    async def test_clip_fetched_returns_extracted(self):
        from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence

        mock_cctv = AsyncMock()
        mock_cctv.fetch_clip = AsyncMock(return_value={"clip_data": b"video_bytes", "camera_id": "CAM01"})

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": "cctv/test-bank/ATM001/CLAIM001.mp4"})

        result = await extract_cctv_evidence(_make_input(), cctv_adapter=mock_cctv, object_store=mock_store)
        assert result.outcome == "EXTRACTED"

    @pytest.mark.asyncio
    async def test_extracted_result_has_object_key(self):
        from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence

        expected_key = "cctv/test-bank/ATM001/CLAIM001.mp4"
        mock_cctv = AsyncMock()
        mock_cctv.fetch_clip = AsyncMock(return_value={"clip_data": b"video", "camera_id": "CAM01"})

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": expected_key})

        result = await extract_cctv_evidence(_make_input(), cctv_adapter=mock_cctv, object_store=mock_store)
        assert result.object_key == expected_key

    @pytest.mark.asyncio
    async def test_clip_stored_in_minio_not_returned_inline(self):
        """CCTV clip bytes must never be returned in the result — only MinIO reference."""
        from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence, CCTVExtractResult

        mock_cctv = AsyncMock()
        mock_cctv.fetch_clip = AsyncMock(return_value={"clip_data": b"video", "camera_id": "CAM01"})

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": "cctv/x.mp4"})

        result = await extract_cctv_evidence(_make_input(), cctv_adapter=mock_cctv, object_store=mock_store)
        # Result should have object_key reference, not raw bytes
        assert not hasattr(result, "clip_data") or result.clip_data is None


class TestCCTVExtractDegradation:
    @pytest.mark.asyncio
    async def test_cctv_unavailable_returns_unavailable(self):
        from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence

        mock_cctv = AsyncMock()
        mock_cctv.fetch_clip = AsyncMock(side_effect=RuntimeError("CCTV DVR unreachable"))

        result = await extract_cctv_evidence(_make_input(), cctv_adapter=mock_cctv, object_store=AsyncMock())
        assert result.outcome == "CCTV_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_cctv_unavailable_does_not_raise(self):
        from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence

        mock_cctv = AsyncMock()
        mock_cctv.fetch_clip = AsyncMock(side_effect=ConnectionError("timeout"))

        result = await extract_cctv_evidence(_make_input(), cctv_adapter=mock_cctv, object_store=AsyncMock())
        assert result is not None

    @pytest.mark.asyncio
    async def test_store_failure_returns_store_failed(self):
        from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence

        mock_cctv = AsyncMock()
        mock_cctv.fetch_clip = AsyncMock(return_value={"clip_data": b"video", "camera_id": "CAM01"})

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(side_effect=RuntimeError("MinIO full"))

        result = await extract_cctv_evidence(_make_input(), cctv_adapter=mock_cctv, object_store=mock_store)
        assert result.outcome in ("STORE_FAILED", "CCTV_UNAVAILABLE", "EXTRACTION_FAILED")
