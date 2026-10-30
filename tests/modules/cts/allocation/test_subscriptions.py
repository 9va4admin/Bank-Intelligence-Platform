"""Admin-controlled reviewer-to-bucket subscriptions."""
import pytest

from modules.cts.allocation.subscriptions import SubscriptionStore, InvalidBucketError
from tests.modules.cts.allocation.fake_redis import FakeRedis
from tests.modules.cts.allocation.fake_subs_db import FakeSubsPool

BANK = "kbl"


@pytest.fixture
def pool():
    return FakeSubsPool()


@pytest.fixture
def store(pool):
    return SubscriptionStore(pool, redis=FakeRedis())


@pytest.mark.asyncio
async def test_set_and_read_a_reviewers_buckets(store):
    await store.set_reviewer_buckets(BANK, "alice", ["HVC", "CA"], changed_by="boss")
    assert sorted(await store.get_reviewer_buckets(BANK, "alice")) == ["CA", "HVC"]


@pytest.mark.asyncio
async def test_setting_replaces_the_previous_set_and_reports_what_changed(store):
    await store.set_reviewer_buckets(BANK, "alice", ["HVC", "CA"], changed_by="boss")
    added, removed = await store.set_reviewer_buckets(BANK, "alice", ["CA", "LVC"], changed_by="boss")
    assert (sorted(added), sorted(removed)) == (["LVC"], ["HVC"])
    assert sorted(await store.get_reviewer_buckets(BANK, "alice")) == ["CA", "LVC"]


@pytest.mark.asyncio
async def test_subscribers_are_listed_per_bucket(store):
    await store.set_reviewer_buckets(BANK, "alice", ["HVC"], changed_by="boss")
    await store.set_reviewer_buckets(BANK, "bob", ["HVC", "HR"], changed_by="boss")
    assert sorted(await store.get_subscribers(BANK, "HVC")) == ["alice", "bob"]
    assert await store.get_subscribers(BANK, "LVC") == []
    assert (await store.get_all(BANK))["HR"] == ["bob"]


@pytest.mark.asyncio
async def test_unknown_buckets_and_misc_cannot_be_subscribed(store):
    for bad in (["NOPE"], ["MISC"], ["hvc "]):
        with pytest.raises(InvalidBucketError):
            await store.set_reviewer_buckets(BANK, "alice", bad, changed_by="boss")


@pytest.mark.asyncio
async def test_clearing_a_reviewers_buckets_is_allowed(store):
    await store.set_reviewer_buckets(BANK, "alice", ["HVC"], changed_by="boss")
    await store.set_reviewer_buckets(BANK, "alice", [], changed_by="boss")
    assert await store.get_reviewer_buckets(BANK, "alice") == []


@pytest.mark.asyncio
async def test_reads_are_cached_and_a_write_refreshes_them(pool, store):
    await store.set_reviewer_buckets(BANK, "alice", ["HVC"], changed_by="boss")
    await store.get_subscribers(BANK, "HVC"); before = pool.calls
    await store.get_subscribers(BANK, "HVC")
    assert pool.calls == before                                   # served from the cache
    await store.set_reviewer_buckets(BANK, "bob", ["HVC"], changed_by="boss")
    assert sorted(await store.get_subscribers(BANK, "HVC")) == ["alice", "bob"]


@pytest.mark.asyncio
async def test_without_a_database_nobody_is_subscribed_so_nothing_is_wrongly_blocked(store):
    s = SubscriptionStore(None, redis=None)
    assert await s.get_subscribers(BANK, "HVC") == [] and await s.get_reviewer_buckets(BANK, "alice") == []


@pytest.mark.asyncio
async def test_a_reviewer_can_be_connected_to_the_validation_queue(store):
    await store.set_reviewer_buckets(BANK, "checker", ["VAL", "SIP_SUCCESS"], changed_by="boss")
    assert await store.get_subscribers(BANK, "VAL") == ["checker"]
