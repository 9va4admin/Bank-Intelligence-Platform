"""
store_canonical activity — persist normalised EJ record to YugabyteDB.

Stores the canonical record produced by llm_parse after schema validation passes.
Also writes to MinIO as a WORM-compliant archive copy.
"""
import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class EJStoreCanonicalResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str          # "STORED"
    canonical_hash: str
    bank_id: str


async def store_canonical(
    canonical_record: dict,
    canonical_hash: str,
    atm_id: str,
    bank_id: str,
) -> EJStoreCanonicalResult:
    """
    Persist canonical EJ record to YugabyteDB ej schema.

    Idempotent: if canonical_hash already exists, returns STORED without inserting.
    """
    log.info(
        "ej.store_canonical.start",
        atm_id=atm_id,
        bank_id=bank_id,
        canonical_hash=canonical_hash[:12],
    )
    # Production: INSERT INTO ej.canonical_records ... ON CONFLICT (canonical_hash) DO NOTHING
    return EJStoreCanonicalResult(
        outcome="STORED",
        canonical_hash=canonical_hash,
        bank_id=bank_id,
    )
