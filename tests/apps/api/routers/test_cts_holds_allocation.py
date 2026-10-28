"""Claim, release and admin assign/reassign endpoints (zone scoping, pinning, audit)."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.cts.allocation.lock_service import LockService
from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext
from tests.modules.cts.allocation.fake_redis import FakeRedis

BANK = "kbl"
CFG = {"allocation_mode": "AUTO", "allocation_lock_ttl_minutes": 10}


def _ctx(user="alice", role=Role.OPS_REVIEWER, zones=("ALL",)):
    return UserContext(user_id=user, bank_id=BANK, bank_type=BankType.SB, role=role,
                       permission_level=PermissionLevel.EDIT, session_id="s", clearing_zones=list(zones))


def _app(ctx, redis, audit=None):
    from apps.api.routers.cts_holds import router_v1
    from apps.api.routers.cts_deps import get_current_user_context
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.state.redis_cts = redis
    cs = AsyncMock(); cs.get_cts_config.return_value = CFG
    app.state.config_service = cs
    app.state.audit_stream_writer = audit
    app.state.db_pool_cts = None
    return TestClient(app)


def run(coro):
    return asyncio.run(coro)


# --- claim --------------------------------------------------------------------------------------------------

def test_claim_inside_the_reviewers_zone_succeeds():
    redis = FakeRedis(); lock = LockService(redis)
    run(lock.set_item_meta(BANK, "I-1", zone="WEST"))
    r = _app(_ctx(zones=("WEST",)), redis).post("/v1/cts/review/I-1/claim")
    assert r.status_code == 200 and r.json()["claimed"] is True


def test_claim_outside_the_reviewers_zone_is_forbidden():
    redis = FakeRedis(); lock = LockService(redis)
    run(lock.set_item_meta(BANK, "I-1", zone="EAST"))
    r = _app(_ctx(zones=("WEST",)), redis).post("/v1/cts/review/I-1/claim")
    assert r.status_code == 403
    assert run(lock.get_lock_holder("I-1")) is None


def test_reclaiming_an_auto_assigned_item_pins_it_against_rebalancing():
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.acquire_lock("I-1", "alice", CFG); await lock.mark_auto(BANK, "I-1")
    run(seed())
    assert run(lock.list_auto(BANK)) == [("I-1", "alice")]
    _app(_ctx("alice"), redis).post("/v1/cts/review/I-1/claim")
    assert run(lock.list_auto(BANK)) == []


def test_unclaim_releases_and_clears_the_auto_mark():
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.acquire_lock("I-1", "alice", CFG); await lock.mark_auto(BANK, "I-1")
    run(seed())
    r = _app(_ctx("alice"), redis).delete("/v1/cts/review/I-1/claim")
    assert r.status_code == 200 and run(lock.get_lock_holder("I-1")) is None and run(lock.list_auto(BANK)) == []


# --- admin force release -------------------------------------------------------------------------------------

def test_admin_force_release_clears_the_auto_mark():
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.acquire_lock("I-1", "alice", CFG); await lock.mark_auto(BANK, "I-1")
    run(seed())
    r = _app(_ctx("boss", Role.OPS_MANAGER), redis).delete("/v1/cts/admin/review/I-1/claim")
    assert r.status_code == 200 and run(lock.list_auto(BANK)) == []


# --- admin assign --------------------------------------------------------------------------------------------

def _assign(client, iid="I-1", reviewer="bob"):
    return client.post(f"/v1/cts/admin/review/{iid}/assign", json={"reviewer_id": reviewer})


def test_admin_can_assign_an_unclaimed_item_to_an_active_reviewer():
    redis = FakeRedis(); lock = LockService(redis)
    run(lock.heartbeat_reviewer(BANK, "bob", zones=["ALL"]))
    audit = AsyncMock()
    r = _assign(_app(_ctx("boss", Role.OPS_MANAGER), redis, audit))
    assert r.status_code == 200 and r.json()["reviewer_id"] == "bob" and r.json()["previous_holder"] is None
    assert run(lock.get_lock_holder("I-1")) == "bob"
    ev = audit.call_args[0][0]
    assert ev.payload["action"] == "ADMIN_ASSIGN" and ev.payload["assigned_to"] == "bob" and ev.payload["assigned_by"] == "boss"


def test_admin_reassign_reports_the_previous_holder_and_pins_the_item():
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.heartbeat_reviewer(BANK, "bob", zones=["ALL"])
        await lock.acquire_lock("I-1", "alice", CFG); await lock.mark_auto(BANK, "I-1")
    run(seed())
    r = _assign(_app(_ctx("boss", Role.BANK_IT_ADMIN), redis))
    assert r.json()["previous_holder"] == "alice" and run(lock.get_lock_holder("I-1")) == "bob"
    assert run(lock.list_auto(BANK)) == []


def test_a_reviewer_cannot_assign_work():
    redis = FakeRedis()
    assert _assign(_app(_ctx("alice", Role.OPS_REVIEWER), redis)).status_code == 403


def test_assigning_to_someone_who_is_not_a_known_reviewer_is_not_found():
    redis = FakeRedis()
    assert _assign(_app(_ctx("boss", Role.OPS_MANAGER), redis), reviewer="ghost").status_code == 404


def test_admin_cannot_assign_across_a_clearing_zone_restriction():
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.heartbeat_reviewer(BANK, "bob", zones=["EAST"])
        await lock.set_item_meta(BANK, "I-1", zone="WEST")
    run(seed())
    r = _assign(_app(_ctx("boss", Role.OPS_MANAGER), redis))
    assert r.status_code == 409 and run(lock.get_lock_holder("I-1")) is None


# --- admin visibility ---------------------------------------------------------------------------------------

def test_active_reviewers_show_zones_and_current_load():
    redis = FakeRedis(); lock = LockService(redis)

    async def seed():
        await lock.heartbeat_reviewer(BANK, "alice", zones=["WEST"])
        await lock.heartbeat_reviewer(BANK, "bob", zones=["ALL"])
        await lock.acquire_lock("I-1", "alice", CFG); await lock.acquire_lock("I-2", "alice", CFG)
    run(seed())
    body = _app(_ctx("boss", Role.OPS_MANAGER), redis).get("/v1/cts/allocation/reviewers").json()
    rows = {r["reviewer_id"]: r for r in body["active_reviewers"]}
    assert rows["alice"]["zones"] == ["WEST"] and rows["alice"]["load"] == 2 and rows["bob"]["load"] == 0


def test_allocation_status_reports_the_active_mode_and_limits():
    redis = FakeRedis()
    app = _app(_ctx("boss", Role.OPS_MANAGER), redis)
    app.app.state.config_service.get_cts_config.return_value = {
        **CFG, "allocation_strategy": "LEAST_LOADED", "allocation_max_per_reviewer": 7}
    body = app.get("/v1/cts/allocation/status").json()
    assert body["allocation_mode"] == "AUTO" and body["allocation_strategy"] == "LEAST_LOADED" and body["max_per_reviewer"] == 7
