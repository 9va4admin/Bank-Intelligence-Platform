"""GET /v1/cts/queue with buckets: each item shows its bucket, a reviewer sees only the buckets they are connected to
(plus MISC), stale items with nobody to take them overflow to MISC."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.cts.allocation.lock_service import LockService
from modules.cts.allocation.subscriptions import SubscriptionStore
from shared.auth.rbac import BankType, Role
from tests.modules.cts.allocation.fake_redis import FakeRedis
from tests.modules.cts.allocation.fake_subs_db import FakeSubsPool

BANK = "kbl"
CFG = {"allocation_mode": "SELF", "allocation_lock_ttl_minutes": 10, "bucket_routing_enabled": True,
       "bucket_overflow_after_minutes": 10, "allocation_retry_seconds": 60, "allocation_rebalance_enabled": True,
       "allocation_rebalance_interval_seconds": 60}
NOW = time.time()


def _ctx(user, role="ops_reviewer"):
    c = MagicMock()
    c.role = Role[role.upper()]; c.bank_id = BANK; c.user_id = user; c.bank_type = BankType.SB
    c.smb_id = None; c.clearing_zones = ["ALL"]
    return c


class _Temporal:
    def __init__(self, ids):
        self._ids = ids

    def list_workflows(self, query=None, page_size=None):
        async def gen():
            for i in self._ids:
                yield SimpleNamespace(id=f"cts-humanreview-{BANK}-{i}", start_time=None,
                                      memo={"instrument_id": i, "clearing_zone": "UNKNOWN", "iet_deadline": NOW + 3600})
        return gen()


def _client(ctx, ids, redis, pool, cfg=None):
    from apps.api.routers import cts_inward
    from apps.api.routers.cts_deps import get_current_user_context, get_current_bank_id, get_current_user_id
    app = FastAPI(); app.include_router(cts_inward.router_v1)
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: BANK
    app.dependency_overrides[get_current_user_id] = lambda: ctx.user_id
    app.state.temporal_client = _Temporal(ids); app.state.redis_cts = redis; app.state.db_pool_cts = pool
    cs = AsyncMock(); cs.get_cts_config.return_value = cfg or CFG
    app.state.config_service = cs
    return TestClient(app)


def _seed(redis, pool, items, subs=None):
    lock = LockService(redis); store = SubscriptionStore(pool, redis=None)

    async def go():
        for iid, bucket, extra in items:
            await lock.set_item_meta(BANK, iid, bucket=bucket, queued_at=extra.pop("queued_at", time.time()), **extra)
        for who, buckets in (subs or {}).items():
            await store.set_reviewer_buckets(BANK, who, buckets, "boss")
    asyncio.run(go())
    return lock


def _ids(resp):
    return {i["instrument_id"]: i for i in resp.json()["items"]}


def test_each_item_shows_its_bucket_and_where_it_came_from():
    redis, pool = FakeRedis(), FakeSubsPool()
    _seed(redis, pool, [("I-1", "HVC", {}), ("I-2", "MISC", {"origin_bucket": "CA"})])
    items = _ids(_client(_ctx("m", "ops_manager"), ["I-1", "I-2"], redis, pool).get("/v1/cts/queue"))
    assert items["I-1"]["bucket"] == "HVC" and items["I-1"]["origin_bucket"] is None
    assert items["I-2"]["bucket"] == "MISC" and items["I-2"]["origin_bucket"] == "CA"


def test_a_reviewer_sees_only_their_buckets_and_misc():
    redis, pool = FakeRedis(), FakeSubsPool()
    _seed(redis, pool, [("H", "HVC", {}), ("L", "LVC", {}), ("M", "MISC", {})], subs={"alice": ["HVC"]})
    seen = set(_ids(_client(_ctx("alice"), ["H", "L", "M"], redis, pool).get("/v1/cts/queue")))
    assert seen == {"H", "M"}


def test_a_manager_sees_every_bucket():
    redis, pool = FakeRedis(), FakeSubsPool()
    _seed(redis, pool, [("H", "HVC", {}), ("L", "LVC", {})])
    assert set(_ids(_client(_ctx("m", "ops_manager"), ["H", "L"], redis, pool).get("/v1/cts/queue"))) == {"H", "L"}


def test_with_routing_off_every_reviewer_sees_everything():
    redis, pool = FakeRedis(), FakeSubsPool()
    _seed(redis, pool, [("H", "HVC", {}), ("L", "LVC", {})], subs={"alice": ["HVC"]})
    cfg = {**CFG, "bucket_routing_enabled": False}
    assert set(_ids(_client(_ctx("alice"), ["H", "L"], redis, pool, cfg).get("/v1/cts/queue"))) == {"H", "L"}


def test_the_bucket_filter_narrows_the_list():
    redis, pool = FakeRedis(), FakeSubsPool()
    _seed(redis, pool, [("H", "HVC", {}), ("L", "LVC", {})])
    r = _client(_ctx("m", "ops_manager"), ["H", "L"], redis, pool).get("/v1/cts/queue?bucket=LVC")
    assert set(_ids(r)) == {"L"}


def test_a_stale_item_with_nobody_to_take_it_overflows_to_misc_on_the_next_poll():
    redis, pool = FakeRedis(), FakeSubsPool()
    _seed(redis, pool, [("old", "HVC", {"queued_at": time.time() - 15 * 60})], subs={"hv": ["HVC"]})   # hv not logged in
    r = _client(_ctx("m", "ops_manager"), ["old"], redis, pool).get("/v1/cts/queue")
    item = _ids(r)["old"]
    assert item["bucket"] == "MISC" and item["origin_bucket"] == "HVC"


def test_an_item_whose_bucket_has_a_logged_in_reviewer_stays_put():
    redis, pool = FakeRedis(), FakeSubsPool()
    _seed(redis, pool, [("old", "HVC", {"queued_at": time.time() - 15 * 60})], subs={"hv": ["HVC"]})
    asyncio.run(LockService(redis).heartbeat_reviewer(BANK, "hv"))
    item = _ids(_client(_ctx("m", "ops_manager"), ["old"], redis, pool).get("/v1/cts/queue"))["old"]
    assert item["bucket"] == "HVC"
