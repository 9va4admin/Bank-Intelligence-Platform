"""
EJNormalisationWorkflow: ingest → fingerprint → llm_parse → validate → store.

Workflow ID: ej-normalise-{bank_id}-{raw_log_hash} (idempotent).
Terminal states: NORMALISED | PARSE_FAILED | VALIDATION_FAILED

Activity sequence (per CLAUDE.md spec):
  1. ingest           — store raw log to MinIO
  2. fingerprint      — validate OEM fingerprint
  3. llm_parse        — Llama 3.3 70B normalises to canonical schema
  4. validate         — validate schema conformance
  5. store_canonical  — persist to YugabyteDB (happy path only)
  6. trigger_dispute_check — publish to ej.canonical topic (happy path only)
  7. update_atm_health     — emit ATM health signal (happy path only)
  8. write_audit      — immutable audit write (ALL outcomes)
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
    outcome: str                           # "NORMALISED" | "PARSE_FAILED" | "VALIDATION_FAILED"
    bank_id: str
    atm_id: str
    oem_fingerprint: str
    canonical_hash: Optional[str] = None
    canonical_record: Optional[dict[str, Any]] = None
    dispute_check_triggered: bool = False
    atm_health_updated: bool = False
    audit_written: bool = False


class EJNormalisationWorkflow:
    def workflow_id(self, bank_id: str, raw_log_hash: str) -> str:
        return f"ej-normalise-{bank_id}-{raw_log_hash}"

    async def run_with_mocks(
        self,
        inp: EJNormalisationInput,
        mock_results: dict,
    ) -> EJNormalisationResult:
        # Step 1: Ingest — store raw log to MinIO
        ingest_result = mock_results["ingest"]  # noqa: F841 — used by production Temporal call

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
            # Step 8: Audit — write for ALL outcomes
            await self._write_audit(
                mock_results, "PARSE_FAILED", inp.raw_log_hash,
                parse_result.canonical_hash, inp.atm_id, inp.bank_id,
            )
            return EJNormalisationResult(
                outcome="PARSE_FAILED",
                bank_id=inp.bank_id,
                atm_id=inp.atm_id,
                oem_fingerprint=fingerprint_result.oem_fingerprint,
                canonical_hash=parse_result.canonical_hash,
                audit_written=True,
            )

        # Step 4: Validate schema
        validate_result = mock_results["validate"]

        if validate_result.outcome != "VALID":
            await self._write_audit(
                mock_results, "VALIDATION_FAILED", inp.raw_log_hash,
                parse_result.canonical_hash, inp.atm_id, inp.bank_id,
            )
            return EJNormalisationResult(
                outcome="VALIDATION_FAILED",
                bank_id=inp.bank_id,
                atm_id=inp.atm_id,
                oem_fingerprint=fingerprint_result.oem_fingerprint,
                canonical_hash=parse_result.canonical_hash,
                audit_written=True,
            )

        # Step 5: Store canonical record
        mock_results["store_canonical"]  # noqa: B018 — simulates activity execution

        # Step 5b: Verify canonical integrity (Gemini Fix D)
        # Re-reads the stored record from YugabyteDB to confirm the canonical_hash →
        # raw_log_hash linkage is intact. Orphaned records or hash mismatches terminate here.
        integrity_result = mock_results["verify_canonical_integrity"]
        if integrity_result.outcome != "INTEGRITY_OK":
            log.error(
                "ej_normalise.integrity_failed",
                atm_id=inp.atm_id,
                bank_id=inp.bank_id,
                canonical_hash=parse_result.canonical_hash,
                failure_reason=getattr(integrity_result, "failure_reason", "UNKNOWN"),
            )
            await self._write_audit(
                mock_results, "INTEGRITY_FAILED", inp.raw_log_hash,
                parse_result.canonical_hash, inp.atm_id, inp.bank_id,
            )
            return EJNormalisationResult(
                outcome="INTEGRITY_FAILED",
                bank_id=inp.bank_id,
                atm_id=inp.atm_id,
                oem_fingerprint=fingerprint_result.oem_fingerprint,
                canonical_hash=parse_result.canonical_hash,
                dispute_check_triggered=False,
                atm_health_updated=False,
                audit_written=True,
            )

        # Step 6: Trigger dispute check
        mock_results["trigger_dispute_check"]  # noqa: B018

        # Step 7: Update ATM health
        mock_results["update_atm_health"]  # noqa: B018

        # Step 8: Write audit
        await self._write_audit(
            mock_results, "NORMALISED", inp.raw_log_hash,
            parse_result.canonical_hash, inp.atm_id, inp.bank_id,
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
            dispute_check_triggered=True,
            atm_health_updated=True,
            audit_written=True,
        )

    async def _write_audit(
        self,
        mock_results: dict,
        outcome: str,
        raw_log_hash: str,
        canonical_hash: Optional[str],
        atm_id: str,
        bank_id: str,
    ) -> None:
        mock_results["write_audit"]  # noqa: B018 — simulates activity execution
