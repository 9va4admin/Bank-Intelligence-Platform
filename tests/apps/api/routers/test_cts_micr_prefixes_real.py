"""GET /v1/cts/admin/micr-prefixes on the real dev YugabyteDB: the list is built from the columns the table really has, joined to the sub-member bank for its name and IFSC;
a failing query is an error (503), never a silently empty list. Skipped when the database is not reachable."""
import asyncio
import socket
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _scenario(fn, *, break_pool=False):
    async def go():
        import asyncpg
        from apps.api.routers import cts_admin_ops
        from apps.api.routers.cts_deps import get_current_bank_id, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"mp-{uuid.uuid4().hex[:8]}"
        await pool.execute("INSERT INTO platform.banks (bank_id, bank_name, bank_code, ifsc_prefix) VALUES ($1,'Sponsor Fixture',$1,'FIXT')", bank)
        await pool.execute("INSERT INTO cts.sub_member_banks (sub_member_id, bank_id, bank_name, sponsor_bank_id, micr_prefix, ifsc_prefix, branch_manager_email_enc, ops_head_email_enc, gm_email_enc) "
                           "VALUES ($1,$2,'Rampur Cooperative',$2,'400','RAMP',$3,$3,$3)", f"smb-{bank}", bank, b"x")
        today = date.today()
        await pool.execute("INSERT INTO cts.micr_prefix_routing (bank_id, micr_prefix, sub_member_id, created_by, effective_from) VALUES ($1,'400',$2,'t',$3)", bank, f"smb-{bank}", today - timedelta(days=5))
        await pool.execute("INSERT INTO cts.micr_prefix_routing (bank_id, micr_prefix, sub_member_id, created_by, effective_from, effective_to) VALUES ($1,'500',$2,'t',$3,$4)",
                           bank, f"smb-{bank}", today - timedelta(days=30), today - timedelta(days=1))
        ctx = MagicMock(spec=UserContext)
        ctx.role, ctx.bank_id, ctx.user_id = Role.OPS_MANAGER, bank, "u"
        app = FastAPI()
        app.include_router(cts_admin_ops.router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: ctx
        app.dependency_overrides[get_current_bank_id] = lambda: bank
        if break_pool:
            class Broken:
                async def fetch(self, *a, **k):
                    raise RuntimeError("relation does not exist")
            app.state.db_pool_cts = Broken()
        else:
            app.state.db_pool_cts = pool
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank)
        finally:
            await pool.execute("DELETE FROM cts.micr_prefix_routing WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM cts.sub_member_banks WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM platform.banks WHERE bank_id=$1", bank)
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


def test_the_list_shows_each_prefix_with_the_sub_member_name_ifsc_and_whether_it_is_in_force():
    async def fn(client, bank):
        r = await client.get("/v1/cts/admin/micr-prefixes")
        assert r.status_code == 200, r.text
        body = r.json()
        by = {i["micr_prefix"]: i for i in body["items"]}
        assert body["total"] == 2 and set(by) == {"400", "500"}
        assert by["400"]["bank_name"] == "Rampur Cooperative" and by["400"]["bank_ifsc"] == "RAMP" and by["400"]["active"] is True
        assert by["500"]["active"] is False                                   # its end date has passed
        assert by["400"]["prefix_id"] and by["400"]["updated_at"]
    _scenario(fn)


def test_search_matches_the_prefix_or_the_bank_name():
    async def fn(client, bank):
        assert [i["micr_prefix"] for i in (await client.get("/v1/cts/admin/micr-prefixes?search=500")).json()["items"]] == ["500"]
        assert len((await client.get("/v1/cts/admin/micr-prefixes?search=rampur")).json()["items"]) == 2
        assert (await client.get("/v1/cts/admin/micr-prefixes?search=zzz")).json()["items"] == []
    _scenario(fn)


def test_a_failing_query_is_a_503_with_a_message_not_an_empty_list():
    async def fn(client, bank):
        r = await client.get("/v1/cts/admin/micr-prefixes")
        assert r.status_code == 503 and r.json()["detail"]
    _scenario(fn, break_pool=True)
