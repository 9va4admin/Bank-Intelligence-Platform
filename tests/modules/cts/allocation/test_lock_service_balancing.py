"""LockService: atomic claim, reviewer load, zones, auto-assignment index, transfer, admin assign."""
import pytest

from modules.cts.allocation.lock_service import LockService
from tests.modules.cts.allocation.fake_redis import FakeRedis

CFG = {"allocation_lock_ttl_minutes": 10}
BANK = "kbl"


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def svc(redis):
    return LockService(redis_client=redis)


# --- claim is atomic ---------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_uses_set_if_absent_so_two_racing_reviewers_cannot_both_win(redis, svc):
    class Racy(FakeRedis):
        async def get(self, key):          # both reviewers read "free" before either writes
            return None
    r = Racy()
    s = LockService(redis_client=r)
    first = await s.acquire_lock("i-1", "alice", CFG)
    second = await s.acquire_lock("i-1", "bob", CFG)
    assert (first, second) == (True, False)
    assert r.kv["lock:cts:i-1"] == "alice"


# --- reviewer load -----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reviewer_loads_counts_live_locks_per_reviewer(svc):
    for i, who in enumerate(["alice", "alice", "bob"]):
        await svc.acquire_lock(f"i-{i}", who, CFG)
    loads = await svc.reviewer_loads(["alice", "bob", "carol"])
    assert loads == {"alice": 2, "bob": 1, "carol": 0}


@pytest.mark.asyncio
async def test_expired_locks_do_not_count_as_load(redis, svc):
    await svc.acquire_lock("i-1", "alice", CFG)
    redis.now = lambda: 10**12                       # far future: every lock has lapsed
    assert await svc.reviewer_loads(["alice"]) == {"alice": 0}


# --- heartbeat and zones -----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_reports_whether_the_reviewer_is_new_to_the_pool(svc):
    assert await svc.heartbeat_reviewer(BANK, "alice", zones=["WEST"]) is True
    assert await svc.heartbeat_reviewer(BANK, "alice", zones=["WEST"]) is False
    assert await svc.get_active_reviewers(BANK) == ["alice"]


@pytest.mark.asyncio
async def test_reviewer_zones_are_recorded_with_the_heartbeat(svc):
    await svc.heartbeat_reviewer(BANK, "alice", zones=["WEST", "EAST"])
    await svc.heartbeat_reviewer(BANK, "bob")
    zones = await svc.get_reviewer_zones(BANK)
    assert zones["alice"] == ["WEST", "EAST"] and zones.get("bob", []) == []


# --- item metadata and the auto-assignment index -------------------------------------------------------------

@pytest.mark.asyncio
async def test_item_meta_round_trips_zone_and_deadline(svc):
    await svc.set_item_meta(BANK, "i-1", zone="WEST", iet_deadline=1234.5)
    assert await svc.get_item_meta(BANK, "i-1") == {"zone": "WEST", "iet_deadline": 1234.5}
    assert await svc.get_item_meta(BANK, "unknown") == {}


@pytest.mark.asyncio
async def test_list_auto_returns_unopened_auto_assigned_items_with_their_holder(svc):
    await svc.acquire_lock("i-1", "alice", CFG)
    await svc.mark_auto(BANK, "i-1")
    assert await svc.list_auto(BANK) == [("i-1", "alice")]
    await svc.unmark_auto(BANK, "i-1")               # the reviewer opened it
    assert await svc.list_auto(BANK) == []


@pytest.mark.asyncio
async def test_list_auto_drops_items_whose_lock_has_lapsed(redis, svc):
    await svc.acquire_lock("i-1", "alice", CFG)
    await svc.mark_auto(BANK, "i-1")
    redis.now = lambda: 10**12
    assert await svc.list_auto(BANK) == []


# --- transfer (rebalance) ----------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transfer_moves_a_lock_only_from_its_current_holder(svc):
    await svc.acquire_lock("i-1", "alice", CFG)
    assert await svc.transfer("i-1", "alice", "bob", CFG) is True
    assert await svc.get_lock_holder("i-1") == "bob"
    assert await svc.transfer("i-1", "alice", "carol", CFG) is False      # alice no longer holds it
    assert await svc.get_lock_holder("i-1") == "bob"


@pytest.mark.asyncio
async def test_transfer_of_a_released_item_does_not_resurrect_it(svc):
    assert await svc.transfer("gone", "alice", "bob", CFG) is False
    assert await svc.get_lock_holder("gone") is None


# --- admin assign ------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_force_assign_overrides_the_current_holder_and_reports_who_it_was(svc):
    await svc.acquire_lock("i-1", "alice", CFG)
    await svc.mark_auto(BANK, "i-1")
    previous = await svc.force_assign("i-1", "bob", CFG, bank_id=BANK)
    assert previous == "alice" and await svc.get_lock_holder("i-1") == "bob"
    assert await svc.list_auto(BANK) == []            # an admin assignment is never moved by the rebalancer


@pytest.mark.asyncio
async def test_force_assign_on_an_unclaimed_item_has_no_previous_holder(svc):
    assert await svc.force_assign("i-2", "bob", CFG, bank_id=BANK) is None
    assert await svc.get_lock_holder("i-2") == "bob"


# --- rebalance gate ----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebalance_gate_allows_one_run_per_interval(svc):
    assert await svc.try_rebalance_gate(BANK, 60) is True
    assert await svc.try_rebalance_gate(BANK, 60) is False


# --- release cleans up the index ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_release_and_force_release_clear_the_auto_mark(svc):
    await svc.acquire_lock("i-1", "alice", CFG); await svc.mark_auto(BANK, "i-1")
    await svc.release_lock("i-1", "alice", bank_id=BANK)
    assert await svc.list_auto(BANK) == []
    await svc.acquire_lock("i-2", "bob", CFG); await svc.mark_auto(BANK, "i-2")
    await svc.force_release("i-2", bank_id=BANK)
    assert await svc.list_auto(BANK) == []


@pytest.mark.asyncio
async def test_forget_item_removes_meta_pending_and_auto_mark(svc):
    await svc.set_item_meta(BANK, "i-1", zone="WEST")
    await svc.add_hybrid_pending(BANK, "i-1", 1.0)
    await svc.forget_item(BANK, "i-1")
    assert await svc.get_item_meta(BANK, "i-1") == {}
    assert await svc.pop_due_hybrid_pending(BANK) == []


@pytest.mark.asyncio
async def test_get_lock_holders_returns_the_holder_of_each_item_or_none(svc):
    await svc.acquire_lock("i-1", "alice", CFG)
    assert await svc.get_lock_holders(["i-1", "i-2"]) == {"i-1": "alice", "i-2": None}
    assert await svc.get_lock_holders([]) == {}
