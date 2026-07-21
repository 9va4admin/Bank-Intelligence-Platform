"""
SMB vault push activities — parse CBS batch file, write to Redis vault.

parse_and_validate_smb_push : normalise CBS push file → canonical records.
update_smb_vault             : write records into Redis (sig/PPS/stop-payment vault).

Both activities degrade gracefully when external deps are unavailable.
Duplicate files (same SHA-256 hash) are detected at parse time via a
UNIQUE constraint on cts.smb_push_sessions and silently skipped.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()


# ── parse_and_validate_smb_push ───────────────────────────────────────────────

class ParseSMBPushInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    smb_id: str
    file_type: str              # "STOP_PAYMENTS" | "PPS_ENTRIES" | "SIGNATURES"
    file_path: str
    file_hash: str              # SHA-256 of raw file content — idempotency key


class ParseSMBPushResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    records: list[dict] = []
    record_count: int = 0
    duplicate: bool = False
    error: Optional[str] = None


@activity.defn
async def parse_and_validate_smb_push(
    inp: ParseSMBPushInput,
    db_pool: Any = None,
) -> ParseSMBPushResult:
    """
    1. Check cts.smb_push_sessions for the file_hash (idempotency).
       If found → duplicate = True, return early.
    2. Parse the CBS batch file into canonical records (via SMBPushParser).
    3. Record the file_hash in cts.smb_push_sessions for future deduplication.

    Degrades gracefully when db_pool is None.
    """
    if db_pool is None:
        log.warning(
            "parse_and_validate_smb_push.db_unavailable",
            agency_id=inp.agency_id,
            smb_id=inp.smb_id,
            file_hash=inp.file_hash,
        )
        return ParseSMBPushResult(error="DB_UNAVAILABLE")

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT file_hash FROM cts.smb_push_sessions WHERE file_hash = $1 AND smb_id = $2",
            inp.file_hash,
            inp.smb_id,
        )
        if existing:
            log.info(
                "parse_and_validate_smb_push.duplicate",
                agency_id=inp.agency_id,
                smb_id=inp.smb_id,
                file_hash=inp.file_hash,
            )
            return ParseSMBPushResult(duplicate=True)

    try:
        import pathlib

        path = pathlib.Path(inp.file_path)
        if not path.exists():
            raise FileNotFoundError(f"SMB push file not found: {inp.file_path}")

        from modules.cts.smb_ingest.parser import SMBPushParser

        parser = SMBPushParser(file_type=inp.file_type, smb_id=inp.smb_id)
        records = parser.parse(path.read_bytes())
    except Exception as exc:
        log.error(
            "parse_and_validate_smb_push.error",
            agency_id=inp.agency_id,
            smb_id=inp.smb_id,
            error=str(exc),
        )
        return ParseSMBPushResult(error=str(exc))

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cts.smb_push_sessions (agency_id, smb_id, file_type, file_hash, record_count)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (file_hash) DO NOTHING
            """,
            inp.agency_id,
            inp.smb_id,
            inp.file_type,
            inp.file_hash,
            len(records),
        )

    log.info(
        "parse_and_validate_smb_push.complete",
        agency_id=inp.agency_id,
        smb_id=inp.smb_id,
        file_type=inp.file_type,
        record_count=len(records),
    )
    return ParseSMBPushResult(records=records, record_count=len(records))


# ── update_smb_vault ──────────────────────────────────────────────────────────

class UpdateSMBVaultInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    smb_id: str
    file_type: str
    records: list[dict]


class UpdateSMBVaultResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    updated_count: int
    error: Optional[str] = None


@activity.defn
async def update_smb_vault(
    inp: UpdateSMBVaultInput,
    redis_client: Any = None,
) -> UpdateSMBVaultResult:
    """
    Writes parsed records into the appropriate Redis vault:
      STOP_PAYMENTS → bloom filter + stop-payment hash set
      PPS_ENTRIES   → pps:{agency_id}:{account_hash}:{series_start}
      SIGNATURES    → sig:{agency_id}:{account_hash}

    Uses Redis pipeline for bulk writes.
    Degrades gracefully when redis_client is None.
    """
    if redis_client is None:
        log.warning(
            "update_smb_vault.redis_unavailable",
            agency_id=inp.agency_id,
            smb_id=inp.smb_id,
            file_type=inp.file_type,
        )
        return UpdateSMBVaultResult(updated_count=0, error="REDIS_UNAVAILABLE")

    async with redis_client.pipeline() as pipe:
        for record in inp.records:
            account_hash = record.get("account_number_hash", "")
            if inp.file_type == "STOP_PAYMENTS":
                key = f"stop:{inp.agency_id}:{account_hash}:{record.get('cheque_number', '')}"
                pipe.set(key, "1")
            elif inp.file_type == "PPS_ENTRIES":
                key = f"pps:{inp.agency_id}:{account_hash}"
                pipe.set(key, str(record))
            elif inp.file_type == "SIGNATURES":
                key = f"sig:{inp.agency_id}:{account_hash}"
                pipe.set(key, str(record))
        await pipe.execute()

    log.info(
        "update_smb_vault.complete",
        agency_id=inp.agency_id,
        smb_id=inp.smb_id,
        file_type=inp.file_type,
        updated_count=len(inp.records),
    )
    return UpdateSMBVaultResult(updated_count=len(inp.records))
