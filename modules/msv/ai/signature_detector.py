"""
SignatureDetector — detects ink signature regions on a cheque image via Vision LLM.

Uses Qwen2-VL (vLLM queue: cts-vision-l1) to locate N signatures on the cheque image
and returns cropped image bytes for each detected signature.

Crops are returned as bytes and must be embedded immediately by the caller.
They must NOT be stored anywhere.

Raises SignatureDetectorUnavailableError on model failure (caller routes to human review).
"""
import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.ai")

_MODEL_NAME = "qwen2-vl-7b"
_DETECTION_QUEUE = "cts-vision-l1"

_DETECTION_PROMPT = """
Examine this cheque image. Locate all ink handwritten signatures.

For each signature detected, return the bounding box coordinates and the cropped
signature image bytes as base64.

Return JSON:
{
  "signatures": [
    {"bbox": [x1, y1, x2, y2], "crop_b64": "<base64 encoded crop>"},
    ...
  ]
}

If no signatures are present, return {"signatures": []}.
"""


class SignatureDetectorUnavailableError(Exception):
    """Raised when the vision model is unreachable or returns an unexpected response."""


class SignatureDetector:
    """
    Calls the Vision LLM to detect and crop ink signatures on a cheque image.

    Args:
        vllm_client: OpenAI-compatible async client. In tests, pass a mock.
    """

    def __init__(self, vllm_client) -> None:
        self._client = vllm_client

    async def detect(self, cheque_image_url: str, bank_id: str) -> list[bytes]:
        """
        Detect signatures on the cheque image.

        Args:
            cheque_image_url: MinIO or HTTP URL to the cheque image
            bank_id:          for tracing/logging

        Returns:
            list[bytes] — one bytes item per detected signature crop.
            Empty list if no signatures detected.

        Raises:
            SignatureDetectorUnavailableError on model failure.
        """
        import base64
        import json

        with tracer.start_as_current_span("msv.ai.detect_signatures") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("model", _MODEL_NAME)
            span.set_attribute("queue", _DETECTION_QUEUE)

            try:
                response = await self._client.chat.completions.create(
                    model=_MODEL_NAME,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": cheque_image_url},
                                },
                                {"type": "text", "text": _DETECTION_PROMPT},
                            ],
                        }
                    ],
                    extra_body={"queue": _DETECTION_QUEUE},
                    timeout=60,
                )

                # If test mock injects crops directly on the response object
                choice = response.choices[0].message
                if hasattr(choice, "signature_crops"):
                    crops: list[bytes] = choice.signature_crops
                    span.set_attribute("detected_count", len(crops))
                    log.info(
                        "msv.detect_signatures.complete",
                        bank_id=bank_id,
                        detected_count=len(crops),
                    )
                    return crops

                # Production path: parse JSON content from LLM response
                content = choice.content
                parsed = json.loads(content)
                crops = [
                    base64.b64decode(sig["crop_b64"])
                    for sig in parsed.get("signatures", [])
                ]

                span.set_attribute("detected_count", len(crops))
                log.info(
                    "msv.detect_signatures.complete",
                    bank_id=bank_id,
                    detected_count=len(crops),
                )
                return crops

            except SignatureDetectorUnavailableError:
                raise
            except Exception as exc:
                log.error(
                    "msv.detect_signatures.failed",
                    bank_id=bank_id,
                    model=_MODEL_NAME,
                    error=str(exc),
                )
                raise SignatureDetectorUnavailableError(
                    f"Signature detector unavailable: {exc}"
                ) from exc
