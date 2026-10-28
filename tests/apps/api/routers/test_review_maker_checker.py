"""POST /review/{id}/decide (the maker) and /review/{id}/validate (the checker): roles, claim ownership, four-eyes,
and what is recorded when."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.cts.allocation.lock_service import LockService
from shared.auth.rbac import BankType, Role
from tests.modules.cts.allocation.fake_redis import FakeRedis

BANK = "kbl"
CFG_ON = {"allocation_mode": "AUTO", "allocation_lock_ttl_minutes": 10, "maker_checker_enabled": True}
CFG_OFF = {**CFG_ON, "maker_checker_enabled": False}


class _Handle:
    def __init__(self, log, wid):
        self.log, self.wid = log, wid

    async def signal(self, fn, arg):
        self.log.append((self.wid, getattr(fn, "__name__", str(fn)), arg))


class _Temporal:
    def __init__(self):
        self.signals = []

    def get_workflow_handle(self, wid):
        return _Handle(self.signals, wid)


class _FakePool:
    def acquire(self):
        class A:
            async def __aenter__(s): return object()
            async def __aexit__(s, *x): return False
        return A()


def _ctx(user, role="ops_reviewer"):
    c = MagicMock()
    c.role = Role[role.upper()]; c.bank_id = BANK; c.user_id = user; c.bank_type = BankType.SB
    c.smb_id = None; c.clearing_zones = ["ALL"]
    return c


def _client(user, redis, cfg, role="ops_reviewer"):
    from apps.api.routers import cts_inward
    from apps.api.routers.cts_deps import get_current_user_context, get_current_bank_id, get_current_user_id
    app = FastAPI(); app.include_router(cts_inward.router_v1)
    ctx = _ctx(user, role)
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: BANK
    app.dependency_overrides[get_current_user_id] = lambda: user
    app.state.temporal_client = _Temporal()
    app.state.redis_cts = redis
    app.state.db_pool_cts = _FakePool()       # only used for the (patched) durable record
    cs = AsyncMock(); cs.get_cts_config.return_value = cfg
    app.state.config_service = cs
    c = TestClient(app, raise_server_exceptions=False)
    c.app_state = app.state
    return c


def run(coro):
    return asyncio.run(coro)


def _meta(redis, iid="I-1", **kw):
    run(LockService(redis).set_item_meta(BANK, iid, bucket=kw.pop("bucket", "HVC"), queued_at=time.time()))
    if kw:
        run(LockService(redis).update_item_meta(BANK, iid, **kw))


@pytest.fixture(autouse=True)
def _patch_durable():
    with patch("apps.api.routers.cts_inward.decide_by_instrument", new_callable=AsyncMock) as d:
        d.return_value = True
        yield d


def _decide(c, action="CONFIRM", reason="looks right", path="decide", iid="I-1"):
    return c.post(f"/v1/cts/review/{iid}/{path}", json={"action": action, "reason": reason})


# --- the maker (decide) ----------------------------------------------------------------------------------------------

def test_with_maker_checker_on_a_makers_decision_is_signalled_but_not_recorded_as_final(_patch_durable):
    redis = FakeRedis(); _meta(redis)
    c = _client("maker", redis, CFG_ON)
    r = _decide(c)
    assert r.status_code == 200 and r.json()["signal_sent"] is True
    assert [s[1] for s in c.app_state.temporal_client.signals] == ["receive_decision"]
    _patch_durable.assert_not_called()


def test_with_maker_checker_off_a_decision_is_final_as_before(_patch_durable):
    redis = FakeRedis(); _meta(redis)
    c = _client("maker", redis, CFG_OFF)
    assert _decide(c).status_code == 200
    _patch_durable.assert_awaited_once()


def test_a_system_decided_sip_item_is_final_on_the_first_human_decision_even_with_maker_checker_on(_patch_durable):
    redis = FakeRedis(); _meta(redis, bucket="SIP_SUCCESS", system_decision="CONFIRM")
    assert _decide(_client("alice", redis, CFG_ON)).status_code == 200
    _patch_durable.assert_awaited_once()


def test_an_item_already_awaiting_a_checker_must_use_validate_not_decide():
    redis = FakeRedis(); _meta(redis, bucket="VAL", stage="VALIDATION", maker_id="maker")
    r = _decide(_client("checker", redis, CFG_ON))
    assert r.status_code == 409 and "validate" in r.json()["detail"].lower()


def test_a_reviewer_cannot_decide_an_item_another_reviewer_holds():
    redis = FakeRedis(); _meta(redis)
    run(LockService(redis).acquire_lock("I-1", "someone-else", CFG_ON))
    r = _decide(_client("maker", redis, CFG_ON))
    assert r.status_code == 409 and "someone-else" not in r.text            # who holds it is not revealed to a stranger


def test_the_holder_can_decide_and_an_unclaimed_item_is_taken_by_the_decider():
    redis = FakeRedis(); _meta(redis); lock = LockService(redis)
    run(lock.acquire_lock("I-1", "maker", CFG_ON))
    assert _decide(_client("maker", redis, CFG_ON)).status_code == 200
    redis2 = FakeRedis(); _meta(redis2, iid="I-2")
    assert _decide(_client("maker", redis2, CFG_ON), iid="I-2").status_code == 200


@pytest.mark.parametrize("role", ["compliance_officer", "fraud_analyst", "rbi_examiner"])
def test_only_reviewers_and_managers_may_decide(role):
    redis = FakeRedis(); _meta(redis)
    assert _decide(_client("x", redis, CFG_ON, role=role)).status_code == 403


def test_a_reason_is_required():
    redis = FakeRedis(); _meta(redis)
    assert _decide(_client("maker", redis, CFG_ON), reason="  ").status_code == 422


# --- the checker (validate) ------------------------------------------------------------------------------------------

def _awaiting_checker(redis, maker="maker", iid="I-1"):
    _meta(redis, iid=iid, bucket="VAL", stage="VALIDATION", maker_id=maker, maker_decision="CONFIRM", origin_bucket="HVC")


def test_a_checker_confirms_or_overrules_and_it_is_recorded_as_the_final_decision(_patch_durable):
    redis = FakeRedis(); _awaiting_checker(redis)
    c = _client("checker", redis, CFG_ON)
    r = _decide(c, action="RETURN", path="validate")
    assert r.status_code == 200
    wid, name, decision = c.app_state.temporal_client.signals[0]
    assert name == "receive_checker_decision" and decision.action == "RETURN" and decision.reviewer_id == "checker"
    _patch_durable.assert_awaited_once()
    assert _patch_durable.call_args.kwargs["reviewer_id"] == "checker" and _patch_durable.call_args.kwargs["decision"] == "RETURN"


def test_the_maker_cannot_validate_their_own_decision():
    redis = FakeRedis(); _awaiting_checker(redis, maker="same")
    r = _decide(_client("same", redis, CFG_ON), path="validate")
    assert r.status_code == 403 and "different person" in r.json()["detail"]


def test_validate_needs_an_item_that_is_awaiting_a_checker():
    redis = FakeRedis(); _meta(redis)                                         # still in the maker's bucket
    assert _decide(_client("checker", redis, CFG_ON), path="validate").status_code == 409


def test_validate_is_refused_when_maker_checker_is_off():
    redis = FakeRedis(); _awaiting_checker(redis)
    assert _decide(_client("checker", redis, CFG_OFF), path="validate").status_code == 409


def test_another_checker_holding_the_item_blocks_validate():
    redis = FakeRedis(); _awaiting_checker(redis)
    run(LockService(redis).acquire_lock("I-1", "checker-2", CFG_ON))
    assert _decide(_client("checker-1", redis, CFG_ON), path="validate").status_code == 409


@pytest.mark.parametrize("role", ["compliance_officer", "rbi_examiner"])
def test_only_reviewers_and_managers_may_validate(role):
    redis = FakeRedis(); _awaiting_checker(redis)
    assert _decide(_client("x", redis, CFG_ON, role=role), path="validate").status_code == 403


def test_validate_needs_a_reason():
    redis = FakeRedis(); _awaiting_checker(redis)
    assert _decide(_client("checker", redis, CFG_ON), reason="", path="validate").status_code == 422


def test_after_validation_the_lock_and_allocation_records_are_cleared():
    redis = FakeRedis(); _awaiting_checker(redis); lock = LockService(redis)
    run(lock.acquire_lock("I-1", "checker", CFG_ON))
    _decide(_client("checker", redis, CFG_ON), path="validate")
    assert run(lock.get_lock_holder("I-1")) is None and run(lock.get_item_meta(BANK, "I-1")) == {}


def test_after_a_final_decision_without_maker_checker_the_allocation_records_are_cleared_too():
    redis = FakeRedis(); _meta(redis); lock = LockService(redis)
    run(lock.acquire_lock("I-1", "maker", CFG_OFF))
    _decide(_client("maker", redis, CFG_OFF))
    assert run(lock.get_lock_holder("I-1")) is None and run(lock.get_item_meta(BANK, "I-1")) == {}


def test_after_a_makers_decision_the_item_stays_so_the_checker_stage_can_find_it():
    redis = FakeRedis(); _meta(redis); lock = LockService(redis)
    run(lock.acquire_lock("I-1", "maker", CFG_ON))
    _decide(_client("maker", redis, CFG_ON))
    assert run(lock.get_item_meta(BANK, "I-1")) != {}
