"""
Batch endorsement activities — stamp and lot-status update.

DI note: stamp_endorsement receives a `lot_store` (duck-typed: has
`fetch_instrument_images(lot_number, bank_id)`) injected at worker
startup via BoundCTSActivities, same pattern as cbs_balance / ngch_filer.
When the real lot_store is unavailable (dev / test), the activity degrades
gracefully (ENDORSEMENT_FAILED outcome) rather than crashing the workflow.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# stamp_endorsement
# ---------------------------------------------------------------------------

class StampEndorsementInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str
    bank_id: str
    bank_ifsc: str
    instrument_ids: list[str]


class StampEndorsementResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    endorsed_count: int
    failed_count: int
    failed_instrument_ids: list[str]


@activity.defn
async def stamp_endorsement(
    inp: StampEndorsementInput,
    lot_store: Any = None,
) -> StampEndorsementResult:
    """
    Stamps the reverse of every instrument in the lot with the bank's
    endorsement template (IFSC, routing, date).

    lot_store is DI-injected at worker startup (reads images from MinIO
    via the lot management module). Falls back gracefully when unavailable.
    """
    if lot_store is None:
        log.warning(
            "stamp_endorsement.lot_store_unavailable",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
        )
        return StampEndorsementResult(
            endorsed_count=0,
            failed_count=len(inp.instrument_ids),
            failed_instrument_ids=list(inp.instrument_ids),
        )

    from modules.cts.endorsement.batch import BatchEndorsementProcessor
    from modules.cts.endorsement.models import EndorsementTemplate

    template = EndorsementTemplate(
        bank_ifsc=inp.bank_ifsc,
        presenter_name=f"ASTRA-{inp.bank_id}",
        stamp_date=datetime.utcnow(),
    )
    processor = BatchEndorsementProcessor(template=template)

    failed: list[str] = []
    endorsed: list[str] = []

    items = await lot_store.fetch_instrument_images(inp.lot_number, inp.bank_id)
    for instrument_id, account_suffix, front_bytes, rear_bytes in items:
        try:
            processor.process([(instrument_id, account_suffix, front_bytes, rear_bytes)])
            endorsed.append(instrument_id)
            log.debug(
                "stamp_endorsement.stamped",
                instrument_id=instrument_id,
                lot_number=inp.lot_number,
            )
        except Exception as exc:
            failed.append(instrument_id)
            log.warning(
                "stamp_endorsement.failed",
                instrument_id=instrument_id,
                lot_number=inp.lot_number,
                error=str(exc),
            )

    return StampEndorsementResult(
        endorsed_count=len(endorsed),
        failed_count=len(failed),
        failed_instrument_ids=failed,
    )


# ---------------------------------------------------------------------------
# update_lot_status
# ---------------------------------------------------------------------------

class UpdateLotStatusInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str
    bank_id: str
    outcome: str         # "ENDORSED" | "ENDORSEMENT_FAILED"
    endorsed_count: int
    failed_count: int


class UpdateLotStatusResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    updated: bool
    outcome: str


@activity.defn
async def update_lot_status(
    inp: UpdateLotStatusInput,
    db_pool: Any = None,
) -> UpdateLotStatusResult:
    """
    Updates the lot record in YugabyteDB to ENDORSED or ENDORSEMENT_FAILED.
    db_pool is injected at worker startup. Degrades gracefully when unavailable.
    """
    if db_pool is None:
        log.warning(
            "update_lot_status.db_unavailable",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
        )
        return UpdateLotStatusResult(updated=False, outcome=inp.outcome)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cts.lots
               SET status = $1,
                   endorsed_count = $2,
                   endorsement_failed_count = $3,
                   endorsed_at = NOW()
             WHERE lot_number = $4 AND bank_id = $5
            """,
            inp.outcome,
            inp.endorsed_count,
            inp.failed_count,
            inp.lot_number,
            inp.bank_id,
        )
    log.info(
        "update_lot_status.updated",
        lot_number=inp.lot_number,
        bank_id=inp.bank_id,
        outcome=inp.outcome,
    )
    return UpdateLotStatusResult(updated=True, outcome=inp.outcome)
