"""
EJ LLM parser: Llama 3.3 70B (ej-reasoning queue) converts OEM-specific raw EJ
text into canonical EJ schema records.

Rules:
- OEM fingerprint must be included in every prompt
- Low confidence fields → None value + warning flag
- Confidence thresholds from parameters, never hardcoded
- Every result has canonical_hash (SHA-256 of normalised content)
- Never cached (each log is unique)
"""
import hashlib
import json
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_CANONICAL_SCHEMA = {
    "transaction_type": "string",
    "amount": "float",
    "status": "string",
    "timestamp": "ISO-8601 string",
    "error_code": "string or null",
}


class EJParseInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_log: str
    oem_fingerprint: str
    atm_id: str
    bank_id: str
    raw_log_hash: str


class EJParseResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                          # "PARSED" | "PARSE_FAILED"
    canonical_record: dict[str, Any]
    canonical_hash: str
    low_confidence_fields: list[str]


def _build_prompt(inp: EJParseInput) -> str:
    schema_json = json.dumps(_CANONICAL_SCHEMA, indent=2)
    return (
        f"OEM: {inp.oem_fingerprint}\n"
        f"ATM: {inp.atm_id}\n\n"
        f"Raw EJ log:\n{inp.raw_log}\n\n"
        f"Extract fields per this canonical schema:\n{schema_json}\n\n"
        "Return JSON with each field as {\"value\": ..., \"confidence\": 0.0-1.0}. "
        "If uncertain set confidence below 0.70."
    )


def _compute_hash(record: dict) -> str:
    content = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()


async def parse_ej_log(
    inp: EJParseInput,
    *,
    vllm_client,
    min_confidence: float,
    max_weak_fields: int = 3,
) -> EJParseResult:
    prompt = _build_prompt(inp)

    try:
        raw = await vllm_client.parse(prompt)
    except Exception as exc:
        log.warning("ej_parser.vllm_unavailable", atm_id=inp.atm_id, error=str(exc))
        return EJParseResult(
            outcome="PARSE_FAILED",
            canonical_record={},
            canonical_hash=_compute_hash({}),
            low_confidence_fields=[],
        )

    canonical: dict[str, Any] = {}
    low_confidence: list[str] = []

    for field, extraction in raw.items():
        confidence = extraction.get("confidence", 0.0)
        if confidence < min_confidence:
            canonical[field] = None
            low_confidence.append(field)
        else:
            canonical[field] = extraction.get("value")

    if len(low_confidence) > max_weak_fields:
        return EJParseResult(
            outcome="PARSE_FAILED",
            canonical_record=canonical,
            canonical_hash=_compute_hash(canonical),
            low_confidence_fields=low_confidence,
        )

    return EJParseResult(
        outcome="PARSED",
        canonical_record=canonical,
        canonical_hash=_compute_hash(canonical),
        low_confidence_fields=low_confidence,
    )
