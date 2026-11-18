"""Alert risk register on the real dev YugabyteDB: seeded from the shipped template (idempotent), every risk gets an owner, only a person declares a risk mitigated and a
DIFFERENT person verifies it, ratings, review dates, audit."""
import asyncio
import socket
import uuid
from datetime import date, timedelta

import asyncpg
import pytest

from shared.alerting.audit import AlertAuditor
from shared.alerting.risk_template import RISK_TEMPLATE
from shared.alerting.risks import RiskInvalid, RiskStore

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def db(fn):
    def wrapper():
        async def go():
            pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
            bank = f"rk-{uuid.uuid4().hex[:8]}"
            events = []

            async def sink(event_type, bank_id, entity_id, actor_id, payload):
                events.append((event_type, entity_id, actor_id, payload))
                return "tx"
            try:
                await fn(RiskStore(pool, review_days=90, auditor=AlertAuditor(sink)), pool, bank, events)
            finally:
                await pool.execute("DELETE FROM platform.alert_risks WHERE bank_id LIKE 'rk-%'")
                await pool.close()
        asyncio.run(go())
    return wrapper


@db
async def test_seeding_creates_every_template_risk_once_with_no_owner_and_a_review_date(store, pool, bank, events):
    assert await store.seed(bank, "admin-1") == len(RISK_TEMPLATE)
    assert await store.seed(bank, "admin-1") == 0                                              # idempotent
    risks = await store.list(bank)
    assert len(risks) == len(RISK_TEMPLATE) and all(r.owner is None and r.status == "OPEN" and r.next_review_on is not None for r in risks)
    assert all(r.title and r.description and 1 <= r.likelihood <= 5 and 1 <= r.impact <= 5 for r in risks)
    assert risks[0].rating == risks[0].likelihood * risks[0].impact


@db
async def test_an_owner_a_mitigation_and_ratings_can_be_set_and_are_checked_and_audited(store, pool, bank, events):
    await store.seed(bank, "admin-1")
    risk = (await store.list(bank))[0]
    updated = await store.update(bank, risk.risk_id, "ops-1", owner="Duty manager", mitigation="Second mail relay added", likelihood=2, impact=4)
    assert updated.owner == "Duty manager" and updated.rating == 8 and updated.mitigation == "Second mail relay added"
    for bad in (dict(likelihood=0), dict(impact=6), dict(owner="   "), dict(owner="x" * 200), dict(next_review_on=date.today() - timedelta(days=400))):
        with pytest.raises(RiskInvalid):
            await store.update(bank, risk.risk_id, "ops-1", **bad)
    with pytest.raises(RiskInvalid) as e:
        await store.update(bank, "nope", "ops-1", owner="x")
    assert e.value.code == "not_found"
    audit = [x for x in events if x[0] == "ALERT_RISK_CHANGED"]
    assert audit and audit[-1][2] == "ops-1" and "Second mail relay" not in str(audit)             # who and what changed; the free text is not copied


@db
async def test_a_risk_is_declared_mitigated_by_one_person_and_verified_by_a_different_one(store, pool, bank, events):
    await store.seed(bank, "admin-1")
    rid = (await store.list(bank))[0].risk_id
    with pytest.raises(RiskInvalid) as e:
        await store.declare_mitigated(bank, rid, "ops-1")
    assert e.value.code == "needs_owner_and_mitigation"
    await store.update(bank, rid, "ops-1", owner="Duty manager", mitigation="Relay added")
    declared = await store.declare_mitigated(bank, rid, "ops-1")
    assert declared.status == "MITIGATED" and declared.declared_by == "ops-1"
    with pytest.raises(RiskInvalid) as e:
        await store.verify(bank, rid, "ops-1")
    assert e.value.code == "same_person"
    verified = await store.verify(bank, rid, "compliance-1")
    assert verified.status == "VERIFIED" and verified.verified_by == "compliance-1"
    reopened = await store.reopen(bank, rid, "compliance-1")
    assert reopened.status == "OPEN" and reopened.declared_by is None and reopened.verified_by is None


@db
async def test_a_risk_that_is_not_mitigated_cannot_be_verified_and_the_system_never_closes_one_by_itself(store, pool, bank, events):
    await store.seed(bank, "admin-1")
    rid = (await store.list(bank))[0].risk_id
    with pytest.raises(RiskInvalid) as e:
        await store.verify(bank, rid, "compliance-1")
    assert e.value.code == "not_mitigated"
    await store.update(bank, rid, "ops-1", owner="Duty manager", mitigation="Relay added")
    await store.declare_mitigated(bank, rid, "ops-1")
    await store.update(bank, rid, "ops-1", mitigation="Changed my mind")                          # changing the mitigation after it was declared reopens it
    assert (await store.list(bank))[0].status == "OPEN"


@db
async def test_a_summary_counts_risks_without_an_owner_overdue_reviews_and_verified_ones_and_banks_are_apart(store, pool, bank, events):
    await store.seed(bank, "admin-1")
    await store.seed(bank + "-other", "admin-1")
    risks = await store.list(bank)
    await store.update(bank, risks[0].risk_id, "ops-1", owner="A")
    await pool.execute("UPDATE platform.alert_risks SET next_review_on = CURRENT_DATE - 3 WHERE risk_id=$1", risks[1].risk_id)
    summary = await store.summary(bank)
    assert summary.total == len(RISK_TEMPLATE) and summary.without_owner == len(RISK_TEMPLATE) - 1 and summary.review_overdue == 1 and summary.verified == 0
    assert (await store.summary(bank + "-empty")).total == 0
