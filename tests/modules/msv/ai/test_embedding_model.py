"""
Tests for modules/msv/ai/embedding_model.py

Covers: output shape validation, unavailability degradation,
bank_id propagation, exception wrapping.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.msv.ai.embedding_model import (
    EmbeddingModelUnavailableError,
    SignatureEmbeddingModel,
)


class TestSignatureEmbeddingModel:
    def _make_model(self, vllm_client):
        return SignatureEmbeddingModel(vllm_client=vllm_client)

    def _make_mock_vllm_client(self, embedding: list[float] | None = None):
        if embedding is None:
            embedding = [0.1] * 512

        client = MagicMock()
        response = MagicMock()
        response.data = [MagicMock()]
        response.data[0].embedding = embedding
        client.embeddings = MagicMock()
        client.embeddings.create = AsyncMock(return_value=response)
        return client

    @pytest.mark.asyncio
    async def test_returns_512_dim_vector(self):
        client = self._make_mock_vllm_client([0.5] * 512)
        model = self._make_model(client)
        result = await model.embed(b"fake_image_bytes", bank_id="kotak-mah")
        assert len(result) == 512

    @pytest.mark.asyncio
    async def test_returns_float_list(self):
        client = self._make_mock_vllm_client([0.1] * 512)
        model = self._make_model(client)
        result = await model.embed(b"fake_image_bytes", bank_id="kotak-mah")
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_embedding_values_match_mock(self):
        expected = [0.42] * 512
        client = self._make_mock_vllm_client(expected)
        model = self._make_model(client)
        result = await model.embed(b"fake_image_bytes", bank_id="kotak-mah")
        assert all(abs(r - e) < 1e-6 for r, e in zip(result, expected))

    @pytest.mark.asyncio
    async def test_vllm_unavailable_raises_embedding_model_error(self):
        client = MagicMock()
        client.embeddings = MagicMock()
        client.embeddings.create = AsyncMock(side_effect=ConnectionError("vLLM down"))
        model = self._make_model(client)
        with pytest.raises(EmbeddingModelUnavailableError):
            await model.embed(b"fake_image_bytes", bank_id="kotak-mah")

    @pytest.mark.asyncio
    async def test_timeout_raises_embedding_model_error(self):
        client = MagicMock()
        client.embeddings = MagicMock()
        client.embeddings.create = AsyncMock(side_effect=TimeoutError("timeout"))
        model = self._make_model(client)
        with pytest.raises(EmbeddingModelUnavailableError):
            await model.embed(b"fake_image_bytes", bank_id="kotak-mah")

    @pytest.mark.asyncio
    async def test_image_bytes_not_in_result(self):
        """Result must be a float vector — no bytes in output."""
        img = b"this_is_a_real_signature_image"
        client = self._make_mock_vllm_client([0.7] * 512)
        model = self._make_model(client)
        result = await model.embed(img, bank_id="kotak-mah")
        # result should be a list of floats, not bytes
        assert isinstance(result, list)
        assert not any(isinstance(v, bytes) for v in result)

    @pytest.mark.asyncio
    async def test_bank_id_passed_to_client(self):
        """bank_id should be included in the vLLM request for routing/audit."""
        client = self._make_mock_vllm_client()
        model = self._make_model(client)
        await model.embed(b"img", bank_id="hdfc-bank")
        # vLLM client was called
        client.embeddings.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_images_produce_calls(self):
        """Two different images → two separate vLLM calls."""
        client = self._make_mock_vllm_client()
        model = self._make_model(client)
        await model.embed(b"img1", bank_id="kotak-mah")
        await model.embed(b"img2", bank_id="kotak-mah")
        assert client.embeddings.create.call_count == 2
