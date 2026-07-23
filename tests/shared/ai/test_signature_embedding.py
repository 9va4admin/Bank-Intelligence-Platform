"""
Tests for shared/ai/signature_embedding.py  — TDD RED step.

Covers:
  - embed() returns correct 512-dim vector
  - embed() passes correct queue in extra_body
  - embed() raises EmbeddingModelUnavailableError on model failure
  - embed() raises EmbeddingModelUnavailableError on wrong dimension
  - cosine_similarity() correct values (identical, orthogonal, known angle)
  - cosine_similarity() safe on zero-magnitude vector (no ZeroDivisionError)
  - pack_embedding / unpack_embedding round-trip
"""
import math
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_embedding(dim: int = 512) -> list[float]:
    return [float(i % 7 + 0.1) for i in range(dim)]


def _make_vllm_client(embedding: list[float]):
    """Returns an AsyncMock vllm client whose embeddings.create returns `embedding`."""
    client = MagicMock()
    response = MagicMock()
    response.data = [MagicMock(embedding=embedding)]
    client.embeddings.create = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# SignatureEmbeddingModel.embed()
# ---------------------------------------------------------------------------

class TestEmbed:
    @pytest.mark.asyncio
    async def test_embed_returns_512_dim_list(self):
        from shared.ai.signature_embedding import SignatureEmbeddingModel
        emb = _make_fake_embedding(512)
        client = _make_vllm_client(emb)
        model = SignatureEmbeddingModel(vllm_client=client, queue="cts-sig-embeddings")
        result = await model.embed(b"fake_image", bank_id="test-bank")
        assert isinstance(result, list)
        assert len(result) == 512

    @pytest.mark.asyncio
    async def test_embed_values_are_floats(self):
        from shared.ai.signature_embedding import SignatureEmbeddingModel
        emb = _make_fake_embedding(512)
        client = _make_vllm_client(emb)
        model = SignatureEmbeddingModel(vllm_client=client, queue="cts-sig-embeddings")
        result = await model.embed(b"fake_image", bank_id="test-bank")
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_embed_passes_queue_in_extra_body(self):
        from shared.ai.signature_embedding import SignatureEmbeddingModel
        emb = _make_fake_embedding(512)
        client = _make_vllm_client(emb)
        model = SignatureEmbeddingModel(vllm_client=client, queue="cts-sig-embeddings")
        await model.embed(b"img", bank_id="test-bank")
        call_kwargs = client.embeddings.create.call_args.kwargs
        assert call_kwargs.get("extra_body", {}).get("queue") == "cts-sig-embeddings"

    @pytest.mark.asyncio
    async def test_embed_uses_model_name(self):
        from shared.ai.signature_embedding import SignatureEmbeddingModel, _MODEL_NAME
        emb = _make_fake_embedding(512)
        client = _make_vllm_client(emb)
        model = SignatureEmbeddingModel(vllm_client=client, queue="cts-sig-embeddings")
        await model.embed(b"img", bank_id="test-bank")
        call_kwargs = client.embeddings.create.call_args.kwargs
        assert call_kwargs.get("model") == _MODEL_NAME

    @pytest.mark.asyncio
    async def test_embed_raises_on_vllm_exception(self):
        from shared.ai.signature_embedding import SignatureEmbeddingModel, EmbeddingModelUnavailableError
        client = MagicMock()
        client.embeddings.create = AsyncMock(side_effect=ConnectionError("vLLM down"))
        model = SignatureEmbeddingModel(vllm_client=client, queue="cts-sig-embeddings")
        with pytest.raises(EmbeddingModelUnavailableError):
            await model.embed(b"img", bank_id="test-bank")

    @pytest.mark.asyncio
    async def test_embed_raises_on_wrong_dimension(self):
        from shared.ai.signature_embedding import SignatureEmbeddingModel, EmbeddingModelUnavailableError
        wrong_dim_emb = _make_fake_embedding(256)  # wrong: should be 512
        client = _make_vllm_client(wrong_dim_emb)
        model = SignatureEmbeddingModel(vllm_client=client, queue="cts-sig-embeddings")
        with pytest.raises(EmbeddingModelUnavailableError, match="512"):
            await model.embed(b"img", bank_id="test-bank")

    @pytest.mark.asyncio
    async def test_embed_encodes_image_as_base64(self):
        import base64
        from shared.ai.signature_embedding import SignatureEmbeddingModel
        emb = _make_fake_embedding(512)
        client = _make_vllm_client(emb)
        model = SignatureEmbeddingModel(vllm_client=client, queue="cts-sig-embeddings")
        image_bytes = b"\x89PNG\r\n\x1a\n"
        await model.embed(image_bytes, bank_id="test-bank")
        call_kwargs = client.embeddings.create.call_args.kwargs
        assert call_kwargs.get("input") == base64.b64encode(image_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# cosine_similarity()
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors_give_1(self):
        from shared.ai.signature_embedding import cosine_similarity
        v = [1.0, 2.0, 3.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_opposite_vectors_give_minus_1(self):
        from shared.ai.signature_embedding import cosine_similarity
        v = [1.0, 0.0, 0.0]
        w = [-1.0, 0.0, 0.0]
        assert abs(cosine_similarity(v, w) - (-1.0)) < 1e-6

    def test_orthogonal_vectors_give_0(self):
        from shared.ai.signature_embedding import cosine_similarity
        v = [1.0, 0.0]
        w = [0.0, 1.0]
        assert abs(cosine_similarity(v, w)) < 1e-6

    def test_known_angle(self):
        from shared.ai.signature_embedding import cosine_similarity
        # 45-degree angle → cos(45°) = 1/√2
        v = [1.0, 0.0]
        w = [1.0, 1.0]
        expected = 1.0 / math.sqrt(2)
        assert abs(cosine_similarity(v, w) - expected) < 1e-6

    def test_zero_vector_returns_0_no_exception(self):
        from shared.ai.signature_embedding import cosine_similarity
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_both_zero_returns_0(self):
        from shared.ai.signature_embedding import cosine_similarity
        assert cosine_similarity([0.0], [0.0]) == 0.0

    def test_512_dim_vectors(self):
        from shared.ai.signature_embedding import cosine_similarity
        v = _make_fake_embedding(512)
        score = cosine_similarity(v, v)
        assert abs(score - 1.0) < 1e-4


# ---------------------------------------------------------------------------
# pack_embedding / unpack_embedding
# ---------------------------------------------------------------------------

class TestPackUnpack:
    def test_pack_returns_bytes(self):
        from shared.ai.signature_embedding import pack_embedding
        v = _make_fake_embedding(512)
        result = pack_embedding(v)
        assert isinstance(result, bytes)

    def test_pack_length_is_2048(self):
        from shared.ai.signature_embedding import pack_embedding
        v = _make_fake_embedding(512)
        assert len(pack_embedding(v)) == 512 * 4  # 4 bytes per float32

    def test_unpack_returns_list_of_floats(self):
        from shared.ai.signature_embedding import pack_embedding, unpack_embedding
        v = _make_fake_embedding(512)
        unpacked = unpack_embedding(pack_embedding(v))
        assert isinstance(unpacked, list)
        assert all(isinstance(x, float) for x in unpacked)

    def test_roundtrip_preserves_values(self):
        from shared.ai.signature_embedding import pack_embedding, unpack_embedding
        v = _make_fake_embedding(512)
        roundtripped = unpack_embedding(pack_embedding(v))
        assert len(roundtripped) == 512
        for orig, rt in zip(v, roundtripped):
            assert abs(orig - rt) < 1e-5  # float32 precision

    def test_pack_different_vectors_differ(self):
        from shared.ai.signature_embedding import pack_embedding
        v1 = [1.0] * 512
        v2 = [2.0] * 512
        assert pack_embedding(v1) != pack_embedding(v2)
