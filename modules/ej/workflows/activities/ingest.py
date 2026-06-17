"""
EJ ingestion activity: validates raw log, computes SHA-256 hash, stores to MinIO.

Raw EJ files are immutable once ingested — this activity is idempotent.
"""
import hashlib
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class EJIngestInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_log: str
    atm_id: str
    bank_id: str
    source: str


class EJIngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                    # "ACCEPTED" | "ALREADY_INGESTED" | "INGEST_FAILED"
    raw_log_hash: str
    object_key: Optional[str] = None
    bank_id: str


async def ingest_ej_log(inp: EJIngestInput, *, object_store) -> EJIngestResult:
    raw_log_hash = hashlib.sha256(inp.raw_log.encode()).hexdigest()
    object_key = f"ej/{inp.bank_id}/{inp.atm_id}/{raw_log_hash}.log"

    try:
        response = await object_store.put(
            key=object_key,
            content=inp.raw_log,
            bank_id=inp.bank_id,
        )
        return EJIngestResult(
            outcome="ACCEPTED",
            raw_log_hash=raw_log_hash,
            object_key=response.get("object_key", object_key),
            bank_id=inp.bank_id,
        )
    except Exception as exc:
        exc_str = str(exc)
        if "AlreadyExists" in exc_str or "already" in exc_str.lower():
            log.info("ej_ingest.duplicate", atm_id=inp.atm_id, hash=raw_log_hash)
            return EJIngestResult(
                outcome="ALREADY_INGESTED",
                raw_log_hash=raw_log_hash,
                object_key=object_key,
                bank_id=inp.bank_id,
            )
        log.warning("ej_ingest.store_failed", atm_id=inp.atm_id, error=str(exc))
        return EJIngestResult(
            outcome="INGEST_FAILED",
            raw_log_hash=raw_log_hash,
            bank_id=inp.bank_id,
        )
