"""classify_bucket and sip_hold_check: facts are gathered best-effort; no failure may block or change a decision."""
from unittest.mock import AsyncMock

import pytest

from modules.cts.workflows.activities import classify_bucket as M
from modules.cts.workflows.activities.classify_bucket import (
    ClassifyBucketInput, SipHoldInput, classify_bucket, sip_hold_check,
)
from tests.modules.cts.allocation.fake_redis import FakeRedis
from tests.modules.cts.allocation.fake_subs_db import FakeSubsPool

CFG = {"bucket_priority": ["HVC", "CA", "IP", "FCC", "LVC"], "bucket_hvc_min_amount": 500000, "bucket_lvc_max_amount": 50000,
       "bucket_frequent_min_cheques": 5, "bucket_frequent_window_days": 30,
       "bucket_corporate_account_types": ["CORPORATE"], "bucket_institution_account_types": ["INSTITUTION"],
       "bucket_routing_enabled": True}


def _inp(**kw):
    base = dict(bank_id="kbl", instrument_id="I-1", account_number="1234567890", presented_amount=90_000.0,
                needs_human=True, cfg=CFG)
    base.update(kw)
    return ClassifyBucketInput(**base)


def _cbs(account_type=None, boom=False):
    cbs = AsyncMock()
    if boom:
        cbs.get_account_info.side_effect = RuntimeError("cbs down")
    else:
        cbs.get_account_info.return_value = type("A", (), {"account_type": account_type})()
    return cbs


class _Conn:
    def __init__(self, listed=(), recent=0, boom=False):
        self.listed, self.recent, self.boom = list(listed), recent, boom

    async def fetch(self, sql, *a):
        if self.boom:
            raise RuntimeError("db down")
        assert sql == M.SQL_LISTS
        return [{"bucket": b} for b in self.listed]

    async def fetchval(self, sql, *a):
        if self.boom:
            raise RuntimeError("db down")
        assert sql == M.SQL_RECENT
        return self.recent


@pytest.mark.asyncio
async def test_a_system_decision_needs_no_lookups_and_is_a_sip_bucket():
    cbs = _cbs()
    r = await classify_bucket(_inp(needs_human=False, system_decision="CONFIRM"), cbs_connector=cbs, db_conn=_Conn(), pepper="p")
    assert r.bucket == "SIP_SUCCESS"
    cbs.get_account_info.assert_not_called()


@pytest.mark.asyncio
async def test_corporate_account_type_from_cbs_makes_it_ca():
    r = await classify_bucket(_inp(), cbs_connector=_cbs("CORPORATE"), db_conn=_Conn(), pepper="p")
    assert r.bucket == "CA"


@pytest.mark.asyncio
async def test_a_bank_list_puts_the_account_in_ip():
    r = await classify_bucket(_inp(), cbs_connector=_cbs("INDIVIDUAL"), db_conn=_Conn(listed=["IP"]), pepper="p")
    assert r.bucket == "IP"


@pytest.mark.asyncio
async def test_many_recent_cheques_on_the_account_make_it_fcc():
    r = await classify_bucket(_inp(), cbs_connector=_cbs("INDIVIDUAL"), db_conn=_Conn(recent=8), pepper="p")
    assert r.bucket == "FCC"


@pytest.mark.asyncio
async def test_high_value_wins_by_priority_even_when_other_classes_match():
    r = await classify_bucket(_inp(presented_amount=900_000.0), cbs_connector=_cbs("CORPORATE"), db_conn=_Conn(recent=9), pepper="p")
    assert r.bucket == "HVC" and r.matched == ["HVC", "CA", "FCC"]


@pytest.mark.asyncio
async def test_low_amount_with_no_other_signal_is_lvc_and_nothing_known_is_hr():
    assert (await classify_bucket(_inp(presented_amount=3_000.0), cbs_connector=_cbs(), db_conn=_Conn(), pepper="p")).bucket == "LVC"
    assert (await classify_bucket(_inp(presented_amount=90_000.0), cbs_connector=_cbs(), db_conn=_Conn(), pepper="p")).bucket == "HR"


@pytest.mark.asyncio
async def test_failed_lookups_degrade_to_what_is_known_and_say_so():
    r = await classify_bucket(_inp(presented_amount=3_000.0), cbs_connector=_cbs(boom=True), db_conn=_Conn(boom=True), pepper="p")
    assert r.bucket == "LVC" and set(r.degraded) == {"account_type", "account_lists", "recent_cheques"}


@pytest.mark.asyncio
async def test_without_a_pepper_the_account_is_never_looked_up_in_the_database():
    conn = _Conn(recent=99, listed=["CA"])
    r = await classify_bucket(_inp(presented_amount=90_000.0), cbs_connector=_cbs(), db_conn=conn, pepper=None)
    assert r.bucket == "HR" and "recent_cheques" in r.degraded


# --- sip_hold_check ---------------------------------------------------------------------------------------------

async def _subscribe(pool, who, buckets):
    from modules.cts.allocation.subscriptions import SubscriptionStore
    await SubscriptionStore(pool, redis=None).set_reviewer_buckets("kbl", who, buckets, "boss")


@pytest.mark.asyncio
async def test_hold_when_a_connected_reviewer_is_logged_in():
    pool, redis = FakeSubsPool(), FakeRedis()
    await _subscribe(pool, "alice", ["SIP_SUCCESS"])
    from modules.cts.allocation.lock_service import LockService
    await LockService(redis).heartbeat_reviewer("kbl", "alice")
    r = await sip_hold_check(SipHoldInput(bank_id="kbl", bucket="SIP_SUCCESS", cfg=CFG), db_pool=pool, redis_client=redis)
    assert r.hold is True


@pytest.mark.asyncio
async def test_no_hold_when_connected_reviewers_are_all_offline():
    pool, redis = FakeSubsPool(), FakeRedis()
    await _subscribe(pool, "alice", ["SIP_SUCCESS"])
    r = await sip_hold_check(SipHoldInput(bank_id="kbl", bucket="SIP_SUCCESS", cfg=CFG), db_pool=pool, redis_client=redis)
    assert r.hold is False and r.reason == "NO_ACTIVE_SUBSCRIBER"


@pytest.mark.asyncio
async def test_no_hold_when_nobody_is_connected_to_the_sip_bucket():
    r = await sip_hold_check(SipHoldInput(bank_id="kbl", bucket="SIP_REJECT", cfg=CFG), db_pool=FakeSubsPool(), redis_client=FakeRedis())
    assert r.hold is False


@pytest.mark.asyncio
async def test_no_hold_when_routing_is_off_or_the_bucket_is_not_sip():
    pool, redis = FakeSubsPool(), FakeRedis()
    await _subscribe(pool, "alice", ["SIP_SUCCESS", "HVC"])
    from modules.cts.allocation.lock_service import LockService
    await LockService(redis).heartbeat_reviewer("kbl", "alice")
    off = await sip_hold_check(SipHoldInput(bank_id="kbl", bucket="SIP_SUCCESS", cfg={**CFG, "bucket_routing_enabled": False}), db_pool=pool, redis_client=redis)
    notsip = await sip_hold_check(SipHoldInput(bank_id="kbl", bucket="HVC", cfg=CFG), db_pool=pool, redis_client=redis)
    assert off.hold is False and notsip.hold is False


@pytest.mark.asyncio
async def test_any_failure_means_no_hold_so_filing_is_never_delayed_by_a_fault():
    class Boom:
        def acquire(self):
            raise RuntimeError("db down")
    r = await sip_hold_check(SipHoldInput(bank_id="kbl", bucket="SIP_SUCCESS", cfg=CFG), db_pool=Boom(), redis_client=FakeRedis())
    assert r.hold is False and r.reason == "CHECK_FAILED"
