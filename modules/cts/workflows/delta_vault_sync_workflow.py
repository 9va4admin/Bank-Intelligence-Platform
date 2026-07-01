"""
Delta Vault Sync Workflow — Gemini Fix B.

Runs every 15 minutes to pull ONLY:
  1. Stop-payment instruction deltas (new STPs filed since last sync)
  2. Canceled cheque leaf serials (cheque books reported lost/stolen)

These are written to the CanceledLeafBloom filter in Redis.
This reduces the fraud window from 18 hours (daily sync) to 15 minutes.

Full signature vault sync still runs at 6AM daily (VaultSyncWorkflow).

Workflow ID pattern: cts-vault-delta-{bank_id}-{yyyymmddhhmm}
Task queue: cts-processing-{bank_id} (same as main CTS queue, low priority)
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DeltaVaultSyncInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    sync_window_minutes: int = 15   # pull deltas for the last N minutes


class DeltaVaultSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    stop_payments_fetched: int
    canceled_leaves_fetched: int
    bloom_serials_added: int
    cbs_degraded: bool = False   # True if CBS was unreachable during sync


# ---------------------------------------------------------------------------
# Activities (called by DeltaVaultSyncWorkflow via Temporal)
# ---------------------------------------------------------------------------

async def fetch_delta_stop_payments(
    bank_id: str,
    window_minutes: int,
    cbs_client: Any,
) -> list[dict]:
    """
    Fetch stop-payment instructions created in the last window_minutes from CBS.
    Returns list of dicts with at minimum: {"account_number": ..., "cheque_serial": ..., "reason": ...}
    Returns empty list on CBS unavailability (graceful degradation — Bloom filter retains previous entries).
    """
    try:
        deltas = await cbs_client.get_stop_payment_deltas(
            bank_id=bank_id,
            window_minutes=window_minutes,
        )
        log.info(
            "delta_sync.stop_payments_fetched",
            bank_id=bank_id,
            count=len(deltas),
            window_minutes=window_minutes,
        )
        return deltas or []
    except Exception as exc:
        log.warning(
            "delta_sync.stop_payments_cbs_degraded",
            bank_id=bank_id,
            error=str(exc),
        )
        return []


async def fetch_delta_canceled_leaves(
    bank_id: str,
    window_minutes: int,
    cbs_client: Any,
) -> list[dict]:
    """
    Fetch canceled cheque leaf serials from the last window_minutes from CBS.
    Returns list of dicts with at minimum: {"serial": ..., "account_number": ...}
    Returns empty list on CBS unavailability.
    """
    try:
        deltas = await cbs_client.get_canceled_cheque_leaves(
            bank_id=bank_id,
            window_minutes=window_minutes,
        )
        log.info(
            "delta_sync.canceled_leaves_fetched",
            bank_id=bank_id,
            count=len(deltas),
            window_minutes=window_minutes,
        )
        return deltas or []
    except Exception as exc:
        log.warning(
            "delta_sync.canceled_leaves_cbs_degraded",
            bank_id=bank_id,
            error=str(exc),
        )
        return []


async def update_bloom_filter(
    bank_id: str,
    stop_payment_deltas: list[dict],
    canceled_leaf_deltas: list[dict],
    bloom_client: Any,
) -> dict:
    """
    Add all new serials to the CanceledLeafBloom filter.
    Returns {"serials_added": int}.
    """
    serials: list[str] = []

    # Extract cheque serial from stop-payment records
    for sp in stop_payment_deltas:
        serial = sp.get("cheque_serial")
        if serial:
            serials.append(str(serial))

    # Extract serial from canceled leaf records
    for cl in canceled_leaf_deltas:
        serial = cl.get("serial")
        if serial:
            serials.append(str(serial))

    if not serials:
        log.info("delta_sync.bloom_no_update_needed", bank_id=bank_id)
        return {"serials_added": 0}

    bloom_client.add_bulk(serials)

    log.info(
        "delta_sync.bloom_updated",
        bank_id=bank_id,
        serials_added=len(serials),
        stop_payments=len(stop_payment_deltas),
        canceled_leaves=len(canceled_leaf_deltas),
    )
    return {"serials_added": len(serials)}
