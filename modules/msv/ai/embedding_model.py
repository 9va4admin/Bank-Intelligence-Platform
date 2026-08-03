"""
SignatureEmbeddingModel — converts signature image bytes to a 512-dim float32 embedding.

Wraps the vLLM embedding endpoint (astra-sig-encoder-v1 model).
Image bytes are NEVER stored — passed in, vector returned, bytes immediately discarded by caller.

In production: vllm_client is the OpenAI-compatible async client pointing at the vLLM server.
In tests: inject a mock client.

Raises EmbeddingModelUnavailableError on any connection/timeout/parsing failure.
Callers must treat this as a graceful-degradation trigger (route to human review).
"""
import base64

import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.ai")

_MODEL_NAME = "astra-sig-encoder-v1"
_EMBEDDING_DIM = 512


class EmbeddingModelUnavailableError(Exception):
    """Raised when the embedding model is unreachable or returns an unexpected response."""


class SignatureEmbeddingModel:
    """
    Wraps the vLLM embedding endpoint.

    Args:
        vllm_client: OpenAI-compatible async client (openai.AsyncOpenAI or equivalent).
                     In tests, pass an AsyncMock.
    """

    def __init__(self, vllm_client) -> None:
        self._client = vllm_client

    async def embed(self, image_bytes: bytes, bank_id: str) -> list[float]:
        """
        Convert signature image bytes to a 512-dim float32 embedding vector.

        Image bytes are NEVER stored. The bytes exist only for the duration of this call.
        The returned list[float] contains no PII.

        Args:
            image_bytes: raw signature crop (JPEG or PNG bytes)
            bank_id:     used for OTel tracing and logging (not included in vLLM request body)

        Returns:
            list[float] of length 512

        Raises:
            EmbeddingModelUnavailableError on any failure
        """
        with tracer.start_as_current_span("msv.ai.embed_signature") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("model", _MODEL_NAME)
            span.set_attribute("image_size_bytes", len(image_bytes))

            try:
                # Encode image bytes as base64 so it can be sent as an embedding input
                image_b64 = base64.b64encode(image_bytes).decode("ascii")

                response = await self._client.embeddings.create(
                    model=_MODEL_NAME,
                    input=image_b64,
                    extra_body={"queue": "msv-embeddings"},
                )

                embedding: list[float] = [float(v) for v in response.data[0].embedding]

                if len(embedding) != _EMBEDDING_DIM:
                    raise EmbeddingModelUnavailableError(
                        f"Expected {_EMBEDDING_DIM}-dim embedding, got {len(embedding)}"
                    )

                span.set_attribute("embedding_dim", len(embedding))
                log.info(
                    "msv.embed_signature.complete",
                    bank_id=bank_id,
                    model=_MODEL_NAME,
                    dim=len(embedding),
                )
                return embedding

            except EmbeddingModelUnavailableError:
                raise
            except Exception as exc:
                log.error(
                    "msv.embed_signature.failed",
                    bank_id=bank_id,
                    model=_MODEL_NAME,
                    error=str(exc),
                )
                raise EmbeddingModelUnavailableError(
                    f"Embedding model unavailable: {exc}"
                ) from exc
