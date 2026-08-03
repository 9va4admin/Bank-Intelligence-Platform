"""
Signature embedding model — shared utility for CTS and MSV.

Converts signature image bytes to a 512-dim float32 embedding vector via
the vLLM astra-sig-encoder-v1 model.  The queue is injected at construction
time so CTS uses 'cts-sig-embeddings' and MSV uses 'msv-embeddings' —
maintaining the blast-isolation rule between modules.

Image bytes are NEVER stored here.  They are base64-encoded, sent to vLLM,
and the embedding vector (no PII) is returned to the caller.

Utility functions:
  cosine_similarity(v1, v2)      — float in [-1, 1]; 0.0 on zero-magnitude input
  pack_embedding(v)              — list[float] → 2048 bytes (512 × float32 LE)
  unpack_embedding(b)            — 2048 bytes → list[float]

Both pack/unpack are used to store embeddings compactly in Redis and YugabyteDB.
"""
from __future__ import annotations

import base64
import math
import struct

import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.shared.ai")

_MODEL_NAME = "astra-sig-encoder-v1"
_EMBEDDING_DIM = 512
_PACK_FMT = f"{_EMBEDDING_DIM}f"   # 512 little-endian float32 → 2048 bytes


class EmbeddingModelUnavailableError(Exception):
    """Raised when the embedding model is unreachable or returns an unexpected response."""


class SignatureEmbeddingModel:
    """
    Wraps the vLLM embedding endpoint for signature images.

    Args:
        vllm_client:  OpenAI-compatible async client (openai.AsyncOpenAI or mock).
        queue:        vLLM queue name — 'cts-sig-embeddings' for CTS,
                      'msv-embeddings' for MSV.  Never use default queue.
    """

    def __init__(self, vllm_client, queue: str) -> None:
        self._client = vllm_client
        self._queue = queue

    async def embed(self, image_bytes: bytes, bank_id: str) -> list[float]:
        """
        Convert signature image bytes to a 512-dim float32 embedding vector.

        Image bytes are never stored.  The returned list[float] contains no PII.

        Raises:
            EmbeddingModelUnavailableError — on any connection, timeout, or
            dimension mismatch failure.  Callers must treat this as a
            graceful-degradation trigger (route to human review).
        """
        with tracer.start_as_current_span("shared.ai.embed_signature") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("model", _MODEL_NAME)
            span.set_attribute("queue", self._queue)
            span.set_attribute("image_size_bytes", len(image_bytes))

            try:
                image_b64 = base64.b64encode(image_bytes).decode("ascii")

                response = await self._client.embeddings.create(
                    model=_MODEL_NAME,
                    input=image_b64,
                    extra_body={"queue": self._queue},
                )

                embedding: list[float] = [float(v) for v in response.data[0].embedding]

                if len(embedding) != _EMBEDDING_DIM:
                    raise EmbeddingModelUnavailableError(
                        f"Expected {_EMBEDDING_DIM}-dim embedding, got {len(embedding)}"
                    )

                span.set_attribute("embedding_dim", len(embedding))
                log.info(
                    "shared.ai.embed_signature.complete",
                    bank_id=bank_id,
                    model=_MODEL_NAME,
                    queue=self._queue,
                    dim=len(embedding),
                )
                return embedding

            except EmbeddingModelUnavailableError:
                raise
            except Exception as exc:
                log.error(
                    "shared.ai.embed_signature.failed",
                    bank_id=bank_id,
                    model=_MODEL_NAME,
                    error=str(exc),
                )
                raise EmbeddingModelUnavailableError(
                    f"Embedding model unavailable: {exc}"
                ) from exc


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """
    Cosine similarity between two vectors.  Returns 0.0 if either vector has
    zero magnitude (avoids ZeroDivisionError).  Result in [-1.0, 1.0].
    """
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return dot / (mag1 * mag2)


def pack_embedding(embedding: list[float]) -> bytes:
    """Serialize 512-dim float32 vector to 2048 bytes for Redis / DB storage."""
    return struct.pack(_PACK_FMT, *embedding)


def unpack_embedding(data: bytes) -> list[float]:
    """Deserialize 2048 bytes back to a 512-dim float32 vector."""
    return list(struct.unpack(_PACK_FMT, data))
