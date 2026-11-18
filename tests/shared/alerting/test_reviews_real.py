"""Post-incident reviews and mitigation actions on the real dev YugabyteDB: a review becomes due for a resolved P0/P1 incident, is submitted, produces actions; an action is
finished with evidence and verified by a DIFFERENT person; an effectiveness hint is computed from recurrence; overdue is computed from bank settings."""
import asyncio
import socket
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg
import pytest

from shared.alerting.audit import AlertAuditor
from shared.alerting.reviews import ReviewInvalid, ReviewStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
GOOD = dict(category="capacity", narrative="Redis ran out of memory after the nightly vault warm-up and evicted keys.", contributing="No memory alert", detection_gap="Found by users", impact="Vault lookups slow")


def db(fn):
    def wrapper():
        async def go():
            pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
            bank = f"rv-{uuid.uuid4().hex[:8]}"
            events = []

            async def sink(event_type, bank_id, entity_id, actor_id, payload):
                events.append((event_type, entity_id, actor_id, payload))
                return "tx"
            store = ReviewStore(pool, due_days={"P0": 3, "P1": 7}, effectiveness_days=30, min_narrative_chars=20, auditor=AlertAuditor(sink))
            try:
                await fn(store, pool, bank, events)
            finally:
                for t in ("alert_actions", "alert_reviews", "alert_incidents", "alert_risks"):
                    await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id LIKE 'rv-%'")
                await pool.close()
        asyncio.run(go())
    return wrapper


async def submitted(store, bank, incident="i1", severity="P0", **kw):
    await store.ensure_due(bank, incident, severity, "redis", "redis:down", resolved_at=kw.pop("resolved_at", NOW))
    review = (await store.list_reviews(bank, now=NOW))[0]
    return await store.submit(bank, review.review_id, "ops-1", **{**GOOD, **kw})


@db
async def test_a_resolved_p0_or_p1_incident_gets_one_review_due_and_lower_severities_get_none(store, pool, bank, events):
    assert await store.ensure_due(bank, "i1", "P0", "redis", "redis:down", resolved_at=NOW) is True
    assert await store.ensure_due(bank, "i1", "P0", "redis", "redis:down", resolved_at=NOW) is False          # one per incident
    assert await store.ensure_due(bank, "i2", "P1", "kafka", "kafka:down", resolved_at=NOW) is True
    assert await store.ensure_due(bank, "i3", "P2", "cbs", "cbs:slow", resolved_at=NOW) is False
    assert await store.ensure_due(bank, "i4", "P3", "cbs", "cbs:info", resolved_at=NOW) is False
    reviews = await store.list_reviews(bank, now=NOW)
    assert {r.incident_id for r in reviews} == {"i1", "i2"} and all(r.status == "DUE" for r in reviews)


@db
async def test_the_due_date_comes_from_the_bank_settings_by_severity_and_overdue_is_worked_out_when_read(store, pool, bank, events):
    await store.ensure_due(bank, "p0", "P0", "redis", "k0", resolved_at=NOW - timedelta(days=4))             # due after 3 days: overdue
    await store.ensure_due(bank, "p1", "P1", "kafka", "k1", resolved_at=NOW - timedelta(days=4))             # due after 7 days: not yet
    by = {r.incident_id: r for r in await store.list_reviews(bank, now=NOW)}
    assert by["p0"].overdue is True and by["p1"].overdue is False
    assert by["p0"].due_at == NOW - timedelta(days=1) and by["p1"].due_at == NOW + timedelta(days=3)


@db
async def test_submitting_needs_a_known_cause_a_real_narrative_and_an_existing_risk_and_is_audited_without_the_text(store, pool, bank, events):
    await store.ensure_due(bank, "i1", "P0", "redis", "k", resolved_at=NOW)
    rid = (await store.list_reviews(bank, now=NOW))[0].review_id
    for bad, code in ((dict(category="bad"), "bad_category"), (dict(narrative="too short"), "narrative_short"), (dict(risk_id="nope"), "unknown_risk")):
        with pytest.raises(ReviewInvalid) as e:
            await store.submit(bank, rid, "ops-1", **{**GOOD, **bad})
        assert e.value.code == code
    done = await store.submit(bank, rid, "ops-1", **GOOD)
    assert done.status == "SUBMITTED" and done.submitted_by == "ops-1" and done.root_cause_category == "capacity"
    with pytest.raises(ReviewInvalid) as e:
        await store.submit(bank, rid, "ops-1", **GOOD)
    assert e.value.code == "already_submitted"
    assert [x for x in events if x[0] == "ALERT_REVIEW_CHANGED"] and "Redis ran out" not in str(events)


@db
async def test_actions_belong_to_a_submitted_review_and_move_through_their_states_with_evidence(store, pool, bank, events):
    await store.ensure_due(bank, "i1", "P0", "redis", "k", resolved_at=NOW)
    rid = (await store.list_reviews(bank, now=NOW))[0].review_id
    with pytest.raises(ReviewInvalid) as e:
        await store.add_action(bank, rid, "ops-1", "preventive", "Add a memory alert", "SRE lead", date(2026, 12, 1))
    assert e.value.code == "review_not_submitted"
    await store.submit(bank, rid, "ops-1", **GOOD)
    a = await store.add_action(bank, rid, "ops-1", "preventive", "Add a memory alert", "SRE lead", date(2026, 12, 1), today=date(2026, 11, 20))
    assert a.status == "OPEN" and a.owner == "SRE lead"
    with pytest.raises(ReviewInvalid) as e:
        await store.set_status(bank, a.action_id, "sre-1", "DONE")
    assert e.value.code == "evidence_required"
    assert (await store.set_status(bank, a.action_id, "sre-1", "IN_PROGRESS")).status == "IN_PROGRESS"
    done = await store.set_status(bank, a.action_id, "sre-1", "DONE", evidence="Alert rule PR 123 merged")
    assert done.status == "DONE" and done.done_by == "sre-1" and done.evidence == "Alert rule PR 123 merged"
    with pytest.raises(ReviewInvalid) as e:
        await store.add_action(bank, rid, "ops-1", "preventive", "x", "y", date(2026, 11, 1), today=date(2026, 11, 20))
    assert e.value.code == "due_in_past"


@db
async def test_a_different_person_verifies_or_sends_it_back_and_wont_fix_needs_a_reason(store, pool, bank, events):
    review = await submitted(store, bank)
    a = await store.add_action(bank, review.review_id, "ops-1", "corrective", "Raise the memory limit", "SRE lead", date(2026, 12, 1), today=date(2026, 11, 20))
    await store.set_status(bank, a.action_id, "sre-1", "DONE", evidence="Limit raised")
    with pytest.raises(ReviewInvalid) as e:
        await store.set_status(bank, a.action_id, "sre-1", "VERIFIED")
    assert e.value.code == "same_person"
    back = await store.set_status(bank, a.action_id, "comp-1", "IN_PROGRESS", note="Evidence does not show the limit")
    assert back.status == "IN_PROGRESS"
    await store.set_status(bank, a.action_id, "sre-1", "DONE", evidence="Limit raised, screenshot attached")
    ok = await store.set_status(bank, a.action_id, "comp-1", "VERIFIED", note="Checked the config")
    assert ok.status == "VERIFIED" and ok.verified_by == "comp-1"
    b = await store.add_action(bank, review.review_id, "ops-1", "preventive", "Another", "SRE lead", date(2026, 12, 1), today=date(2026, 11, 20))
    with pytest.raises(ReviewInvalid) as e:
        await store.set_status(bank, b.action_id, "ops-1", "WONT_FIX")
    assert e.value.code == "note_required"
    assert (await store.set_status(bank, b.action_id, "ops-1", "WONT_FIX", note="Superseded by the memory limit")).status == "WONT_FIX"
    with pytest.raises(ReviewInvalid) as e:
        await store.set_status(bank, b.action_id, "ops-1", "OPEN")
    assert e.value.code == "bad_transition"


@db
async def test_overdue_actions_and_the_effectiveness_hint_are_worked_out_from_recurrence(store, pool, bank, events):
    review = await submitted(store, bank, resolved_at=NOW - timedelta(days=60))
    a = await store.add_action(bank, review.review_id, "ops-1", "corrective", "Raise the limit", "SRE lead", date(2026, 11, 25), today=date(2026, 11, 20))
    old = await store.add_action(bank, review.review_id, "ops-1", "corrective", "Old action", "SRE lead", date(2026, 11, 22), today=date(2026, 11, 20))
    by = {x.action_id: x for x in await store.list_actions(bank, today=date(2026, 12, 1), now=NOW + timedelta(days=11))}
    assert by[a.action_id].overdue is True and by[a.action_id].effectiveness == "NA"
    await store.set_status(bank, a.action_id, "sre-1", "DONE", evidence="Raised")
    await pool.execute("UPDATE platform.alert_actions SET done_at = $2 WHERE action_id = $1", a.action_id, NOW - timedelta(days=40))
    assert {x.action_id: x for x in await store.list_actions(bank, now=NOW)}[a.action_id].effectiveness == "EFFECTIVE_SUGGESTED"     # 40 quiet days, no recurrence
    await pool.execute("UPDATE platform.alert_actions SET done_at = $2 WHERE action_id = $1", a.action_id, NOW - timedelta(days=5))
    assert {x.action_id: x for x in await store.list_actions(bank, now=NOW)}[a.action_id].effectiveness == "TOO_EARLY"
    await pool.execute("INSERT INTO platform.alert_incidents (incident_id, bank_id, dedup_key, alert_id, component, severity, state, summary, opened_at) "
                       "VALUES ($1,$2,'redis:down','a','redis','P0','RESOLVED','again',$3)", uuid.uuid4().hex, bank, NOW - timedelta(days=2))
    assert {x.action_id: x for x in await store.list_actions(bank, now=NOW)}[a.action_id].effectiveness == "RECURRED"
    assert old.status == "OPEN"
