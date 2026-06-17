"""
EJNormalisationWorkflow: ingest → fingerprint → llm_parse → validate → store.

Workflow ID: ej-normalise-{bank_id}-{raw_log_hash} (idempotent).
Terminal states: NORMALISED | PARSE_FAILED | VALIDATION_FAILED
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class EJNormalisationInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_log: str
    raw_log_hash: str
    atm_id: str
    bank_id: str
    oem_fingerprint: str
    source: str


class EJNormalisationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "NORMALISED" | "PARSE_FAILED" | "VALIDATION_FAILED"
    bank_id: str
    atm_id: str
    oem_fingerprint: str
    canonical_hash: Optional[str] = None
    canonical_record: Optional[dict[str, Any]] = None


class EJNormalisationWorkflow:
    def workflow_id(self, bank_id: str, raw_log_hash: str) -> str:
        return f"ej-normalise-{bank_id}-{raw_log_hash}"

    async def run_with_mocks(
        self,
        inp: EJNormalisationInput,
        mock_results: dict,
    ) -> EJNormalisationResult:
        # Step 1: Ingest — store raw log to MinIO
        ingest_result = mock_results["ingest"]

        # Step 2: Validate OEM fingerprint
        fingerprint_result = mock_results["fingerprint"]

        # Step 3: LLM parse
        parse_result = mock_results["llm_parse"]

        if parse_result.outcome != "NORMALISED":
            log.warning(
                "ej_normalise.parse_failed",
                atm_id=inp.atm_id,
                bank_id=inp.bank_id,
            )
            return EJNormalisationResult(
                outcome="PARSE_FAILED",
                bank_id=inp.bank_id,
                atm_id=inp.atm_id,
                oem_fingerprint=fingerprint_result.oem_fingerprint,
                canonical_hash=parse_result.canonical_hash,
            )

        # Step 4: Validate schema
        validate_result = mock_results["validate"]

        if validate_result.outcome != "VALID":
            return EJNormalisationResult(
                outcome="VALIDATION_FAILED",
                bank_id=inp.bank_id,
                atm_id=inp.atm_id,
                oem_fingerprint=fingerprint_result.oem_fingerprint,
                canonical_hash=parse_result.canonical_hash,
            )

        log.info(
            "ej_normalise.complete",
            atm_id=inp.atm_id,
            bank_id=inp.bank_id,
            canonical_hash=parse_result.canonical_hash,
        )

        return EJNormalisationResult(
            outcome="NORMALISED",
            bank_id=inp.bank_id,
            atm_id=inp.atm_id,
            oem_fingerprint=fingerprint_result.oem_fingerprint,
            canonical_hash=parse_result.canonical_hash,
            canonical_record=parse_result.canonical_record,
        )
