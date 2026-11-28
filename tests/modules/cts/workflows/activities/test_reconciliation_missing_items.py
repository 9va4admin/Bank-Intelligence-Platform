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


# ── only a count of what was submitted (the instrument list was not passed), and no database connection ──────────
# In production this activity is registered on the worker directly, so it never receives a db_pool. An early exit
# for "no db_pool" used to return RECONCILED without looking at the report at all.

@pytest.mark.asyncio
async def test_with_only_a_count_a_report_shorter_than_what_was_submitted_flags_the_gap():
    rows = [{"instrument_id": f"I{n}", "status": "SETTLED"} for n in (1, 2, 3)]
    res = await match_submitted_vs_settled(MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=5), db_pool=None)
    assert res.outcome == "EXCEPTIONS_FLAGGED"
    assert res.matched_count == 3 and res.exception_count == 2      # we know how many are missing, not which


@pytest.mark.asyncio
async def test_with_only_a_count_a_complete_report_still_reconciles():
    rows = [{"instrument_id": f"I{n}", "status": "SETTLED"} for n in (1, 2, 3)]
    res = await match_submitted_vs_settled(MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=3), db_pool=None)
    assert res.outcome == "RECONCILED" and res.matched_count == 3 and res.exception_count == 0


@pytest.mark.asyncio
async def test_with_only_a_count_a_returned_row_is_flagged_even_without_a_database():
    rows = [{"instrument_id": "I1", "status": "SETTLED"}, {"instrument_id": "I2", "status": "RETURNED"}]
    res = await match_submitted_vs_settled(MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=2), db_pool=None)
    assert res.outcome == "EXCEPTIONS_FLAGGED" and res.matched_count == 1 and res.exception_count == 1
    assert [e["instrument_id"] for e in res.exception_instruments] == ["I2"]


@pytest.mark.asyncio
async def test_with_only_a_count_returned_and_missing_items_are_both_counted():
    rows = [{"instrument_id": "I1", "status": "RETURNED"}]
    res = await match_submitted_vs_settled(MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=3), db_pool=None)
    assert res.outcome == "EXCEPTIONS_FLAGGED" and res.exception_count == 3     # 1 returned + 2 absent from the report


@pytest.mark.asyncio
async def test_a_repeated_row_does_not_hide_a_missing_instrument():
    rows = [{"instrument_id": "I1", "status": "SETTLED"}, {"instrument_id": "I1", "status": "SETTLED"}]
    res = await match_submitted_vs_settled(MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=2), db_pool=None)
    assert res.outcome == "EXCEPTIONS_FLAGGED" and res.matched_count == 1 and res.exception_count == 1


@pytest.mark.asyncio
async def test_an_empty_report_for_submitted_items_is_not_reconciled_even_without_a_database():
    res = await match_submitted_vs_settled(MatchInput(session_id="S", bank_id="kbl", settlement_rows=[], submitted_count=10), db_pool=None)
    assert res.outcome == "EXCEPTIONS_FLAGGED" and res.exception_count == 10 and res.matched_count == 0


@pytest.mark.asyncio
async def test_a_session_that_submitted_nothing_and_has_an_empty_report_reconciles():
    res = await match_submitted_vs_settled(MatchInput(session_id="S", bank_id="kbl", settlement_rows=[], submitted_count=0), db_pool=None)
    assert res.outcome == "RECONCILED" and res.exception_count == 0 and res.matched_count == 0


@pytest.mark.asyncio
async def test_the_instrument_list_is_used_without_a_database_too():
    rows = [{"instrument_id": "I1", "status": "SETTLED"}]
    res = await match_submitted_vs_settled(
        MatchInput(session_id="S", bank_id="kbl", settlement_rows=rows, submitted_count=2, submitted_instrument_ids=["I1", "I2"]), db_pool=None)
    assert res.outcome == "EXCEPTIONS_FLAGGED"
    assert [e["instrument_id"] for e in res.exception_instruments] == ["I2"]
