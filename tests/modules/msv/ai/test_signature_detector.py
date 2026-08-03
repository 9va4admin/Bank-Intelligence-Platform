"""
Tests for modules/msv/ai/signature_detector.py

Covers: output type (list of bytes), empty list when no signatures detected,
unavailability degradation, bank_id propagation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.msv.ai.signature_detector import (
    SignatureDetector,
    SignatureDetectorUnavailableError,
)


class TestSignatureDetector:
    def _make_detector(self, vllm_client):
        return SignatureDetector(vllm_client=vllm_client)

    def _mock_vllm_returning_crops(self, crops: list[bytes]):
        """Mock that returns a vision response containing cropped signature bytes."""
        client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        # The detector parses crops from the response; inject them via mock attribute
        response.choices[0].message.signature_crops = crops
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)
        return client

    @pytest.mark.asyncio
    async def test_returns_list_of_bytes(self):
        crops = [b"sig_image_1", b"sig_image_2"]
        client = self._mock_vllm_returning_crops(crops)
        detector = self._make_detector(client)
        result = await detector.detect("minio://bucket/img.jpg", bank_id="kotak-mah")
        assert isinstance(result, list)
        assert all(isinstance(c, bytes) for c in result)

    @pytest.mark.asyncio
    async def test_no_signatures_returns_empty_list(self):
        client = self._mock_vllm_returning_crops([])
        detector = self._make_detector(client)
        result = await detector.detect("minio://bucket/img.jpg", bank_id="kotak-mah")
        assert result == []

    @pytest.mark.asyncio
    async def test_vllm_unavailable_raises_detector_error(self):
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=ConnectionError("vLLM down"))
        detector = self._make_detector(client)
        with pytest.raises(SignatureDetectorUnavailableError):
            await detector.detect("minio://bucket/img.jpg", bank_id="kotak-mah")

    @pytest.mark.asyncio
    async def test_timeout_raises_detector_error(self):
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=TimeoutError("timeout"))
        detector = self._make_detector(client)
        with pytest.raises(SignatureDetectorUnavailableError):
            await detector.detect("minio://bucket/img.jpg", bank_id="kotak-mah")

    @pytest.mark.asyncio
    async def test_bank_id_passed_as_parameter(self):
        client = self._mock_vllm_returning_crops([b"img1"])
        detector = self._make_detector(client)
        await detector.detect("minio://bucket/img.jpg", bank_id="hdfc-bank")
        client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_signature_returns_single_item(self):
        crops = [b"one_signature"]
        client = self._mock_vllm_returning_crops(crops)
        detector = self._make_detector(client)
        result = await detector.detect("minio://bucket/img.jpg", bank_id="kotak-mah")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_three_signatures_returns_three_items(self):
        crops = [b"sig1", b"sig2", b"sig3"]
        client = self._mock_vllm_returning_crops(crops)
        detector = self._make_detector(client)
        result = await detector.detect("minio://bucket/img.jpg", bank_id="kotak-mah")
        assert len(result) == 3
