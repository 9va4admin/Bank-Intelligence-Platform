"""Tests for batch operations API: clearing sessions from the real schema, and the endpoints not yet backed by real data."""
import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.batch import get_current_bank_id, get_current_role, router_v1

_AUTH = {"Authorization": "Bearer test-token-hdfc-bank"}

# Columns the migration chain does NOT create on cts.clearing_sessions. The old queries used them, failed on every real
# database, and the route silently answered with hard-coded sessions. A fake connection cannot notice a wrong column,
# so the tests below check the SQL text itself.
_NOT_IN_SCHEMA = ("clearing_date", "opened_at", "sealed_at", "submitted_at", "reconciled_at", "npci_ack_ref", "total_instruments")


class FakeConn:
    def __init__(self, pool):
        self.pool = pool

    async def fetch(self, sql, *a):
        self.pool.sql.append(sql)
        if self.pool.fail:
            raise RuntimeError("db down")
        return self.pool.rows.pop(0) if self.pool.rows else []


class FakePool:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.sql = list(rows or []), fail, []

    def acquire(self):
        conn = FakeConn(self)

        class A:
            async def __aenter__(s): return conn
            async def __aexit__(s, *e): return False
        return A()


_MISSING = object()


def _client(pool):
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_bank_id] = lambda: "hdfc-bank"
    app.dependency_overrides[get_current_role] = lambda: "ops_manager"
    if pool is not _MISSING:
        app.state.db_pool_cts = pool
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def client():
    return _client(FakePool())


@pytest.fixture()
def unauthed_client():
    """No override: exercises the real (middleware-backed) auth path."""
    app = FastAPI()
    app.include_router(router_v1)
    return TestClient(app, raise_server_exceptions=False)


def _session_row(**kw):
    base = {"session_id": "825c4caf-2605-5048-a7c8-19b4c843b0b1", "session_date": dt.date(2026, 10, 31),
            "session_type": "MORNING", "status": "SUBMITTED",
            "created_at": dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.timezone.utc),
            "presentation_open_at": None, "presentation_close_at": None, "settlement_at": None}
    base.update(kw)
    return base


class TestSessionList:
    def test_lists_the_real_rows_and_maps_status(self):
        pool = FakePool(rows=[[_session_row(), _session_row(session_id="s2", status="PENDING", session_type="AFTERNOON")]])
        data = _client(pool).get("/v1/cts/sessions").json()
        assert data["total"] == 2
        assert [s["status"] for s in data["sessions"]] == ["FILED", "OPEN"]
        assert data["sessions"][0]["clearing_date"] == "2026-10-31"
        assert data["sessions"][0]["opened_at"].startswith("2026-10-31T09:00")  # falls back to created_at

    def test_sql_uses_only_columns_that_exist(self):
        pool = FakePool(rows=[[]])
        _client(pool).get("/v1/cts/sessions")
        assert pool.sql and not [c for c in _NOT_IN_SCHEMA if c in pool.sql[0]]

    def test_empty_is_empty_not_fake_sessions(self):
        data = _client(FakePool(rows=[[]])).get("/v1/cts/sessions").json()
        assert data["sessions"] == [] and data["total"] == 0

    def test_database_error_is_an_error_not_mock_data(self):
        resp = _client(FakePool(fail=True)).get("/v1/cts/sessions")
        assert resp.status_code == 503 and "sessions" not in resp.json()

    def test_no_database_is_an_error_not_mock_data(self):
        resp = _client(_MISSING).get("/v1/cts/sessions")
        assert resp.status_code == 503 and "sessions" not in resp.json()

    def test_requires_auth(self, unauthed_client):
        assert unauthed_client.get("/v1/cts/sessions").status_code == 401


def _today_pool(sessions=None, inward=(0, 0), outward=(0, 0), decisions=None, reviews=None, trend=None):
    return FakePool(rows=[sessions or [],
                          [{"direction": "INWARD", "n": inward[0], "paise": inward[1]},
                           {"direction": "OUTWARD", "n": outward[0], "paise": outward[1]}],
                          decisions or [], reviews or [], trend or []])


class TestTodaySummary:
    def test_counts_come_from_the_database(self):
        pool = _today_pool(
            sessions=[{"status": "RECONCILED"}, {"status": "SUBMITTED"}],
            inward=(10, 5_000_000), outward=(4, 2_000_000),
            decisions=[{"decision": "STP_CONFIRM", "n": 6}, {"decision": "STP_RETURN", "n": 2}],
            reviews=[{"status": "PENDING", "reviewer_decision": None, "n": 3},
                     {"status": "DECIDED", "reviewer_decision": "CONFIRM", "n": 1},
                     {"status": "DECIDED", "reviewer_decision": "RETURN", "n": 1}])
        d = _client(pool).get("/v1/cts/sessions/today").json()
        assert (d["sessions_count"], d["sessions_settled"]) == (2, 1)
        assert (d["total_inward"], d["total_inward_value_paise"]) == (10, 5_000_000)
        assert (d["total_outward"], d["total_outward_value_paise"]) == (4, 2_000_000)
        assert (d["stp_confirmed"], d["stp_returned"]) == (6, 2)
        assert (d["manual_confirmed"], d["manual_returned"], d["pending_review"]) == (1, 1, 3)
        assert d["overall_stp_rate_pct"] == 80.0

    def test_sql_uses_only_columns_that_exist(self):
        pool = _today_pool()
        _client(pool).get("/v1/cts/sessions/today")
        joined = " ".join(pool.sql)
        assert pool.sql and not [c for c in _NOT_IN_SCHEMA if c in joined]

    def test_nothing_today_is_zeros_not_invented_numbers(self):
        d = _client(_today_pool()).get("/v1/cts/sessions/today").json()
        assert d["total_inward"] == 0 and d["sessions_count"] == 0 and d["stp_confirmed"] == 0
        assert d["net_settlement_paise"] is None            # not derivable without reconciliation
        assert all(t["inward"] == 0 for t in d["trend_5d"])

    def test_database_error_is_an_error_not_mock_data(self):
        assert _client(FakePool(fail=True)).get("/v1/cts/sessions/today").status_code == 503

    def test_no_database_is_an_error_not_mock_data(self):
        assert _client(_MISSING).get("/v1/cts/sessions/today").status_code == 503

    def test_requires_auth(self, unauthed_client):
        assert unauthed_client.get("/v1/cts/sessions/today").status_code == 401


_UNBUILT = [
    "/v1/cts/sessions/S1/summary", "/v1/cts/sessions/S1/bankwise", "/v1/cts/sessions/S1/download/npci",
    "/v1/cts/sessions/S1/download/mis", "/v1/cts/sessions/S1/download/settlement", "/v1/cts/dashboard/ops",
]


class TestNotYetBackedByRealData:
    """These endpoints used to return invented numbers (a fake NPCI return file among them). Until each is built on
    real data it says so, rather than handing a bank something that looks genuine."""

    @pytest.mark.parametrize("path", _UNBUILT)
    def test_returns_501_with_error_code_and_no_data(self, client, path):
        resp = client.get(path, headers=_AUTH)
        assert resp.status_code == 501
        assert resp.json()["detail"]["error_code"] == "CTS_BATCH_NOT_IMPLEMENTED"

    @pytest.mark.parametrize("path", _UNBUILT)
    def test_still_requires_auth(self, unauthed_client, path):
        assert unauthed_client.get(path).status_code == 401


class TestBatchAuthEdgeCases:
    """get_current_bank_id / get_current_role delegate to the shared,
    middleware-backed require_user_context: no per-router token parsing,
    no test-token backdoor."""

    def test_test_token_bearer_header_no_longer_grants_access(self, unauthed_client):
        """Regression guard for ASTRA-01: batch.py minted bank_id='hdfc-bank'
        and role='ops_manager' (full val/vol dashboard + file downloads) from
        a bare test-token-* Bearer header. That must never work again."""
        resp = unauthed_client.get("/v1/cts/sessions", headers=_AUTH)
        assert resp.status_code == 401
