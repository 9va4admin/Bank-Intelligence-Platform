"""Admin configuration: the bank-maintained account lists that put an account in the CA (corporate) or IP (institution)
bucket. Accounts are stored as keyed hashes plus the last four digits; raw numbers are never stored, returned or audited."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext
from shared.utils.pii_crypto import hash_account_number

BANK = "kbl"
PEPPER = "test-pepper"


class _Conn:
    def __init__(self, rows):
        self.rows = rows            # dict: (bank, bucket, hash) -> {"last4", "added_by", "added_at"}

    async def execute(self, sql, *a):
        from apps.api.routers import cts_bucket_lists as M
        if sql == M.SQL_INSERT:
            bank, bucket, h, last4, by = a
            if (bank, bucket, h) in self.rows:
                return "INSERT 0 0"
            self.rows[(bank, bucket, h)] = {"last4": last4, "added_by": by, "added_at": "2026-10-28T10:00:00+00:00"}
            return "INSERT 0 1"
        if sql == M.SQL_DELETE:
            bank, bucket, h = a
            return "DELETE 1" if self.rows.pop((bank, bucket, h), None) else "DELETE 0"
        raise AssertionError(sql[:50])

    async def fetchval(self, sql, *a):
        from apps.api.routers import cts_bucket_lists as M
        assert sql == M.SQL_COUNT
        return sum(1 for (b, bk, _h) in self.rows if b == a[0] and bk == a[1])

    async def fetch(self, sql, *a):
        from apps.api.routers import cts_bucket_lists as M
        assert sql == M.SQL_LIST
        bank, bucket, after, limit = a
        items = sorted(((h, v) for (b, bk, h), v in self.rows.items() if b == bank and bk == bucket and h > after))
        return [{"account_hash": h, "account_last4": v["last4"], "added_by": v["added_by"], "added_at": v["added_at"]}
                for h, v in items[:limit]]

    def transaction(self):
        class T:
            async def __aenter__(s): return s
            async def __aexit__(s, *x): return False
        return T()


class _Pool:
    def __init__(self):
        self.rows = {}

    def acquire(self):
        conn = _Conn(self.rows)

        class A:
            async def __aenter__(s): return conn
            async def __aexit__(s, *x): return False
        return A()


def _client(role=Role.OPS_MANAGER, pool=None, audit=None, pepper=PEPPER):
    from apps.api.routers.cts_bucket_lists import router_v1
    from apps.api.routers.cts_deps import get_current_user_context
    app = FastAPI()
    app.include_router(router_v1)
    ctx = UserContext(user_id="boss", bank_id=BANK, bank_type=BankType.SB, role=role,
                      permission_level=PermissionLevel.EDIT, session_id="s")
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.state.db_pool_cts = pool if pool is not None else _Pool()
    app.state.audit_stream_writer = audit
    patcher = patch("apps.api.routers.cts_bucket_lists.config_service")
    cs = patcher.start()
    if pepper is None:
        cs.get_secret = AsyncMock(side_effect=RuntimeError("no pepper"))
    else:
        cs.get_secret = AsyncMock(return_value=pepper)
    c = TestClient(app, raise_server_exceptions=False)
    c._patcher = patcher
    return c


@pytest.fixture(autouse=True)
def _stop_patches():
    yield
    patch.stopall()


def test_adding_accounts_stores_only_hashes_and_last_four():
    pool = _Pool()
    r = _client(pool=pool).post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": ["1234567890", "9876543210"]})
    assert r.status_code == 200 and r.json() == {"bucket": "CA", "added": 2, "already_present": 0, "invalid": []}
    h = hash_account_number("1234567890", BANK, PEPPER)
    assert pool.rows[(BANK, "CA", h)]["last4"] == "7890" and pool.rows[(BANK, "CA", h)]["added_by"] == "boss"
    assert all("1234567890" not in str(k) + str(v) for k, v in pool.rows.items())


def test_adding_the_same_account_again_is_reported_not_duplicated():
    pool = _Pool()
    c = _client(pool=pool)
    c.post("/v1/cts/admin/bucket-accounts/IP", json={"account_numbers": ["1234567890"]})
    r = c.post("/v1/cts/admin/bucket-accounts/IP", json={"account_numbers": ["1234567890", "5555566666"]})
    assert r.json()["added"] == 1 and r.json()["already_present"] == 1 and len(pool.rows) == 2


def test_the_same_account_can_be_on_both_lists():
    pool = _Pool()
    c = _client(pool=pool)
    c.post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": ["1234567890"]})
    assert c.post("/v1/cts/admin/bucket-accounts/IP", json={"account_numbers": ["1234567890"]}).json()["added"] == 1


def test_malformed_account_numbers_are_reported_by_last_digits_only_and_not_stored():
    pool = _Pool()
    r = _client(pool=pool).post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": ["12", "12 34@56", "1234567890"]})
    body = r.json()
    assert body["added"] == 1 and len(body["invalid"]) == 2 and len(pool.rows) == 1
    assert all("12 34@56" not in str(i) for i in body["invalid"])


def test_only_ca_and_ip_have_lists():
    for bad in ("HVC", "MISC", "ca"):
        r = _client().post(f"/v1/cts/admin/bucket-accounts/{bad}", json={"account_numbers": ["1234567890"]})
        assert r.status_code == 422


def test_a_single_call_is_limited():
    r = _client().post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": ["1234567890"] * 5001})
    assert r.status_code == 422


def test_listing_shows_last_four_total_and_pages_through_the_list():
    pool = _Pool()
    c = _client(pool=pool)
    c.post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": [f"10000000{n:02d}" for n in range(1, 8)]})
    page1 = c.get("/v1/cts/admin/bucket-accounts/CA?limit=3").json()
    assert page1["total"] == 7 and len(page1["items"]) == 3 and page1["next_cursor"]
    assert set(page1["items"][0]) == {"account_hash", "account_last4", "added_by", "added_at"}
    page2 = c.get(f"/v1/cts/admin/bucket-accounts/CA?limit=10&cursor={page1['next_cursor']}").json()
    assert len(page2["items"]) == 4 and page2["next_cursor"] is None
    seen = [i["account_hash"] for i in page1["items"] + page2["items"]]
    assert len(set(seen)) == 7


def test_an_account_can_be_removed_by_its_hash():
    pool = _Pool()
    c = _client(pool=pool)
    c.post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": ["1234567890"]})
    h = hash_account_number("1234567890", BANK, PEPPER)
    assert c.delete(f"/v1/cts/admin/bucket-accounts/CA/{h}").status_code == 200
    assert pool.rows == {}
    assert c.delete(f"/v1/cts/admin/bucket-accounts/CA/{h}").status_code == 404


def test_reviewers_cannot_manage_the_lists_but_managers_and_admins_can():
    assert _client(Role.OPS_REVIEWER).get("/v1/cts/admin/bucket-accounts/CA").status_code == 403
    assert _client(Role.OPS_MANAGER).get("/v1/cts/admin/bucket-accounts/CA").status_code == 200
    assert _client(Role.BANK_IT_ADMIN).get("/v1/cts/admin/bucket-accounts/IP").status_code == 200


def test_changes_are_audited_with_counts_and_never_account_numbers():
    audit = AsyncMock()
    c = _client(audit=audit)
    c.post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": ["1234567890", "9876543210"]})
    ev = audit.call_args[0][0]
    assert ev.payload["action"] == "BUCKET_ACCOUNTS_ADDED" and ev.payload["bucket"] == "CA"
    assert ev.payload["added"] == 2 and ev.payload["changed_by"] == "boss"
    assert "1234567890" not in str(ev.payload)


def test_without_the_hashing_secret_nothing_is_stored():
    pool = _Pool()
    r = _client(pool=pool, pepper=None).post("/v1/cts/admin/bucket-accounts/CA", json={"account_numbers": ["1234567890"]})
    assert r.status_code == 503 and pool.rows == {}
