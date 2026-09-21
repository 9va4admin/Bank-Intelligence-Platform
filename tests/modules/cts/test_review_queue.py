"""Durable human-review queue: one table, `direction` flag (INWARD|OUTWARD), decisions kept in place
(status=DECIDED), every state change appended to cts.human_review_history. Before this the queue lived
only in Redis/Kafka and cts.human_review_items was written by no code."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.review_queue import list_open, open_item, record_decision


def _conn():
    c = AsyncMock()
    tx = MagicMock(); tx.__aenter__ = AsyncMock(return_value=None); tx.__aexit__ = AsyncMock(return_value=False)
    c.transaction = MagicMock(return_value=tx)
    c.fetchval = AsyncMock(return_value=uuid.uuid4())
    return c


@pytest.mark.asyncio
async def test_open_item_maps_id_to_uuid_and_appends_created_history():
    conn = _conn()
    rid = await open_item(conn, bank_id="kbl", direction="OUTWARD", instrument_id="000787-c687",
                          workflow_id="cts-outscan-kbl-1", parent_workflow_id="cts-outscan-kbl-1",
                          escalation_reason="PAYEE_NAME_MISMATCH", context_bundle={"k": 1},
                          review_deadline_at=datetime.now(timezone.utc) + timedelta(hours=4))
    assert isinstance(rid, uuid.UUID)
    sqls = [c.args[0] for c in conn.execute.await_args_list] + [c.args[0] for c in conn.fetchval.await_args_list]
    assert any("human_review_items" in q for q in sqls)
    assert any("human_review_history" in q and "CREATED" in " ".join(map(str, c.args)) for q in sqls
               for c in conn.execute.await_args_list)
    assert conn.fetchval.await_args_list[0].args[2] is not None     # instrument uuid argument present


@pytest.mark.asyncio
async def test_open_item_rejects_unknown_direction():
    with pytest.raises(ValueError):
        await open_item(_conn(), bank_id="kbl", direction="SIDEWAYS", instrument_id="x", workflow_id="w",
                        parent_workflow_id="w", escalation_reason="r", context_bundle={},
                        review_deadline_at=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_record_decision_updates_in_place_and_appends_history():
    conn = _conn(); conn.fetchrow = AsyncMock(return_value={"review_id": uuid.uuid4()})
    ok = await record_decision(conn, bank_id="kbl", workflow_id="w1", decision="RETURN",
                               reviewer_id="usr-ops-kbl", notes="tampered")
    assert ok is True
    updates = [c.args[0] for c in conn.fetchrow.await_args_list]
    assert any("UPDATE cts.human_review_items" in q and "DECIDED" in q for q in updates)
    assert not any("DELETE" in q.upper() for q in updates)                 # never moved/removed
    hist = [c for c in conn.execute.await_args_list if "human_review_history" in c.args[0]]
    assert hist and "DECIDED" in " ".join(map(str, hist[0].args))


@pytest.mark.asyncio
async def test_record_decision_returns_false_when_no_open_item():
    conn = _conn(); conn.fetchrow = AsyncMock(return_value=None)
    assert await record_decision(conn, bank_id="kbl", workflow_id="nope", decision="CONFIRM",
                                 reviewer_id="u", notes="n") is False


@pytest.mark.asyncio
async def test_list_open_filters_open_statuses_and_optional_direction():
    conn = _conn(); conn.fetch = AsyncMock(return_value=[])
    await list_open(conn, bank_id="kbl", direction="INWARD", limit=25)
    q, *args = conn.fetch.await_args.args
    assert "PENDING" in q and "ASSIGNED" in q and "DECIDED" not in q
    assert "INWARD" in args and 25 in args


@pytest.mark.skipif(not os.environ.get("ASTRA_MIGRATION_TEST_ADMIN_DSN"), reason="needs the dev database")
@pytest.mark.asyncio
async def test_against_the_real_table_and_history():
    """Real YugabyteDB: text instrument ids, text reviewer ids, no decision_id/IET for OUTWARD."""
    import asyncpg
    conn = await asyncpg.connect(os.environ["ASTRA_MIGRATION_TEST_ADMIN_DSN"])
    wf = f"rq-test-{uuid.uuid4().hex[:8]}"
    try:
        rid = await open_item(conn, bank_id="kbl", direction="OUTWARD", instrument_id="REAL-001",
                              workflow_id=wf, parent_workflow_id=wf, escalation_reason="PAYEE_FROZEN",
                              context_bundle={"a": 1}, review_deadline_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert (await list_open(conn, "kbl", direction="OUTWARD", limit=100))
        assert await record_decision(conn, bank_id="kbl", workflow_id=wf, decision="RETURN",
                                     reviewer_id="usr-ops-kbl", notes="ok") is True
        row = await conn.fetchrow("select status, reviewer_decision from cts.human_review_items where review_id=$1", rid)
        assert row["status"] == "DECIDED" and row["reviewer_decision"] == "RETURN"
        n = await conn.fetchval("select count(*) from cts.human_review_history where review_id=$1", rid)
        assert n == 2                                                       # CREATED + DECIDED
        assert not await list_open(conn, "kbl", direction="OUTWARD", limit=500) or all(
            r["workflow_id"] != wf for r in await list_open(conn, "kbl", direction="OUTWARD", limit=500))
    finally:
        await conn.execute("delete from cts.human_review_history where bank_id='kbl' and review_id in "
                           "(select review_id from cts.human_review_items where workflow_id=$1)", wf)
        await conn.execute("delete from cts.human_review_items where workflow_id=$1", wf)
        await conn.close()


# ── stage / level (where the item is in human review) ────────────────────────────────────────────

from modules.cts.review_queue import assign, escalate, start_review, STAGES


def test_stages_are_the_documented_lifecycle():
    assert STAGES == ("PENDING", "ASSIGNED", "IN_REVIEW", "DECIDED")


@pytest.mark.asyncio
async def test_open_item_records_tier_and_starts_at_level_1():
    conn = _conn()
    await open_item(conn, bank_id="kbl", direction="INWARD", instrument_id="i", workflow_id="w",
                    parent_workflow_id="w", escalation_reason="r", context_bundle={},
                    review_deadline_at=datetime.now(timezone.utc), queue_tier="high_value")
    args = conn.fetchval.await_args_list[0].args
    assert "high_value" in args and 1 in args                     # queue_tier and review_level=1


@pytest.mark.asyncio
@pytest.mark.parametrize("fn,kwargs,event", [
    (assign, dict(reviewer_id="usr-rev-1", zone="MUMBAI"), "ASSIGNED"),
    (start_review, dict(reviewer_id="usr-rev-1"), "IN_REVIEW"),
])
async def test_transitions_update_status_and_append_history(fn, kwargs, event):
    conn = _conn(); conn.fetchrow = AsyncMock(return_value={"review_id": uuid.uuid4()})
    assert await fn(conn, bank_id="kbl", workflow_id="w", **kwargs) is True
    assert any(event in q.args[0] or event in " ".join(map(str, q.args)) for q in conn.fetchrow.await_args_list)
    hist = [c for c in conn.execute.await_args_list if "human_review_history" in c.args[0]]
    assert hist and event in " ".join(map(str, hist[0].args))


@pytest.mark.asyncio
async def test_escalate_raises_level_and_requeues_pending():
    conn = _conn(); conn.fetchrow = AsyncMock(return_value={"review_id": uuid.uuid4(), "review_level": 2})
    lvl = await escalate(conn, bank_id="kbl", workflow_id="w", actor="usr-rev-1", reason="high value")
    assert lvl == 2
    q = conn.fetchrow.await_args_list[0].args[0]
    assert "review_level = review_level + 1" in q and "'PENDING'" in q
    hist = [c for c in conn.execute.await_args_list if "human_review_history" in c.args[0]]
    assert "ESCALATED" in " ".join(map(str, hist[0].args))


@pytest.mark.asyncio
async def test_escalate_unknown_item_returns_none():
    conn = _conn(); conn.fetchrow = AsyncMock(return_value=None)
    assert await escalate(conn, bank_id="kbl", workflow_id="nope", actor="u", reason="r") is None


from modules.cts.review_queue import decide_by_instrument


@pytest.mark.asyncio
async def test_decide_by_instrument_targets_the_open_item_of_that_direction():
    conn = _conn(); conn.fetchrow = AsyncMock(return_value={"review_id": uuid.uuid4()})
    ok = await decide_by_instrument(conn, bank_id="kbl", direction="OUTWARD", instrument_ref="000787-c687",
                                    decision="RETURN", reviewer_id="usr-ops-kbl", notes="frozen payee")
    assert ok is True
    q, *args = conn.fetchrow.await_args_list[0].args
    assert "instrument_ref" in q and "direction" in q and "DECIDED" in q
    assert "OUTWARD" in args and "000787-c687" in args


@pytest.mark.asyncio
async def test_decide_by_instrument_false_when_nothing_open():
    conn = _conn(); conn.fetchrow = AsyncMock(return_value=None)
    assert await decide_by_instrument(conn, bank_id="kbl", direction="INWARD", instrument_ref="x",
                                      decision="CONFIRM", reviewer_id="u", notes="n") is False
