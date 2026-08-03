"""
store_canonical activity — persist normalised EJ record to YugabyteDB.

Stores the canonical record produced by llm_parse after schema validation passes.
Idempotent: ON CONFLICT (canonical_hash) DO NOTHING — safe for Temporal retries.

Caller injects db_pool (asyncpg Pool) for production. Test callers omit it to
exercise the activity without a live database.
"""
import json
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_INSERT_SQL = """
INSERT INTO ej.canonical_records (
    canonical_hash,
    atm_id,
    bank_id,
    record_json,
    stored_at
)
VALUES ($1, $2, $3, $4, NOW())
ON CONFLICT (canonical_hash) DO NOTHING
"""


class EJStoreCanonicalResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str          # "STORED" | "DUPLICATE"
    canonical_hash: str
    bank_id: str


async def store_canonical(
    canonical_record: dict,
    canonical_hash: str,
    atm_id: str,
    bank_id: str,
    db_pool=None,
) -> EJStoreCanonicalResult:
    """
    Persist canonical EJ record to YugabyteDB ej schema.

    Idempotent: if canonical_hash already exists, returns DUPLICATE without error.
    Production callers must inject db_pool (asyncpg Pool via pgbouncer-ej).
    """
    log.info(
        "ej.store_canonical.start",
        atm_id=atm_id,
        bank_id=bank_id,
        canonical_hash=canonical_hash[:12],
    )

    if db_pool is None:
        # Test path — no DB available; treat as stored for workflow continuity.
        log.warning(
            "ej.store_canonical.no_db_pool",
            atm_id=atm_id,
            bank_id=bank_id,
        )
        return EJStoreCanonicalResult(
            outcome="STORED",
            canonical_hash=canonical_hash,
            bank_id=bank_id,
        )

    record_json = json.dumps(canonical_record, ensure_ascii=False)

    async with db_pool.acquire() as conn:
        result = await conn.execute(
            _INSERT_SQL,
            canonical_hash,
            atm_id,
            bank_id,
            record_json,
        )

    # asyncpg returns "INSERT 0 N" — 0 rows affected means ON CONFLICT fired
    inserted = result.endswith("1")
    outcome = "STORED" if inserted else "DUPLICATE"

    log.info(
        "ej.store_canonical.complete",
        atm_id=atm_id,
        bank_id=bank_id,
        canonical_hash=canonical_hash[:12],
        outcome=outcome,
    )

    return EJStoreCanonicalResult(
        outcome=outcome,
        canonical_hash=canonical_hash,
        bank_id=bank_id,
    )
