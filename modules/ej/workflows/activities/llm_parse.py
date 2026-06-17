"""
EJ LLM parse activity: fetches raw log from object store and delegates to llm_parser.
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from modules.ej.parser.llm_parser import EJParseInput, parse_ej_log

log = structlog.get_logger()


class EJLLMParseActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_log_hash: str
    oem_fingerprint: str
    atm_id: str
    bank_id: str
    object_key: str


class EJLLMParseActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                            # "NORMALISED" | "PARSE_FAILED"
    canonical_record: Optional[dict[str, Any]] = None
    canonical_hash: Optional[str] = None
    low_confidence_fields: list[str] = []


async def llm_parse_ej(
    inp: EJLLMParseActivityInput,
    *,
    object_store,
    vllm_client,
    min_confidence: float,
    max_weak_fields: int = 3,
) -> EJLLMParseActivityResult:
    try:
        raw_log = await object_store.get(inp.object_key)
    except Exception as exc:
        log.warning("ej_llm_parse.store_fetch_failed", atm_id=inp.atm_id, error=str(exc))
        return EJLLMParseActivityResult(outcome="PARSE_FAILED")

    parse_input = EJParseInput(
        raw_log=raw_log,
        oem_fingerprint=inp.oem_fingerprint,
        atm_id=inp.atm_id,
        bank_id=inp.bank_id,
        raw_log_hash=inp.raw_log_hash,
    )

    parse_result = await parse_ej_log(
        parse_input,
        vllm_client=vllm_client,
        min_confidence=min_confidence,
        max_weak_fields=max_weak_fields,
    )

    if parse_result.outcome == "PARSED":
        return EJLLMParseActivityResult(
            outcome="NORMALISED",
            canonical_record=parse_result.canonical_record,
            canonical_hash=parse_result.canonical_hash,
            low_confidence_fields=parse_result.low_confidence_fields,
        )

    return EJLLMParseActivityResult(
        outcome="PARSE_FAILED",
        canonical_record=parse_result.canonical_record,
        canonical_hash=parse_result.canonical_hash,
        low_confidence_fields=parse_result.low_confidence_fields,
    )
