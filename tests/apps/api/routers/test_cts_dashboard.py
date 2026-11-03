"""
Tests for cts_dashboard.py — GET /dashboard/today, /dashboard/trend, /exceptions.

Failures are surfaced (503), never turned into zeros; queries use the real cts schema.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import UserContext, Role, BankType, PermissionLevel


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_ctx(bank_id: str = "test-bank") -> UserContext:
    return UserContext(
        user_id="u1",
        bank_id=bank_id,
        bank_type=BankType.SB,
        role=Role.OPS_MANAGER,
        permission_level=PermissionLevel.EDIT,
        session_id="sess1",
    )


def _make_app(db_pool=None):
    """Build a minimal FastAPI app with only cts_dashboard routes registered."""
    from apps.api.routers.cts_dashboard import router_v1
    from apps.api.routers.cts_deps import get_current_user_context

    app = FastAPI()
    app.include_router(router_v1)

    ctx = _make_ctx()

    async def _override_ctx():
        return ctx

    app.dependency_overrides[get_current_user_context] = _override_ctx
    if db_pool is not None:
        app.state.db_pool_cts = db_pool
    return app



import contextlib


class _Conn:
    """Routes a query to canned rows by its /* q:name */ tag (or by table name for untagged SQL)."""
    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.sql = rows, fail, []

    async def fetch(self, sql, *args):
        if self.fail:
            raise RuntimeError("db down")
        self.sql.append(sql)
        for key, val in self.rows.items():
            if key in sql:
                return val
        return []


class _Pool:
    def __init__(self, rows=None, fail=False):
        self.conn = _Conn(rows or {}, fail)

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


_INWARD = {
    "q:inward_decisions": [{"decision": "STP_CONFIRM", "n": 6, "paise": 600}, {"decision": "STP_RETURN", "n": 1, "paise": 100}],
    "q:inward_reviews": [{"status": "DECIDED", "reviewer_decision": "CONFIRM", "n": 2, "paise": 200},
                         {"status": "DECIDED", "reviewer_decision": "RETURN", "n": 1, "paise": 50},
                         {"status": "PENDING", "reviewer_decision": None, "n": 3, "paise": 300}],
    "q:inward_totals": [{"n": 13, "paise": 1250, "breached": 0}],
    "q:inward_perf": [{"avg_ms": 400, "p99_ms": 590, "near": 0}],
    "q:outward_totals": [{"n": 5, "paise": 500}],
    "q:outward_returns": [{"return_reason_code": "09", "n": 1, "paise": 100}],
    "q:outward_ngch": [{"accepted": 4, "returned": 1}],
    "FROM cts.clearing_sessions": [{"status": "SETTLED"}, {"status": "OPEN"}],
}


class TestDashboardToday:

    def test_counts_come_from_real_decisions_and_reviews(self):
        client = TestClient(_make_app(db_pool=_Pool(_INWARD)))
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200, r.text
        b = r.json()
        assert (b["total_inward"], b["stp_confirmed"], b["stp_returned"]) == (13, 6, 1)
        assert (b["manual_confirmed"], b["manual_returned"], b["pending_review"]) == (2, 1, 3)
        assert b["total_outward"] == 5
        assert b["sessions_count"] == 2 and b["sessions_settled"] == 1

    def test_response_and_queries_are_scoped_to_the_callers_bank(self):
        pool = _Pool(_INWARD)
        captured = []
        orig = pool.conn.fetch
        async def spy(sql, *args):
            captured.append(args)
            return await orig(sql, *args)
        pool.conn.fetch = spy
        b = TestClient(_make_app(db_pool=pool)).get("/v1/cts/dashboard/today").json()
        assert b["bank_id"] == "test-bank"
        assert captured and all(a[0] == "test-bank" for a in captured)

    def test_inward_excludes_outward_cheques(self):
        pool = _Pool(_INWARD)
        TestClient(_make_app(db_pool=pool)).get("/v1/cts/dashboard/today")
        inward_sql = [q for q in pool.conn.sql if "q:inward_decisions" in q][0]
        assert "direction = 'INWARD'" in inward_sql

    def test_manual_decisions_read_the_columns_that_are_written(self):
        pool = _Pool(_INWARD)
        TestClient(_make_app(db_pool=pool)).get("/v1/cts/dashboard/today")
        assert not any("MANUAL_CONFIRM" in q or "MANUAL_RETURN" in q for q in pool.conn.sql)

    def test_db_error_is_503_not_zeros(self):
        client = TestClient(_make_app(db_pool=_Pool(fail=True)), raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 503
        assert r.json()["detail"]["error_code"] == "CTS_BATCH_DB_UNAVAILABLE"

    def test_no_pool_is_503(self):
        client = TestClient(_make_app(db_pool=None), raise_server_exceptions=False)
        assert client.get("/v1/cts/dashboard/today").status_code == 503

    def test_unauthenticated_returns_401(self):
        from apps.api.routers.cts_dashboard import router_v1
        app = FastAPI(); app.include_router(router_v1)
        assert TestClient(app, raise_server_exceptions=False).get("/v1/cts/dashboard/today").status_code == 401


class TestDashboardTrend:

    def test_rows_are_inward_only_and_rates_from_decisions(self):
        pool = _Pool({"q:trend": [{"date": "Nov 02", "inward": 10, "stp_rate_pct": 70.0, "return_rate_pct": 10.0}]})
        r = TestClient(_make_app(db_pool=pool)).get("/v1/cts/dashboard/trend?days=3")
        assert r.status_code == 200
        assert r.json()["trend"][0] == {"date": "Nov 02", "inward": 10, "stp_rate_pct": 70.0, "return_rate_pct": 10.0}
        sql = pool.conn.sql[0]
        assert "direction = 'INWARD'" in sql and "MANUAL_RETURN" not in sql

    def test_days_bounds(self):
        c = TestClient(_make_app(db_pool=_Pool()))
        assert c.get("/v1/cts/dashboard/trend?days=31").status_code == 422
        assert c.get("/v1/cts/dashboard/trend?days=0").status_code == 422

    def test_db_error_is_503(self):
        c = TestClient(_make_app(db_pool=_Pool(fail=True)), raise_server_exceptions=False)
        assert c.get("/v1/cts/dashboard/trend").status_code == 503


class TestExceptions:

    _ROWS = {"q:exceptions": [{
        "exception_id": "EX-1", "instrument_id": "I1", "exception_type": "VAULT_MISS", "severity": "HIGH",
        "occurred_at": "2026-11-03T10:00:00+00:00", "detail": "VAULT_MISS", "resolved": False, "margin_seconds": 12}]}

    def test_items_labelled_from_real_decision_reason(self):
        r = TestClient(_make_app(db_pool=_Pool(self._ROWS))).get("/v1/cts/exceptions")
        assert r.status_code == 200
        it = r.json()["items"][0]
        assert it["exception_type"] == "VAULT_MISS" and it["margin_seconds"] == 12 and it["resolved"] is False

    def test_reads_only_columns_that_exist(self):
        pool = _Pool(self._ROWS)
        TestClient(_make_app(db_pool=pool)).get("/v1/cts/exceptions")
        sql = pool.conn.sql[0]
        assert "workflow_exceptions" not in sql and "decision_outcome" not in sql and "decided_at" not in sql
        assert "decision_reason" in sql and "iet_margin_seconds" in sql

    def test_severity_filter_applied(self):
        r = TestClient(_make_app(db_pool=_Pool(self._ROWS))).get("/v1/cts/exceptions?severity=CRITICAL")
        assert r.status_code == 200 and r.json()["total"] == 0

    def test_limit_capped_at_500(self):
        assert TestClient(_make_app(db_pool=_Pool())).get("/v1/cts/exceptions?limit=501").status_code == 422

    def test_db_error_is_503_not_empty(self):
        c = TestClient(_make_app(db_pool=_Pool(fail=True)), raise_server_exceptions=False)
        assert c.get("/v1/cts/exceptions").status_code == 503

    def test_unauthenticated_returns_401(self):
        from apps.api.routers.cts_dashboard import router_v1
        app = FastAPI(); app.include_router(router_v1)
        assert TestClient(app, raise_server_exceptions=False).get("/v1/cts/exceptions").status_code == 401
