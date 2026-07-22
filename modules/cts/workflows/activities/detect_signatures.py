"""
detect_signatures activity — Vision LLM detects ink signatures on a cheque image.

Used by both CTS pipelines with different downstream behaviour:

  Outward (presentee bank):
    PRESENT  → proceed to lot  (no vault lookup, no comparison)
    ABSENT   → CTS-2010 reject / SIGNATURE_ABSENT
    DEGRADED → proceed optimistically (don't block lot on AI failure)

  Inward (drawee bank):
    PRESENT, sig_count=1    → S-SVS (SignatureVault + Siamese compare)
    PRESENT, sig_count≥2   → M-SVS (per-signatory vault + mandate BRE)
    ABSENT                  → HUMAN_REVIEW / NO_SIGNATURE
    DEGRADED                → HUMAN_REVIEW (consistent with all AI degradation paths)
    fraud_flags non-empty   → HUMAN_REVIEW / SIGNATURE_FRAUD_SUSPECTED

Uses Qwen2-VL 7B on cts-vision-l1 queue (fast L1 — detection only;
72B forensic model reserved for full alteration analysis in alteration.py).

The activity is self-contained within modules/cts/ — no import from modules/msv/.
"""
from __future__ import annotations

import json
from typing import Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.detect_signatures")

_MODEL_NAME = "qwen2-vl-7b"
_QUEUE = "cts-vision-l1"
_TIMEOUT_SECONDS = 60

_DETECTION_PROMPT = """Examine this cheque image and locate all handwritten ink signatures.

Return JSON with exactly these fields:
{
  "signature_count": <integer — total distinct ink signatures found>,
  "signature_bboxes": [[x1, y1, x2, y2], ...],
  "signature_fraud_flags": [<string>, ...]
}

Rules:
- signature_count: count only genuine ink handwritten signatures, not printed text or stamps.
- signature_bboxes: one [x1, y1, x2, y2] per signature as decimal fractions of image size
  (0.0 = left/top, 1.0 = right/bottom). Empty array if count is 0.
- signature_fraud_flags: include any that apply —
    "OVERWRITTEN"   — ink written on top of existing ink or whiteout
    "SMUDGED"       — ink blur suggesting wet-ink tampering
    "MULTIPLE_INKS" — different ink colours across signature zones
    "FAINT_INK"     — stroke too light to be genuine (photocopied or printed)
    "MISALIGNED"    — signature placed outside the designated signature box
  Return [] if none detected.

Return ONLY valid JSON. No markdown, no explanation.
"""


class DetectSignaturesInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    image_url: str


class DetectSignaturesResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "PRESENT" | "ABSENT" | "DEGRADED"
    sig_count: int
    sig_bboxes: list[list[float]]       # fractional [x1,y1,x2,y2] per detected signature
    fraud_flags: list[str]
    degraded: bool = False


@activity.defn
async def detect_signatures(
    inp: DetectSignaturesInput,
    vllm_client=None,
) -> DetectSignaturesResult:
    """
    Detect the number and fraud indicators of ink signatures on a cheque image.

    Returns DetectSignaturesResult in all cases — never raises.
    Callers own the routing decision based on outcome and sig_count.
    """
    with tracer.start_as_current_span("cts.detect_signatures") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        span.set_attribute("model", _MODEL_NAME)
        span.set_attribute("queue", _QUEUE)

        if vllm_client is None:
            log.warning(
                "detect_signatures.no_client",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            )
            span.set_attribute("degraded", True)
            return DetectSignaturesResult(
                outcome="DEGRADED", sig_count=0, sig_bboxes=[], fraud_flags=[], degraded=True
            )

        try:
            response = await vllm_client.chat.completions.create(
                model=_MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": inp.image_url}},
                        {"type": "text", "text": _DETECTION_PROMPT},
                    ],
                }],
                extra_body={"queue": _QUEUE},
                timeout=_TIMEOUT_SECONDS,
            )

            raw = response.choices[0].message.content
            parsed = json.loads(raw)

        except json.JSONDecodeError as exc:
            log.warning(
                "detect_signatures.invalid_json",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            span.set_attribute("degraded", True)
            return DetectSignaturesResult(
                outcome="DEGRADED", sig_count=0, sig_bboxes=[], fraud_flags=[], degraded=True
            )
        except Exception as exc:
            log.warning(
                "detect_signatures.vllm_unavailable",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            span.set_attribute("degraded", True)
            return DetectSignaturesResult(
                outcome="DEGRADED", sig_count=0, sig_bboxes=[], fraud_flags=[], degraded=True
            )

        sig_count = int(parsed.get("signature_count", 0))
        fraud_flags = list(parsed.get("signature_fraud_flags", []))
        # Validate and normalise bboxes — LLM occasionally returns malformed entries
        sig_bboxes = [
            [float(v) for v in bbox]
            for bbox in (parsed.get("signature_bboxes") or [])
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4
        ]
        outcome = "PRESENT" if sig_count > 0 else "ABSENT"

        span.set_attribute("sig_count", sig_count)
        span.set_attribute("bbox_count", len(sig_bboxes))
        span.set_attribute("fraud_flag_count", len(fraud_flags))

        log.info(
            "detect_signatures.complete",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            sig_count=sig_count,
            bbox_count=len(sig_bboxes),
            outcome=outcome,
            fraud_flags=fraud_flags,
        )

        return DetectSignaturesResult(
            outcome=outcome,
            sig_count=sig_count,
            sig_bboxes=sig_bboxes,
            fraud_flags=fraud_flags,
            degraded=False,
        )
