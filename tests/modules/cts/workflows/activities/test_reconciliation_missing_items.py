"""An instrument we submitted that NGCH's settlement report does not mention at all must be flagged, never silently reconciled.

Found on reading match_submitted_vs_settled: it received submitted_count but never used it, so a report that left out
submitted items (or came back empty because NGCH was unreachable) produced outcome RECONCILED with no exceptions."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.workflows.activities.session_reconciliation_activities import (
    MatchInput, match_submitted_vs_settled,
)


def _pool():
    p = MagicMock()
    p.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    p.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return p


@pytest.mark.asyncio
async def test_a_submitted_instrument_missing_from_the_report_is_an_exception():
    rows = [{"instrument_id": "I1", "status": "SETTLED"}]
    res = await match_submitted_vs_settled(
        MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=2,
                   submitted_instrument_ids=["I1", "I2"]), db_pool=_pool())
    assert res.outcome == "EXCEPTIONS_FLAGGED" and res.matched_count == 1 and res.exception_count == 1
    assert res.exception_instruments == [{"instrument_id": "I2", "status": "MISSING_FROM_SETTLEMENT",
                                          "reason": "Submitted but not in the NGCH settlement report"}]


@pytest.mark.asyncio
async def test_an_empty_report_never_reconciles_a_session_that_submitted_items():
    res = await match_submitted_vs_settled(
        MatchInput(session_id="S", bank_id="kbl", settlement_rows=[], submitted_count=3,
                   submitted_instrument_ids=["I1", "I2", "I3"], report_unavailable=True), db_pool=_pool())
    assert res.outcome == "EXCEPTIONS_FLAGGED" and res.exception_count == 3


@pytest.mark.asyncio
async def test_an_unavailable_report_with_only_a_count_is_still_not_reconciled():
    res = await match_submitted_vs_settled(
        MatchInput(session_id="S", bank_id="kbl", settlement_rows=[], submitted_count=5, report_unavailable=True), db_pool=_pool())
    assert res.outcome == "EXCEPTIONS_FLAGGED"


@pytest.mark.asyncio
async def test_a_report_row_for_an_instrument_we_did_not_submit_is_not_counted_as_matched():
    rows = [{"instrument_id": "I1", "status": "SETTLED"}, {"instrument_id": "X9", "status": "SETTLED"}]
    res = await match_submitted_vs_settled(
        MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=1,
                   submitted_instrument_ids=["I1"]), db_pool=_pool())
    assert res.matched_count == 1 and res.outcome == "EXCEPTIONS_FLAGGED"
    assert [e["instrument_id"] for e in res.exception_instruments] == ["X9"]


@pytest.mark.asyncio
async def test_everything_submitted_and_settled_still_reconciles():
    rows = [{"instrument_id": "I1", "status": "SETTLED"}, {"instrument_id": "I2", "status": "SETTLED"}]
    res = await match_submitted_vs_settled(
        MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=2,
                   submitted_instrument_ids=["I1", "I2"]), db_pool=_pool())
    assert res.outcome == "RECONCILED" and res.matched_count == 2 and res.exception_count == 0
