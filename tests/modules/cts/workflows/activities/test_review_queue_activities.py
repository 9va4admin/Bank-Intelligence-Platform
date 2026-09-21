"""open_review_item: outward payee holds (frozen / name mismatch) returned MISMATCH_HELD but created no
queue item anywhere, so no reviewer could ever see them. The activity never raises (a review-queue
write failure must not break clearing)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.cts.workflows.activities.review_queue_activities import OpenReviewItemInput, open_review_item


def _inp(**kw):
    base = dict(bank_id="kbl", direction="OUTWARD", instrument_id="000787-c687", workflow_id="cts-outscan-kbl-1",
                parent_workflow_id="cts-outscan-kbl-1", escalation_reason="PAYEE_ACCOUNT_FROZEN",
                context={"account_status": "FROZEN"})
    base.update(kw)
    return OpenReviewItemInput(**base)


def _pool(conn):
    pool = MagicMock()
    ctx = MagicMock(); ctx.__aenter__ = AsyncMock(return_value=conn); ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.mark.asyncio
async def test_opens_an_item_with_the_given_direction_and_reason(monkeypatch):
    calls = {}

    async def fake_open(conn, **kw):
        calls.update(kw)
    monkeypatch.setattr("modules.cts.workflows.activities.review_queue_activities.open_item", fake_open)
    assert await open_review_item(_inp(), db_pool=_pool(MagicMock())) is True
    assert calls["direction"] == "OUTWARD" and calls["escalation_reason"] == "PAYEE_ACCOUNT_FROZEN"
    assert calls["bank_id"] == "kbl" and calls["review_deadline_at"] is not None


@pytest.mark.asyncio
async def test_no_pool_degrades_without_raising():
    assert await open_review_item(_inp(), db_pool=None) is False


@pytest.mark.asyncio
async def test_db_error_degrades_without_raising(monkeypatch):
    async def boom(conn, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr("modules.cts.workflows.activities.review_queue_activities.open_item", boom)
    assert await open_review_item(_inp(), db_pool=_pool(MagicMock())) is False
