"""open_review_item — put a held instrument into the durable human-review queue.

Never raises: a queue-write failure must degrade (log + False), never break clearing.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.review_queue import open_item

log = structlog.get_logger()


class OpenReviewItemInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    direction: str                       # INWARD | OUTWARD
    instrument_id: str
    workflow_id: str
    parent_workflow_id: str
    escalation_reason: str
    context: dict = {}
    review_window_minutes: int = 240     # outward holds have no IET; reviewer SLA window
    queue_tier: str = "standard"


@activity.defn
async def open_review_item(inp: OpenReviewItemInput, db_pool: Optional[Any] = None) -> bool:
    if db_pool is None:
        log.warning("open_review_item.no_pool", bank_id=inp.bank_id, instrument_id=inp.instrument_id)
        return False
    try:
        async with db_pool.acquire() as conn:
            await open_item(
                conn, bank_id=inp.bank_id, direction=inp.direction, instrument_id=inp.instrument_id,
                workflow_id=inp.workflow_id, parent_workflow_id=inp.parent_workflow_id,
                escalation_reason=inp.escalation_reason, context_bundle=inp.context,
                review_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=inp.review_window_minutes),
                queue_tier=inp.queue_tier,
            )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("open_review_item.failed", bank_id=inp.bank_id, instrument_id=inp.instrument_id, error=str(exc))
        return False
