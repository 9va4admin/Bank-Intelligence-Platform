"""Both decide endpoints must record the decision in the durable review queue (status=DECIDED + history),
in addition to signalling the workflow."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from apps.api.routers.cts_inward import ReviewDecisionRequest, submit_review_decision


def _pool(conn):
    pool = MagicMock(); ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn); ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.mark.asyncio
async def test_inward_decision_is_recorded(monkeypatch):
    seen = {}

    async def fake_decide(conn, **kw):
        seen.update(kw); return True
    monkeypatch.setattr("apps.api.routers.cts_inward.decide_by_instrument", fake_decide)
    req = MagicMock(); req.app.state.temporal_client = None; req.app.state.db_pool_cts = _pool(AsyncMock())
    await submit_review_decision(instrument_id="INST-9", body=ReviewDecisionRequest(action="RETURN", reason="tampered"),
                                 request=req, bank_id="kbl", reviewer_id="usr-rev-1")
    assert seen["direction"] == "INWARD" and seen["instrument_ref"] == "INST-9"
    assert seen["decision"] == "RETURN" and seen["reviewer_id"] == "usr-rev-1" and seen["notes"] == "tampered"


@pytest.mark.asyncio
async def test_inward_decision_still_succeeds_if_the_queue_write_fails(monkeypatch):
    async def boom(conn, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr("apps.api.routers.cts_inward.decide_by_instrument", boom)
    req = MagicMock(); req.app.state.temporal_client = None; req.app.state.db_pool_cts = _pool(AsyncMock())
    res = await submit_review_decision(instrument_id="INST-9", body=ReviewDecisionRequest(action="CONFIRM", reason="ok"),
                                       request=req, bank_id="kbl", reviewer_id="u")
    assert res.instrument_id == "INST-9"
