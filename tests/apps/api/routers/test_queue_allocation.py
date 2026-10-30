"""GET /v1/cts/queue: who is on the queue, who holds each item, deferred AUTO/HYBRID assignment, rebalancing on login,
and clearing-zone scoping for reviewers."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.cts.allocation.lock_service import LockService
from shared.auth.rbac import BankType, Role
from tests.modules.cts.allocation.fake_redis import FakeRedis

BANK = "kbl"
CFG = {"allocation_mode": "AUTO", "allocation_lock_ttl_minutes": 10, "hybrid_auto_assign_timeout_minutes": 5,
       "allocation_strategy": "LEAST_LOADED", "allocation_max_per_reviewer": 10, "allocation_urgent_margin_minutes": 30,
       "allocation_rebalance_enabled": True, "allocation_rebalance_interval_seconds": 60,
       "allocation_rebalance_max_moves": 20, "allocation_retry_seconds": 60}


def _ctx(user="alice", role="ops_reviewer", pu_ids=("ALL",)):
    c = MagicMock()
    c.role = Role[role.upper()]
    c.bank_id = BANK
    c.user_id = user
    c.bank_type = BankType.SB
    c.smb_id = None
    c.pu_ids = list(pu_ids)
    return c


class _Temporal:
    def __init__(self, items):
        self._items = items

    def list_workflows(self, query=None, page_size=None):
        async def gen():
            for iid, zone, deadline in self._items:
                yield SimpleNamespace(id=f"cts-humanreview-{BANK}-{iid}", start_time=None,
                                      memo={"instrument_id": iid, "pu_id": zone, "iet_deadline": deadline})
        return gen()


def _app(ctx, items, redis, cfg=None):
    from apps.api.routers import cts_inward
    from apps.api.routers.cts_deps import get_current_user_context, get_current_bank_id, get_current_user_id
    app = FastAPI()
    app.include_router(cts_inward.router_v1)
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: BANK
    app.dependency_overrides[get_current_user_id] = lambda: ctx.user_id
    app.state.temporal_client = _Temporal(items)
    app.state.redis_cts = redis
    cs = AsyncMock(); cs.get_cts_config.return_value = cfg or CFG
    app.state.config_service = cs
    app.state.db_pool_cts = None
    return app


def _get(app):
    return TestClient(app).get("/v1/cts/queue")


NOW = time.time()


def test_each_item_shows_who_holds_it():
    redis = FakeRedis()
    r = _get(_app(_ctx(), [("I-1", "WEST", NOW + 3600), ("I-2", "WEST", NOW + 7200)], redis))
    assert r.status_code == 200
    r2 = _get(_app(_ctx(), [("I-1", "WEST", NOW + 3600)], redis))
    assert r2.json()["items"][0]["assigned_to"] is None
    import asyncio
    asyncio.run(LockService(redis).acquire_lock("I-1", "bob", CFG))
    held = {i["instrument_id"]: i["assigned_to"] for i in _get(_app(_ctx(), [("I-1", "WEST", NOW + 3600)], redis)).json()["items"]}
    assert held == {"I-1": "bob"}


def test_polling_registers_the_reviewer_with_their_pus():
    import asyncio
    redis = FakeRedis()
    _get(_app(_ctx("alice", pu_ids=("WEST",)), [], redis))
    lock = LockService(redis)
    assert asyncio.run(lock.get_active_reviewers(BANK)) == ["alice"]
    assert asyncio.run(lock.get_reviewer_pus(BANK)) == {"alice": ["WEST"]}


def test_a_reviewer_scoped_to_a_pu_only_sees_that_pu_and_items_without_one():
    redis = FakeRedis()
    items = [("W", "WEST", NOW + 1), ("E", "EAST", NOW + 2), ("U", None, NOW + 3)]
    seen = {i["instrument_id"] for i in _get(_app(_ctx("w", pu_ids=("WEST",)), items, redis)).json()["items"]}
    assert seen == {"W", "U"}


def test_a_manager_and_an_all_zone_reviewer_see_everything():
    items = [("W", "WEST", NOW + 1), ("E", "EAST", NOW + 2)]
    for ctx in (_ctx("m", role="ops_manager", pu_ids=("WEST",)), _ctx("a", pu_ids=("ALL",))):
        assert {i["instrument_id"] for i in _get(_app(ctx, items, FakeRedis())).json()["items"]} == {"W", "E"}


def test_a_new_login_triggers_a_rebalance_that_gives_them_a_share():
    import asyncio
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.heartbeat_reviewer(BANK, "alice")
        for i in range(6):
            await lock.acquire_lock(f"A-{i}", "alice", CFG); await lock.mark_auto(BANK, f"A-{i}")
    asyncio.run(seed())
    _get(_app(_ctx("bob"), [], redis))                                    # bob logs in
    loads = asyncio.run(lock.reviewer_loads(["alice", "bob"]))
    assert loads == {"alice": 3, "bob": 3}


def test_rebalance_does_not_run_in_self_mode():
    import asyncio
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.heartbeat_reviewer(BANK, "alice")
        for i in range(6):
            await lock.acquire_lock(f"A-{i}", "alice", CFG); await lock.mark_auto(BANK, f"A-{i}")
    asyncio.run(seed())
    _get(_app(_ctx("bob"), [], redis, cfg={**CFG, "allocation_mode": "SELF"}))
    assert asyncio.run(lock.reviewer_loads(["alice", "bob"])) == {"alice": 6, "bob": 0}


def test_due_pending_items_are_assigned_in_auto_mode_too():
    import asyncio
    redis = FakeRedis(); lock = LockService(redis)
    asyncio.run(lock.add_hybrid_pending(BANK, "P-1", time.time() - 5))
    _get(_app(_ctx("alice"), [("P-1", "UNKNOWN", NOW + 3600)], redis))
    assert asyncio.run(lock.get_lock_holder("P-1")) == "alice"


def test_a_due_item_nobody_can_take_is_rescheduled_not_lost():
    import asyncio
    redis = FakeRedis(); lock = LockService(redis)
    cfg = {**CFG, "allocation_max_per_reviewer": 1}

    async def seed():
        await lock.acquire_lock("busy", "alice", cfg)
        await lock.add_hybrid_pending(BANK, "P-1", time.time() - 5)
    asyncio.run(seed())
    _get(_app(_ctx("alice"), [("P-1", "UNKNOWN", NOW + 3 * 3600)], redis, cfg=cfg))
    assert asyncio.run(lock.get_lock_holder("P-1")) is None
    assert redis.z[f"hybrid-pending:{BANK}"]["P-1"] > time.time()
