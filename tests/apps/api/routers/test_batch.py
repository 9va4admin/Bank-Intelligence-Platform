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

    def _answer(self, sql):
        self.pool.sql.append(sql)
        if self.pool.fail:
            raise RuntimeError("db down")
        for tag, rows in self.pool.routes.items():     # real queries carry a /* q:name */ tag
            if f"q:{tag} " in sql:
                return rows
        return self.pool.rows.pop(0) if self.pool.rows else []

    async def fetch(self, sql, *a):
        return self._answer(sql)

    async def fetchrow(self, sql, *a):
        rows = self._answer(sql)
        return rows[0] if rows else None


class FakePool:
    def __init__(self, rows=None, fail=False, routes=None):
        self.rows, self.fail, self.sql, self.routes = list(rows or []), fail, [], dict(routes or {})

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


SID = "825c4caf-2605-5048-a7c8-19b4c843b0b1"


def _real_pool(**over):
    routes = {
        "session": [_session_row()],
        "inward_decisions": [{"decision": "STP_CONFIRM", "n": 6, "paise": 600}, {"decision": "STP_RETURN", "n": 2, "paise": 200}],
        "inward_reviews": [{"status": "PENDING", "reviewer_decision": None, "n": 3, "paise": 300},
                           {"status": "DECIDED", "reviewer_decision": "CONFIRM", "n": 1, "paise": 100},
                           {"status": "DECIDED", "reviewer_decision": "RETURN", "n": 1, "paise": 50}],
        "inward_totals": [{"n": 12, "paise": 1250, "breached": 0}],
        "inward_perf": [{"avg_ms": 300, "p99_ms": 580, "near": 2}],
        "outward_totals": [{"n": 10, "paise": 9000}],
        "outward_returns": [{"return_reason_code": "01", "n": 2, "paise": 800}],
        "settlement": [{"net_position_paise": 4200}],
        "bankwise_inward": [{"ifsc": "HDFC0000001", "n": 5, "paise": 500, "confirmed": 4, "returned": 1, "confirmed_paise": 400}],
        "bankwise_outward": [{"ifsc": "KKBK0000001", "n": 8, "paise": 8000, "confirmed": 7, "returned": 1, "returned_paise": 700}],
        "rrf": [{"rrf_path": "cts/hdfc-bank/2026-10-31/rrf/x.xml", "exception_count": 2}],
    }
    routes.update(over)
    return FakePool(routes=routes)


class TestSessionSummary:
    def test_breakdown_is_built_from_the_database(self):
        d = _client(_real_pool()).get(f"/v1/cts/sessions/{SID}/summary").json()
        p, w = d["presenting_bank"], d["drawee_bank"]
        assert (p["total_inward"], p["stp_confirmed"], p["stp_returned"]) == (12, 6, 2)
        assert (p["manual_confirmed"], p["manual_returned"], p["pending_review"]) == (1, 1, 3)
        assert (p["avg_decision_ms"], p["p99_decision_ms"], p["iet_near_breach_count"]) == (300, 580, 2)
        assert p["stp_rate_pct"] == 66.67 and p["return_rate_pct"] == 25.0
        assert (w["total_outward"], w["ngch_returned"], w["ngch_accepted"]) == (10, 2, 8)
        assert w["return_reasons"] == {"01": 2}
        assert d["net_settlement_paise"] == 4200 and d["session"]["session_id"] == SID

    def test_net_settlement_is_null_until_reconciled(self):
        d = _client(_real_pool(settlement=[])).get(f"/v1/cts/sessions/{SID}/summary").json()
        assert d["net_settlement_paise"] is None

    def test_unknown_session_is_404(self):
        resp = _client(_real_pool(session=[])).get(f"/v1/cts/sessions/{SID}/summary")
        assert resp.status_code == 404 and resp.json()["detail"]["error_code"] == "CTS_SESSION_NOT_FOUND"

    def test_malformed_session_id_is_404_not_500(self):
        assert _client(_real_pool()).get("/v1/cts/sessions/not-a-uuid/summary").status_code == 404

    def test_database_error_is_503(self):
        assert _client(FakePool(fail=True)).get(f"/v1/cts/sessions/{SID}/summary").status_code == 503

    def test_sql_uses_only_columns_that_exist(self):
        pool = _real_pool()
        _client(pool).get(f"/v1/cts/sessions/{SID}/summary")
        assert not [c for c in _NOT_IN_SCHEMA if c in " ".join(pool.sql)]


class TestBankwise:
    def test_rows_from_both_perspectives(self):
        rows = _client(_real_pool()).get(f"/v1/cts/sessions/{SID}/bankwise").json()["rows"]
        by = {r["bank_ifsc"]: r for r in rows}
        assert by["HDFC0000001"]["perspective"] == "PRESENTING" and by["HDFC0000001"]["cheque_count"] == 5
        assert by["HDFC0000001"]["return_rate_pct"] == 20.0
        assert by["KKBK0000001"]["perspective"] == "DRAWEE" and by["KKBK0000001"]["returned_count"] == 1

    def test_perspective_filter(self):
        rows = _client(_real_pool()).get(f"/v1/cts/sessions/{SID}/bankwise?perspective=DRAWEE").json()["rows"]
        assert {r["perspective"] for r in rows} == {"DRAWEE"}

    def test_no_activity_is_an_empty_list(self):
        d = _client(_real_pool(bankwise_inward=[], bankwise_outward=[])).get(f"/v1/cts/sessions/{SID}/bankwise").json()
        assert d["rows"] == []


class TestDownloads:
    def test_npci_serves_the_stored_rrf_file(self, monkeypatch):
        seen = {}

        async def fake_fetch(url, timeout=15.0):
            seen["url"] = url
            return b"<RRF>real</RRF>"
        monkeypatch.setattr("apps.api.routers.batch.fetch_object_bytes", fake_fetch)
        resp = _client(_real_pool()).get(f"/v1/cts/sessions/{SID}/download/npci")
        assert resp.status_code == 200 and resp.content == b"<RRF>real</RRF>"
        assert "xml" in resp.headers["content-type"] and "attachment" in resp.headers["content-disposition"]
        assert seen["url"] == "s3://astra-cts/cts/hdfc-bank/2026-10-31/rrf/x.xml"

    def test_npci_404_when_no_rrf_was_generated(self):
        resp = _client(_real_pool(rrf=[])).get(f"/v1/cts/sessions/{SID}/download/npci")
        assert resp.status_code == 404 and resp.json()["detail"]["error_code"] == "CTS_RRF_NOT_FOUND"

    def test_npci_503_when_the_stored_file_cannot_be_read(self, monkeypatch):
        async def boom(url, timeout=15.0):
            raise RuntimeError("minio down")
        monkeypatch.setattr("apps.api.routers.batch.fetch_object_bytes", boom)
        assert _client(_real_pool()).get(f"/v1/cts/sessions/{SID}/download/npci").status_code == 503

    def test_mis_csv_carries_the_real_numbers(self):
        resp = _client(_real_pool()).get(f"/v1/cts/sessions/{SID}/download/mis")
        assert resp.status_code == 200 and "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        body = resp.text
        assert "Total Inward,12" in body and "STP Confirmed,6" in body and "Total Outward,10" in body
        assert "2105" not in body and "FUNDS_INSUFFICIENT,185" not in body       # the old invented figures

    def test_mis_works_for_today_without_a_session_row(self):
        resp = _client(_real_pool(session=[])).get("/v1/cts/sessions/TODAY/download/mis")
        assert resp.status_code == 200 and "Total Inward,12" in resp.text

    def test_settlement_csv_is_per_counterparty_and_signed(self):
        body = _client(_real_pool()).get(f"/v1/cts/sessions/{SID}/download/settlement").text
        assert "HDFC0000001" in body and "KKBK0000001" in body and "PAY" in body and "RECEIVE" in body
        assert "State Bank" not in body and "8,20,00,000" not in body

    @pytest.mark.parametrize("path", ["npci", "mis", "settlement"])
    def test_downloads_require_auth(self, unauthed_client, path):
        assert unauthed_client.get(f"/v1/cts/sessions/{SID}/download/{path}").status_code == 401


class TestOpsDashboard:
    def _pool(self):
        today = dt.date.today()
        return _real_pool(
            ops_instruments=[{"day": today, "inward": 12, "outward": 10, "inward_paise": 2_000_000_000, "breached": 1}],
            ops_decisions=[{"day": today, "total": 8, "stp_confirmed": 6, "returned": 2}],
            ops_sessions=[_session_row()],
        )

    def test_today_and_trend_from_the_database(self):
        d = _client(self._pool()).get("/v1/cts/dashboard/ops?days=3").json()
        assert len(d["trend"]) <= 3
        t = d["today"]
        assert (t["inward"], t["outward"], t["iet_breach"]) == (12, 10, 1)
        assert t["inward_value_cr"] == 2.0 and t["stp_rate_pct"] == 75.0 and t["return_rate_pct"] == 25.0
        assert t["sessions"][0]["id"] == SID and t["sessions"][0]["status"] == "FILED"

    def test_a_quiet_day_is_zeros(self):
        d = _client(_real_pool(ops_instruments=[], ops_decisions=[], ops_sessions=[])).get("/v1/cts/dashboard/ops").json()
        assert d["today"]["inward"] == 0 and d["today"]["sessions"] == []

    def test_database_error_is_503(self):
        assert _client(FakePool(fail=True)).get("/v1/cts/dashboard/ops").status_code == 503

    def test_requires_auth(self, unauthed_client):
        assert unauthed_client.get("/v1/cts/dashboard/ops").status_code == 401


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
