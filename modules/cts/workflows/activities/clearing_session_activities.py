"""
Clearing session activities — seal lots, update session status.

seal_all_lots   : queries YugabyteDB for all SEALED lots in the session.
update_session_status: marks the clearing session SUBMITTED/EXCEPTION in DB.

Both activities degrade gracefully when db_pool is unavailable (dev / test).
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()


# ── seal_all_lots ─────────────────────────────────────────────────────────────

class SealAllLotsInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    bank_id: str
    pu_ids: list[str]
    clearing_date: str          # YYYY-MM-DD


class SealAllLotsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    sealed_lots: list[dict]     # [{pu_id, lot_number, instrument_count}, ...]
    status: str                 # "OK" | "DEGRADED"


@activity.defn
async def seal_all_lots(
    inp: SealAllLotsInput,
    db_pool: Any = None,
) -> SealAllLotsResult:
    """
    Fetch all lots with status = 'SEALED' for the given session from YugabyteDB.
    Returns the lot metadata list.  Degrades gracefully when db_pool is None.
    """
    if db_pool is None:
        log.warning(
            "seal_all_lots.db_unavailable",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
        )
        return SealAllLotsResult(sealed_lots=[], status="DEGRADED")

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pu_id, lot_number, instrument_count
              FROM cts.lots
             WHERE session_id = $1
               AND bank_id    = $2
               AND status     = 'SEALED'
            """,
            inp.session_id,
            inp.bank_id,
        )

    sealed = [dict(r) for r in rows]
    log.info(
        "seal_all_lots.complete",
        session_id=inp.session_id,
        bank_id=inp.bank_id,
        lot_count=len(sealed),
    )
    return SealAllLotsResult(sealed_lots=sealed, status="OK")


# ── update_session_status ─────────────────────────────────────────────────────

class UpdateSessionStatusInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    bank_id: str
    status: str                 # "SUBMITTED" | "SUBMITTED_TO_SB" | "EXCEPTION" | "EMPTY_SESSION"
    ngch_reference: Optional[str] = None
    failure_reason: Optional[str] = None


class UpdateSessionStatusResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    updated: bool
    status: str


@activity.defn
async def update_session_status(
    inp: UpdateSessionStatusInput,
    db_pool: Any = None,
) -> UpdateSessionStatusResult:
    """
    Mark the clearing session record in YugabyteDB with its terminal status.
    Degrades gracefully when db_pool is None.
    """
    if db_pool is None:
        log.warning(
            "update_session_status.db_unavailable",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
        )
        return UpdateSessionStatusResult(updated=False, status=inp.status)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cts.clearing_sessions
               SET status          = $1,
                   ngch_reference  = $2,
                   failure_reason  = $3,
                   closed_at       = NOW()
             WHERE session_id = $4 AND bank_id = $5
            """,
            inp.status,
            inp.ngch_reference,
            inp.failure_reason,
            inp.session_id,
            inp.bank_id,
        )

    log.info(
        "update_session_status.updated",
        session_id=inp.session_id,
        bank_id=inp.bank_id,
        status=inp.status,
    )
    return UpdateSessionStatusResult(updated=True, status=inp.status)
