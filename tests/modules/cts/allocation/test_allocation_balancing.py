"""AllocationService: least-loaded choice, per-reviewer cap, clearing-zone scoping, urgent items, admin assign,
rebalancing as reviewers log in."""
import time

import pytest

from modules.cts.allocation.allocation_service import AllocationService
from modules.cts.allocation.lock_service import LockService
from tests.modules.cts.allocation.fake_redis import FakeRedis

BANK = "kbl"
AUTO = {"allocation_mode": "AUTO", "allocation_lock_ttl_minutes": 10, "allocation_strategy": "LEAST_LOADED",
        "allocation_max_per_reviewer": 3, "allocation_urgent_margin_minutes": 30,
        "allocation_rebalance_enabled": True, "allocation_rebalance_max_moves": 20}


@pytest.fixture
def lock():
    return LockService(redis_client=FakeRedis())


@pytest.fixture
def alloc(lock):
    return AllocationService(lock_service=lock)


async def _hold(lock, who, n, prefix="x"):
    for i in range(n):
        await lock.acquire_lock(f"{prefix}-{who}-{i}", who, AUTO)


# --- least loaded -----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_assign_picks_the_least_loaded_reviewer(lock, alloc):
    await _hold(lock, "alice", 2); await _hold(lock, "bob", 1)
    res = await alloc.auto_assign("i-1", ["alice", "bob", "carol"], AUTO, bank_id=BANK)
    assert res.claimed and res.reviewer_id == "carol"


@pytest.mark.asyncio
async def test_a_newly_logged_in_reviewer_receives_the_next_items_until_levelled(lock, alloc):
    await _hold(lock, "alice", 2); await _hold(lock, "bob", 2)
    for i in range(3):
        assert (await alloc.auto_assign(f"n-{i}", ["alice", "bob", "carol"], AUTO, bank_id=BANK)).claimed
    loads = await lock.reviewer_loads(["alice", "bob", "carol"])
    assert loads["carol"] >= 2 and max(loads.values()) <= 3          # carol is filled first; nobody passes the cap


@pytest.mark.asyncio
async def test_random_strategy_is_still_available(lock, alloc):
    cfg = {**AUTO, "allocation_strategy": "RANDOM"}
    res = await alloc.auto_assign("i-1", ["alice", "bob"], cfg, bank_id=BANK)
    assert res.claimed and res.reviewer_id in {"alice", "bob"}


# --- cap ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reviewers_at_the_cap_are_skipped(lock, alloc):
    await _hold(lock, "alice", 3)
    res = await alloc.auto_assign("i-1", ["alice", "bob"], AUTO, bank_id=BANK)
    assert res.reviewer_id == "bob"


@pytest.mark.asyncio
async def test_when_everyone_is_at_the_cap_the_item_stays_unassigned_with_a_reason(lock, alloc):
    await _hold(lock, "alice", 3); await _hold(lock, "bob", 3)
    res = await alloc.auto_assign("i-1", ["alice", "bob"], AUTO, bank_id=BANK)
    assert res.claimed is False and res.reason == "ALL_AT_CAPACITY"
    assert await lock.get_lock_holder("i-1") is None


@pytest.mark.asyncio
async def test_cap_zero_means_no_cap(lock, alloc):
    await _hold(lock, "alice", 50)
    res = await alloc.auto_assign("i-1", ["alice"], {**AUTO, "allocation_max_per_reviewer": 0}, bank_id=BANK)
    assert res.claimed


@pytest.mark.asyncio
async def test_an_item_close_to_its_deadline_ignores_the_cap(lock, alloc):
    await _hold(lock, "alice", 3)
    await lock.set_item_meta(BANK, "urgent", iet_deadline=time.time() + 10 * 60)     # inside the 30-minute margin
    res = await alloc.auto_assign("urgent", ["alice"], AUTO, bank_id=BANK)
    assert res.claimed and res.reviewer_id == "alice"


@pytest.mark.asyncio
async def test_no_reviewers_gives_a_reason_not_an_error(lock, alloc):
    res = await alloc.auto_assign("i-1", [], AUTO, bank_id=BANK)
    assert res.claimed is False and res.reason == "NO_ACTIVE_REVIEWERS"


# --- zones -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_assign_only_considers_reviewers_scoped_to_the_items_zone(lock, alloc):
    await lock.heartbeat_reviewer(BANK, "west", pu_ids=["WEST"])
    await lock.heartbeat_reviewer(BANK, "east", pu_ids=["EAST"])
    await lock.heartbeat_reviewer(BANK, "mgr", pu_ids=["ALL"])
    await lock.set_item_meta(BANK, "i-1", pu_id="WEST")
    await _hold(lock, "west", 2)                                    # west is busier, but east may not take it
    res = await alloc.auto_assign("i-1", ["west", "east", "mgr"], AUTO, bank_id=BANK)
    assert res.reviewer_id == "mgr"                                 # least loaded among the eligible (west, mgr)


@pytest.mark.asyncio
async def test_an_item_with_no_zone_can_go_to_anyone(lock, alloc):
    await lock.heartbeat_reviewer(BANK, "east", pu_ids=["EAST"])
    res = await alloc.auto_assign("i-1", ["east"], AUTO, bank_id=BANK)
    assert res.claimed


@pytest.mark.asyncio
async def test_no_eligible_reviewer_for_the_zone_leaves_it_unassigned(lock, alloc):
    await lock.heartbeat_reviewer(BANK, "east", pu_ids=["EAST"])
    await lock.set_item_meta(BANK, "i-1", pu_id="WEST")
    res = await alloc.auto_assign("i-1", ["east"], AUTO, bank_id=BANK)
    assert res.claimed is False and res.reason == "NO_ELIGIBLE_REVIEWER"


@pytest.mark.asyncio
async def test_claim_is_refused_outside_the_reviewers_zone(lock, alloc):
    await lock.set_item_meta(BANK, "i-1", pu_id="WEST")
    res = await alloc.claim("i-1", "east", AUTO, bank_id=BANK, reviewer_pus=["EAST"])
    assert res.claimed is False and res.reason == "PU_RESTRICTED"
    ok = await alloc.claim("i-1", "west", AUTO, bank_id=BANK, reviewer_pus=["WEST"])
    assert ok.claimed


@pytest.mark.asyncio
async def test_a_reviewer_with_all_zones_can_claim_anything(lock, alloc):
    await lock.set_item_meta(BANK, "i-1", pu_id="WEST")
    assert (await alloc.claim("i-1", "mgr", AUTO, bank_id=BANK, reviewer_pus=["ALL"])).claimed


# --- opening an item pins it -------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_assigned_items_are_movable_until_the_reviewer_opens_them(lock, alloc):
    await alloc.auto_assign("i-1", ["alice"], AUTO, bank_id=BANK)
    assert await lock.list_auto(BANK) == [("i-1", "alice")]
    await alloc.claim("i-1", "alice", AUTO, bank_id=BANK)            # re-entrant claim = opened it
    assert await lock.list_auto(BANK) == []


# --- admin assign ------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_assign_reassigns_and_pins(lock, alloc):
    await alloc.auto_assign("i-1", ["alice"], AUTO, bank_id=BANK)
    prev = await alloc.assign("i-1", "bob", AUTO, bank_id=BANK)
    assert prev == "alice" and await lock.get_lock_holder("i-1") == "bob"
    assert await lock.list_auto(BANK) == []


# --- rebalance ---------------------------------------------------------------------------------------------

async def _auto(lock, who, n):
    for i in range(n):
        iid = f"{who}-{i}"
        await lock.acquire_lock(iid, who, AUTO); await lock.mark_auto(BANK, iid)


@pytest.mark.asyncio
async def test_rebalance_moves_unopened_work_to_a_reviewer_who_just_logged_in(lock, alloc):
    await _auto(lock, "alice", 6)
    await lock.heartbeat_reviewer(BANK, "alice"); await lock.heartbeat_reviewer(BANK, "bob")
    res = await alloc.rebalance(BANK, AUTO)
    loads = await lock.reviewer_loads(["alice", "bob"])
    assert loads == {"alice": 3, "bob": 3} and len(res.moves) == 3


@pytest.mark.asyncio
async def test_rebalance_never_moves_an_item_the_reviewer_has_opened(lock, alloc):
    await _auto(lock, "alice", 4)
    for i in range(4):
        await lock.unmark_auto(BANK, f"alice-{i}")                    # all opened
    await lock.heartbeat_reviewer(BANK, "alice"); await lock.heartbeat_reviewer(BANK, "bob")
    res = await alloc.rebalance(BANK, AUTO)
    assert res.moves == [] and (await lock.reviewer_loads(["alice", "bob"])) == {"alice": 4, "bob": 0}


@pytest.mark.asyncio
async def test_rebalance_respects_the_move_cap(lock, alloc):
    await _auto(lock, "alice", 10)
    await lock.heartbeat_reviewer(BANK, "alice"); await lock.heartbeat_reviewer(BANK, "bob")
    res = await alloc.rebalance(BANK, {**AUTO, "allocation_rebalance_max_moves": 2})
    assert len(res.moves) == 2


@pytest.mark.asyncio
async def test_rebalance_respects_zones(lock, alloc):
    await _auto(lock, "west", 4)
    for i in range(4):
        await lock.set_item_meta(BANK, f"west-{i}", pu_id="WEST")
    await lock.heartbeat_reviewer(BANK, "west", pu_ids=["WEST"]); await lock.heartbeat_reviewer(BANK, "east", pu_ids=["EAST"])
    res = await alloc.rebalance(BANK, AUTO)
    assert res.moves == []                                            # east may not take WEST items


@pytest.mark.asyncio
async def test_rebalance_is_off_when_disabled(lock, alloc):
    await _auto(lock, "alice", 6)
    await lock.heartbeat_reviewer(BANK, "alice"); await lock.heartbeat_reviewer(BANK, "bob")
    res = await alloc.rebalance(BANK, {**AUTO, "allocation_rebalance_enabled": False})
    assert res.moves == []


@pytest.mark.asyncio
async def test_rebalance_with_one_reviewer_does_nothing(lock, alloc):
    await _auto(lock, "alice", 6)
    await lock.heartbeat_reviewer(BANK, "alice")
    assert (await alloc.rebalance(BANK, AUTO)).moves == []
