"""Inward API: drawee name (from CBS, stored plain by bank-owner decision) attached to queue / decision rows."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.routers.cts_inward import QueueItem, DecisionLogItem, _fetch_drawee_names
from shared.utils.instrument_uuid import to_instrument_uuid


def _pool(rows):
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)
    return pool, conn


@pytest.mark.asyncio
async def test_maps_names_back_to_instrument_ids():
    u1 = to_instrument_uuid("kbl", "IW-1")
    pool, conn = _pool([{"instrument_id": u1, "drawee_name": "JAGADISH.V"}])
    out = await _fetch_drawee_names(pool, "kbl", ["IW-1", "IW-2"])
    assert out == {"IW-1": "JAGADISH.V"}
    assert conn.fetch.await_args.args[1] == "kbl"          # always bank-scoped


@pytest.mark.asyncio
async def test_no_pool_or_no_ids_returns_empty_without_querying():
    assert await _fetch_drawee_names(None, "kbl", ["IW-1"]) == {}
    pool, conn = _pool([])
    assert await _fetch_drawee_names(pool, "kbl", []) == {}
    conn.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_db_error_degrades_to_empty():
    pool, conn = _pool([])
    conn.fetch = AsyncMock(side_effect=RuntimeError("db down"))
    assert await _fetch_drawee_names(pool, "kbl", ["IW-1"]) == {}


def test_response_models_carry_optional_drawee_name():
    assert QueueItem.model_fields["drawee_name"].default is None
    assert DecisionLogItem.model_fields["drawee_name"].default is None
