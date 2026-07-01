"""
verify_canonical_integrity activity — Gemini Fix D.

After store_canonical writes to YugabyteDB, this activity re-reads the record
and verifies the canonical_hash → raw_log_hash linkage is intact.

Detects:
  - Orphaned canonical records (store reported success but row missing from DB)
  - Hash mismatch (canonical_hash in DB links to wrong raw_log_hash)
  - Bank isolation violations (record exists but belongs to different bank_id)
  - DB unavailability (YugabyteDB timeout during partition rebalance)

Called between store_canonical (step 5) and trigger_dispute_check (step 6)
in EJNormalisationWorkflow.

Outcomes:
  INTEGRITY_OK      → proceed to trigger_dispute_check
  INTEGRITY_FAILED  → write audit with reason, terminate workflow with INTEGRITY_FAILED
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EJIntegrityCheckInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    canonical_hash: str
    raw_log_hash: str
    atm_id: str
    bank_id: str


class EJIntegrityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "INTEGRITY_OK" | "INTEGRITY_FAILED"
    canonical_hash: str
    raw_log_hash: str
    bank_id: str
    failure_reason: Optional[str] = None  # "CANONICAL_RECORD_NOT_FOUND" | "RAW_LOG_HASH_MISMATCH"
                                          # | "BANK_ID_MISMATCH" | "DB_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class EJIntegrityError(Exception):
    """Raised by EJNormalisationWorkflow when verify_canonical_integrity returns FAILED."""

    def __init__(self, canonical_hash: str, failure_reason: str, bank_id: str) -> None:
        self.canonical_hash = canonical_hash
        self.failure_reason = failure_reason
        self.bank_id = bank_id
        super().__init__(
            f"EJ canonical integrity check failed: {failure_reason} "
            f"(canonical_hash={canonical_hash}, bank_id={bank_id})"
        )


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

async def verify_canonical_integrity(
    inp: EJIntegrityCheckInput,
    db_client: Any,
) -> EJIntegrityResult:
    """
    Verify that the canonical record just written to YugabyteDB is intact.

    Queries ej.canonical_records by canonical_hash AND bank_id (multi-tenancy safe).
    Checks that raw_log_hash in the returned row matches the expected raw_log_hash.

    Returns EJIntegrityResult — never raises (Temporal retries handle transient DB failures
    via the configured retry policy; persistent failures surface as INTEGRITY_FAILED).
    """
    log.info(
        "ej.verify_integrity.start",
        canonical_hash=inp.canonical_hash[:12],
        bank_id=inp.bank_id,
        atm_id=inp.atm_id,
    )

    try:
        row = await db_client.fetch_canonical_record(
            canonical_hash=inp.canonical_hash,
            bank_id=inp.bank_id,
        )
    except Exception as exc:
        log.error(
            "ej.verify_integrity.db_unavailable",
            canonical_hash=inp.canonical_hash[:12],
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return EJIntegrityResult(
            outcome="INTEGRITY_FAILED",
            canonical_hash=inp.canonical_hash,
            raw_log_hash=inp.raw_log_hash,
            bank_id=inp.bank_id,
            failure_reason="DB_UNAVAILABLE",
        )

    if row is None:
        log.error(
            "ej.verify_integrity.orphaned_record",
            canonical_hash=inp.canonical_hash[:12],
            bank_id=inp.bank_id,
        )
        return EJIntegrityResult(
            outcome="INTEGRITY_FAILED",
            canonical_hash=inp.canonical_hash,
            raw_log_hash=inp.raw_log_hash,
            bank_id=inp.bank_id,
            failure_reason="CANONICAL_RECORD_NOT_FOUND",
        )

    # Validate bank isolation
    stored_bank_id = row.get("bank_id", "")
    if stored_bank_id != inp.bank_id:
        log.error(
            "ej.verify_integrity.bank_id_mismatch",
            expected_bank_id=inp.bank_id,
            stored_bank_id=stored_bank_id,
            canonical_hash=inp.canonical_hash[:12],
        )
        return EJIntegrityResult(
            outcome="INTEGRITY_FAILED",
            canonical_hash=inp.canonical_hash,
            raw_log_hash=inp.raw_log_hash,
            bank_id=inp.bank_id,
            failure_reason="BANK_ID_MISMATCH",
        )

    # Validate raw_log_hash linkage
    stored_raw_log_hash = row.get("raw_log_hash", "")
    if stored_raw_log_hash != inp.raw_log_hash:
        log.error(
            "ej.verify_integrity.hash_mismatch",
            expected_raw_log_hash=inp.raw_log_hash[:12],
            stored_raw_log_hash=stored_raw_log_hash[:12] if stored_raw_log_hash else "EMPTY",
            canonical_hash=inp.canonical_hash[:12],
            bank_id=inp.bank_id,
        )
        return EJIntegrityResult(
            outcome="INTEGRITY_FAILED",
            canonical_hash=inp.canonical_hash,
            raw_log_hash=inp.raw_log_hash,
            bank_id=inp.bank_id,
            failure_reason="RAW_LOG_HASH_MISMATCH",
        )

    log.info(
        "ej.verify_integrity.ok",
        canonical_hash=inp.canonical_hash[:12],
        bank_id=inp.bank_id,
    )
    return EJIntegrityResult(
        outcome="INTEGRITY_OK",
        canonical_hash=inp.canonical_hash,
        raw_log_hash=inp.raw_log_hash,
        bank_id=inp.bank_id,
    )
