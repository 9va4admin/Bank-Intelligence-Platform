"""Review consumer: remember each item's zone and deadline, retry AUTO when nobody is free, and let urgent HYBRID
items skip the wait."""
import time
from unittest.mock import AsyncMock

import pytest

from modules.cts.allocation.lock_service import LockService
from modules.cts.consumers.human_review_consumer import handle_human_review_event
from shared.event_bus.schemas import KafkaEventEnvelope
from tests.modules.cts.allocation.fake_redis import FakeRedis

BANK = "kbl"


def _env(iid="I-1", pu_id=None, deadline=None):
    payload = {"instrument_id": iid, "workflow_id": f"wf-{iid}", "context_bundle": {}, "iet_deadline": deadline}
    if pu_id:
        payload["pu_id"] = pu_id
    return KafkaEventEnvelope(event_id="e", event_type="CTS_HUMAN_REVIEW_REQUIRED", bank_id=BANK,
                              schema_version="1.0", payload=payload)


def _cfg(**kw):
    base = {"allocation_mode": "AUTO", "allocation_lock_ttl_minutes": 10, "hybrid_auto_assign_timeout_minutes": 5,
            "allocation_strategy": "LEAST_LOADED", "allocation_max_per_reviewer": 3,
            "allocation_urgent_margin_minutes": 30, "allocation_retry_seconds": 60}
    base.update(kw)
    svc = AsyncMock()
    svc.get_cts_config.return_value = base
    return svc


async def _run(envelope, redis, cfg):
    await handle_human_review_event(envelope, immudb=AsyncMock(), db=None, redis=redis, config_svc=cfg)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["SELF", "AUTO", "HYBRID"])
async def test_zone_and_deadline_are_remembered_in_every_mode(mode):
    redis = FakeRedis()
    await _run(_env(pu_id="WEST", deadline=1234.0), redis, _cfg(allocation_mode=mode))
    meta = await LockService(redis).get_item_meta(BANK, "I-1")
    assert meta["pu_id"] == "WEST" and meta["iet_deadline"] == 1234.0


@pytest.mark.asyncio
async def test_auto_assigns_to_the_least_loaded_active_reviewer():
    redis = FakeRedis(); lock = LockService(redis)
    for who in ("alice", "bob"):
        await lock.heartbeat_reviewer(BANK, who)
    for i in range(2):
        await lock.acquire_lock(f"busy-{i}", "alice", {})
    await _run(_env(), redis, _cfg())
    assert await lock.get_lock_holder("I-1") == "bob"
    assert [i for i, _ in await lock.list_auto(BANK)] == ["I-1"]


@pytest.mark.asyncio
async def test_auto_with_nobody_logged_in_schedules_a_retry_instead_of_dropping_the_item():
    redis = FakeRedis(); lock = LockService(redis)
    before = time.time()
    await _run(_env(), redis, _cfg(allocation_retry_seconds=60))
    assert await lock.get_lock_holder("I-1") is None
    score = redis.z[f"hybrid-pending:{BANK}"]["I-1"]
    assert before + 55 <= score <= time.time() + 65


@pytest.mark.asyncio
async def test_auto_when_everyone_is_at_the_cap_retries_later():
    redis = FakeRedis(); lock = LockService(redis)
    await lock.heartbeat_reviewer(BANK, "alice")
    for i in range(3):
        await lock.acquire_lock(f"busy-{i}", "alice", {})
    await _run(_env(), redis, _cfg())
    assert "I-1" in redis.z[f"hybrid-pending:{BANK}"]


@pytest.mark.asyncio
async def test_hybrid_waits_the_configured_time_when_the_deadline_is_far():
    redis = FakeRedis(); now = time.time()
    await _run(_env(deadline=now + 3 * 3600), redis, _cfg(allocation_mode="HYBRID"))
    score = redis.z[f"hybrid-pending:{BANK}"]["I-1"]
    assert now + 5 * 60 - 5 <= score <= now + 5 * 60 + 5


@pytest.mark.asyncio
async def test_hybrid_urgent_item_is_assigned_straight_away():
    redis = FakeRedis(); now = time.time()
    await _run(_env(deadline=now + 10 * 60), redis, _cfg(allocation_mode="HYBRID"))   # inside the 30-minute margin
    assert redis.z[f"hybrid-pending:{BANK}"]["I-1"] <= now + 1


@pytest.mark.asyncio
async def test_hybrid_item_due_before_the_timeout_is_pulled_forward_to_the_margin():
    redis = FakeRedis(); now = time.time()
    # deadline in 33 min: margin starts in 3 min, earlier than the 5-minute wait
    await _run(_env(deadline=now + 33 * 60), redis, _cfg(allocation_mode="HYBRID"))
    score = redis.z[f"hybrid-pending:{BANK}"]["I-1"]
    assert now + 3 * 60 - 5 <= score <= now + 3 * 60 + 5


# --- buckets ------------------------------------------------------------------------------------------------

from modules.cts.allocation.subscriptions import SubscriptionStore  # noqa: E402
from tests.modules.cts.allocation.fake_subs_db import FakeSubsPool  # noqa: E402


def _env_b(iid="I-1", bucket=None, deadline=None):
    e = _env(iid, deadline=deadline)
    if bucket:
        e.payload["bucket"] = bucket
    return e


@pytest.mark.asyncio
async def test_the_items_bucket_and_arrival_time_are_remembered():
    redis = FakeRedis(); before = time.time()
    await _run(_env_b(bucket="HVC"), redis, _cfg(allocation_mode="SELF"))
    meta = await LockService(redis).get_item_meta(BANK, "I-1")
    assert meta["bucket"] == "HVC" and before <= meta["queued_at"] <= time.time()


@pytest.mark.asyncio
async def test_an_event_with_no_bucket_is_filed_under_hr():
    redis = FakeRedis()
    await _run(_env_b(), redis, _cfg(allocation_mode="SELF"))
    assert (await LockService(redis).get_item_meta(BANK, "I-1"))["bucket"] == "HR"


@pytest.mark.asyncio
async def test_auto_with_routing_on_assigns_only_within_the_bucket():
    redis = FakeRedis(); lock = LockService(redis); pool = FakeSubsPool()
    subs = SubscriptionStore(pool, redis=None)
    await subs.set_reviewer_buckets(BANK, "hv", ["HVC"], "boss"); await subs.set_reviewer_buckets(BANK, "lv", ["LVC"], "boss")
    for who in ("hv", "lv"):
        await lock.heartbeat_reviewer(BANK, who)
    await handle_human_review_event(_env_b(bucket="HVC"), immudb=AsyncMock(), db=pool, redis=redis,
                                    config_svc=_cfg(bucket_routing_enabled=True))
    assert await lock.get_lock_holder("I-1") == "hv"


@pytest.mark.asyncio
async def test_a_misc_item_is_not_retried_because_people_claim_it_themselves():
    redis = FakeRedis()
    await _run(_env_b(bucket="MISC"), redis, _cfg(bucket_routing_enabled=True))
    assert f"hybrid-pending:{BANK}" not in redis.z or "I-1" not in redis.z[f"hybrid-pending:{BANK}"]


# --- maker-checker: the checker-stage event -----------------------------------------------------------------------

def _val_env(iid="I-1", maker="maker", decision="CONFIRM"):
    e = _env(iid)
    e.payload.update({"bucket": "VAL", "stage": "VALIDATION", "maker_decision": decision, "maker_id": maker})
    return e


@pytest.mark.asyncio
async def test_a_validation_event_moves_the_item_to_val_and_remembers_the_maker_and_where_it_came_from():
    redis = FakeRedis(); lock = LockService(redis)
    await lock.set_item_meta(BANK, "I-1", pu_id="WEST", iet_deadline=999.0, bucket="HVC", queued_at=1.0)
    await lock.acquire_lock("I-1", "maker", {})
    await _run(_val_env(), redis, _cfg(allocation_mode="SELF"))
    meta = await lock.get_item_meta(BANK, "I-1")
    assert (meta["bucket"], meta["origin_bucket"], meta["maker_id"], meta["maker_decision"], meta["stage"]) == \
           ("VAL", "HVC", "maker", "CONFIRM", "VALIDATION")
    assert meta["pu_id"] == "WEST"                                     # what was known about the cheque is kept
    assert await lock.get_lock_holder("I-1") is None                  # the maker no longer holds it


@pytest.mark.asyncio
async def test_auto_mode_gives_the_validation_item_to_a_checker_never_the_maker():
    redis = FakeRedis(); lock = LockService(redis); pool = FakeSubsPool()
    subs = SubscriptionStore(pool, redis=None)
    for who in ("maker", "checker"):
        await subs.set_reviewer_buckets(BANK, who, ["VAL"], "boss"); await lock.heartbeat_reviewer(BANK, who)
    await lock.set_item_meta(BANK, "I-1", bucket="HVC", queued_at=1.0)
    await handle_human_review_event(_val_env(), immudb=AsyncMock(), db=pool, redis=redis,
                                    config_svc=_cfg(bucket_routing_enabled=True))
    assert await lock.get_lock_holder("I-1") == "checker"


@pytest.mark.asyncio
async def test_with_only_the_maker_online_the_item_waits_for_a_checker_with_a_retry():
    redis = FakeRedis(); lock = LockService(redis)
    await lock.heartbeat_reviewer(BANK, "maker")
    await lock.set_item_meta(BANK, "I-1", bucket="HVC", queued_at=1.0)
    await _run(_val_env(), redis, _cfg())
    assert await lock.get_lock_holder("I-1") is None
    assert "I-1" in redis.z[f"hybrid-pending:{BANK}"]
