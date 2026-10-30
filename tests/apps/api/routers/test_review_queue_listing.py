"""GET /v1/cts/queue lists running review workflows without relying on Temporal custom search attributes.

The old query filtered on a BankId search attribute that nothing ever set or registered, so against a real Temporal the
reviewer queue was always empty. The bank is now taken from the workflow id (cts-humanreview-{bank}-{instrument})."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import BankType, Role

BANK = "kbl"


class _Temporal:
    def __init__(self, workflows):
        self.workflows, self.queries = workflows, []

    def list_workflows(self, query=None, page_size=None):
        self.queries.append(query)
        wfs = self.workflows

        async def gen():
            for w in wfs:
                yield w
        return gen()


def _wf(wid, **memo):
    # temporalio 1.7.1: memo on a listed workflow is an async method, not a dict
    async def _memo():
        return memo
    return SimpleNamespace(id=wid, memo=_memo, start_time=None)


def _client(workflows, smb_id=None):
    from apps.api.routers import cts_inward
    from apps.api.routers.cts_deps import get_current_user_context
    app = FastAPI(); app.include_router(cts_inward.router_v1)
    ctx = MagicMock(); ctx.role = Role.OPS_MANAGER; ctx.bank_id = BANK; ctx.user_id = "u"; ctx.bank_type = BankType.SB
    ctx.smb_id = smb_id; ctx.pu_ids = ["ALL"]
    if smb_id:                      # a sub-member user: their own bank id is the SMB; the items live under the sponsor
        ctx.bank_type = BankType.SMB; ctx.bank_id = smb_id; ctx.sponsor_bank_id = BANK
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.state.temporal_client = _Temporal(workflows)
    app.state.redis_cts = None
    cs = AsyncMock(); cs.get_cts_config.return_value = {}
    app.state.config_service = cs
    c = TestClient(app, raise_server_exceptions=False)
    c.temporal = app.state.temporal_client
    c.app = app
    return c


def test_the_query_does_not_use_a_custom_search_attribute():
    c = _client([])
    assert c.get("/v1/cts/queue").status_code == 200
    assert "BankId" not in c.temporal.queries[0] and "SmbId" not in c.temporal.queries[0]


def test_only_this_banks_review_workflows_are_listed():
    c = _client([_wf(f"cts-humanreview-{BANK}-A1", instrument_id="A1", iet_deadline=time.time() + 600),
                 _wf("cts-humanreview-otherbank-B1", instrument_id="B1"),
                 _wf(f"cts-humanreview-{BANK}x-C1", instrument_id="C1")])      # a bank whose name merely starts the same
    ids = [i["instrument_id"] for i in c.get("/v1/cts/queue").json()["items"]]
    assert ids == ["A1"]


def test_a_sub_member_user_sees_only_their_own_items():
    c = _client([_wf(f"cts-humanreview-{BANK}-A1", instrument_id="A1", smb_id="smb-1"),
                 _wf(f"cts-humanreview-{BANK}-A2", instrument_id="A2", smb_id="smb-2"),
                 _wf(f"cts-humanreview-{BANK}-A3", instrument_id="A3")], smb_id="smb-1")
    ids = [i["instrument_id"] for i in c.get("/v1/cts/queue").json()["items"]]
    assert ids == ["A1"]


def test_memo_fields_reach_the_queue_row():
    c = _client([_wf(f"cts-humanreview-{BANK}-A1", instrument_id="A1", account_display="****1234",
                     iet_deadline=1234567.0, pu_id="MUMBAI")])
    row = c.get("/v1/cts/queue").json()["items"][0]
    assert row["account_display"] == "****1234" and row["iet_deadline"] == 1234567.0 and row["pu_id"] == "MUMBAI"


def test_the_queue_says_which_items_the_caller_holds():
    import asyncio
    from modules.cts.allocation.lock_service import LockService
    from tests.modules.cts.allocation.fake_redis import FakeRedis
    c = _client([_wf(f"cts-humanreview-{BANK}-A1", instrument_id="A1"), _wf(f"cts-humanreview-{BANK}-A2", instrument_id="A2")])
    redis = FakeRedis()
    asyncio.run(LockService(redis).acquire_lock("A1", "u", {"allocation_lock_ttl_minutes": 10}))      # held by the caller
    asyncio.run(LockService(redis).acquire_lock("A2", "someone-else", {"allocation_lock_ttl_minutes": 10}))
    c.app.state.redis_cts = redis
    rows = {i["instrument_id"]: i for i in c.get("/v1/cts/queue").json()["items"]}
    assert rows["A1"]["assigned_to_me"] is True and rows["A2"]["assigned_to_me"] is False
