"""Bucket-aware allocation: reviewers work only the buckets an admin connected them to; MISC is self-claim only;
de-allocation and no-subscriber items go to MISC; rebalancing stays inside a bucket."""
import time

import pytest

from modules.cts.allocation.allocation_service import AllocationService
from modules.cts.allocation.lock_service import LockService
from modules.cts.allocation.subscriptions import SubscriptionStore
from tests.modules.cts.allocation.fake_redis import FakeRedis
from tests.modules.cts.allocation.fake_subs_db import FakeSubsPool

BANK = "kbl"
CFG = {"allocation_mode": "AUTO", "allocation_lock_ttl_minutes": 10, "allocation_strategy": "LEAST_LOADED",
       "allocation_max_per_reviewer": 10, "allocation_urgent_margin_minutes": 30, "allocation_rebalance_enabled": True,
       "allocation_rebalance_max_moves": 20, "bucket_routing_enabled": True, "bucket_overflow_after_minutes": 10}


@pytest.fixture
def parts():
    redis = FakeRedis()
    lock = LockService(redis)
    subs = SubscriptionStore(FakeSubsPool(), redis=None)
    return lock, subs, AllocationService(lock, subscriptions=subs), redis


async def _item(lock, iid, bucket, **kw):
    await lock.set_item_meta(BANK, iid, bucket=bucket, queued_at=kw.pop("queued_at", time.time()), **kw)


async def _setup(lock, subs, who_buckets):
    for who, buckets in who_buckets.items():
        await subs.set_reviewer_buckets(BANK, who, buckets, "boss")
        await lock.heartbeat_reviewer(BANK, who)


# --- auto-assign stays inside the bucket --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_assign_only_considers_reviewers_subscribed_to_the_items_bucket(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"hv": ["HVC"], "lv": ["LVC"]})
    await _item(lock, "i-1", "HVC")
    res = await alloc.auto_assign("i-1", ["hv", "lv"], CFG, bank_id=BANK)
    assert res.claimed and res.reviewer_id == "hv"


@pytest.mark.asyncio
async def test_a_bucket_nobody_is_subscribed_to_is_not_auto_assigned(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"lv": ["LVC"]})
    await _item(lock, "i-1", "HVC")
    res = await alloc.auto_assign("i-1", ["lv"], CFG, bank_id=BANK)
    assert res.claimed is False and res.reason == "NO_ELIGIBLE_REVIEWER"


@pytest.mark.asyncio
async def test_misc_is_never_auto_assigned(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"hv": ["HVC"]})
    await _item(lock, "i-1", "MISC")
    res = await alloc.auto_assign("i-1", ["hv"], CFG, bank_id=BANK)
    assert res.claimed is False and res.reason == "MISC_SELF_CLAIM"


@pytest.mark.asyncio
async def test_routing_off_keeps_the_flat_pool(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "i-1", "HVC")
    res = await alloc.auto_assign("i-1", ["anyone"], {**CFG, "bucket_routing_enabled": False}, bank_id=BANK)
    assert res.claimed and res.reviewer_id == "anyone"


# --- claim -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_reviewer_can_claim_from_a_subscribed_bucket_and_from_misc_only(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"hv": ["HVC"]})
    await _item(lock, "mine", "HVC"); await _item(lock, "other", "LVC"); await _item(lock, "misc", "MISC")
    mine = await alloc.claim("mine", "hv", CFG, bank_id=BANK, reviewer_buckets=["HVC"])
    other = await alloc.claim("other", "hv", CFG, bank_id=BANK, reviewer_buckets=["HVC"])
    misc = await alloc.claim("misc", "hv", CFG, bank_id=BANK, reviewer_buckets=["HVC"])
    assert mine.claimed and misc.claimed
    assert other.claimed is False and other.reason == "NOT_SUBSCRIBED"


@pytest.mark.asyncio
async def test_unrestricted_claimers_such_as_managers_can_claim_any_bucket(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "i-1", "LVC")
    assert (await alloc.claim("i-1", "mgr", CFG, bank_id=BANK, reviewer_buckets=None)).claimed


@pytest.mark.asyncio
async def test_routing_off_ignores_subscriptions_on_claim(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "i-1", "LVC")
    cfg = {**CFG, "bucket_routing_enabled": False}
    assert (await alloc.claim("i-1", "hv", cfg, bank_id=BANK, reviewer_buckets=["HVC"])).claimed


# --- de-allocation and overflow go to MISC ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_releasing_a_claim_sends_the_item_to_misc_and_remembers_where_it_came_from(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "i-1", "HVC")
    await alloc.claim("i-1", "hv", CFG, bank_id=BANK)
    await alloc.unclaim("i-1", "hv", CFG, bank_id=BANK)
    meta = await lock.get_item_meta(BANK, "i-1")
    assert meta["bucket"] == "MISC" and meta["origin_bucket"] == "HVC"
    assert await lock.get_lock_holder("i-1") is None


@pytest.mark.asyncio
async def test_an_item_already_in_misc_keeps_its_original_bucket_when_released_again(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "i-1", "MISC", origin_bucket="CA")
    await alloc.move_to_misc(BANK, "i-1")
    assert (await lock.get_item_meta(BANK, "i-1"))["origin_bucket"] == "CA"


@pytest.mark.asyncio
async def test_with_routing_off_release_does_not_move_the_item(parts):
    lock, subs, alloc, _ = parts
    cfg = {**CFG, "bucket_routing_enabled": False}
    await _item(lock, "i-1", "HVC")
    await alloc.claim("i-1", "hv", cfg, bank_id=BANK)
    await alloc.unclaim("i-1", "hv", cfg, bank_id=BANK)
    assert (await lock.get_item_meta(BANK, "i-1"))["bucket"] == "HVC"


@pytest.mark.asyncio
async def test_item_with_no_active_subscriber_overflows_to_misc_after_the_wait(parts):
    lock, subs, alloc, _ = parts
    await subs.set_reviewer_buckets(BANK, "hv", ["HVC"], "boss")            # subscribed but not logged in
    await _item(lock, "old", "HVC", queued_at=time.time() - 11 * 60)
    await _item(lock, "new", "HVC", queued_at=time.time() - 2 * 60)
    assert await alloc.overflow_if_stale(BANK, "old", CFG) is True
    assert await alloc.overflow_if_stale(BANK, "new", CFG) is False
    meta = await lock.get_item_meta(BANK, "old")
    assert meta["bucket"] == "MISC" and meta["origin_bucket"] == "HVC"


@pytest.mark.asyncio
async def test_item_with_an_active_subscriber_does_not_overflow_even_when_old(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"hv": ["HVC"]})
    await _item(lock, "old", "HVC", queued_at=time.time() - 60 * 60)
    assert await alloc.overflow_if_stale(BANK, "old", CFG) is False


@pytest.mark.asyncio
async def test_claimed_items_never_overflow(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "old", "HVC", queued_at=time.time() - 60 * 60)
    await lock.acquire_lock("old", "hv", CFG)
    assert await alloc.overflow_if_stale(BANK, "old", CFG) is False


# --- rebalance and admin assign stay inside the bucket ----------------------------------------------------------

@pytest.mark.asyncio
async def test_rebalance_only_moves_work_to_reviewers_subscribed_to_that_bucket(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"hv1": ["HVC"], "lv": ["LVC"]})
    for i in range(6):
        await _item(lock, f"h-{i}", "HVC")
        await lock.acquire_lock(f"h-{i}", "hv1", CFG)
        await lock.mark_auto(BANK, f"h-{i}")
    res = await alloc.rebalance(BANK, CFG)
    assert res.moves == []                                       # lv is not subscribed to HVC
    await _setup(lock, subs, {"hv2": ["HVC"]})
    res = await alloc.rebalance(BANK, CFG)
    assert len(res.moves) == 3 and all(to == "hv2" for _, _, to in res.moves)


@pytest.mark.asyncio
async def test_can_take_refuses_an_unsubscribed_reviewer_but_misc_is_open(parts):
    lock, subs, alloc, _ = parts
    await subs.set_reviewer_buckets(BANK, "lv", ["LVC"], "boss")
    await _item(lock, "hv-item", "HVC")
    await _item(lock, "misc-item", "MISC")
    assert await alloc.can_take(BANK, "hv-item", "lv", CFG) is False
    assert await alloc.can_take(BANK, "misc-item", "lv", CFG) is True
    assert await alloc.can_take(BANK, "hv-item", "lv", {**CFG, "bucket_routing_enabled": False}) is True


# --- maker-checker: the checker queue and the four-eyes rule -------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_assign_skips_excluded_reviewers_such_as_the_maker(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"maker": ["VAL"], "checker": ["VAL"]})
    await _item(lock, "i-1", "VAL")
    res = await alloc.auto_assign("i-1", ["maker", "checker"], CFG, bank_id=BANK, exclude={"maker"})
    assert res.claimed and res.reviewer_id == "checker"


@pytest.mark.asyncio
async def test_if_only_the_maker_is_available_nobody_gets_the_validation_item(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"maker": ["VAL"]})
    await _item(lock, "i-1", "VAL")
    res = await alloc.auto_assign("i-1", ["maker"], CFG, bank_id=BANK, exclude={"maker"})
    assert res.claimed is False and res.reason in ("NO_ELIGIBLE_REVIEWER", "NO_ACTIVE_REVIEWERS")


@pytest.mark.asyncio
async def test_the_maker_cannot_claim_the_validation_item(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "i-1", "VAL", origin_bucket="HVC")
    await lock.update_item_meta(BANK, "i-1", maker_id="maker", stage="VALIDATION")
    res = await alloc.claim("i-1", "maker", CFG, bank_id=BANK, reviewer_buckets=["VAL"])
    assert res.claimed is False and res.reason == "FOUR_EYES"
    assert (await alloc.claim("i-1", "checker", CFG, bank_id=BANK, reviewer_buckets=["VAL"])).claimed


@pytest.mark.asyncio
async def test_four_eyes_applies_even_when_bucket_routing_is_off(parts):
    lock, subs, alloc, _ = parts
    await _item(lock, "i-1", "VAL")
    await lock.update_item_meta(BANK, "i-1", maker_id="maker", stage="VALIDATION")
    res = await alloc.claim("i-1", "maker", {**CFG, "bucket_routing_enabled": False}, bank_id=BANK)
    assert res.reason == "FOUR_EYES"


@pytest.mark.asyncio
async def test_admin_cannot_assign_the_validation_item_to_the_maker(parts):
    lock, subs, alloc, _ = parts
    await subs.set_reviewer_buckets(BANK, "maker", ["VAL"], "boss")
    await _item(lock, "i-1", "VAL")
    await lock.update_item_meta(BANK, "i-1", maker_id="maker", stage="VALIDATION")
    assert await alloc.can_take(BANK, "i-1", "maker", CFG) is False
    await subs.set_reviewer_buckets(BANK, "checker", ["VAL"], "boss")
    assert await alloc.can_take(BANK, "i-1", "checker", CFG) is True


@pytest.mark.asyncio
async def test_rebalance_never_moves_a_validation_item_to_its_maker(parts):
    lock, subs, alloc, _ = parts
    await _setup(lock, subs, {"c1": ["VAL"], "maker": ["VAL"]})
    for i in range(4):
        await _item(lock, f"v-{i}", "VAL")
        await lock.update_item_meta(BANK, f"v-{i}", maker_id="maker", stage="VALIDATION")
        await lock.acquire_lock(f"v-{i}", "c1", CFG)
        await lock.mark_auto(BANK, f"v-{i}")
    res = await alloc.rebalance(BANK, CFG)
    assert res.moves == []
