"""
Tests for cts_dashboard.py — GET /dashboard/today, /dashboard/trend, /exceptions.

TDD: this file is written BEFORE cts_dashboard.py exists — first run must be RED.
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


# ---------------------------------------------------------------------------
# GET /v1/cts/dashboard/today
# ---------------------------------------------------------------------------

class TestDashboardToday:

    def test_no_db_returns_zeroed_summary(self):
        """When db_pool_cts is absent (dev mode) return zero-filled summary."""
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200
        body = r.json()
        assert body["bank_id"] == "test-bank"
        assert body["total_inward"] == 0
        assert body["stp_confirmed"] == 0
        assert body["overall_stp_rate_pct"] == 0.0

    def test_with_db_returns_computed_rates(self):
        """When DB rows are present, stp_rate_pct is calculated correctly."""
        inward_row = {
            "total_inward": 100, "stp_confirmed": 80, "stp_returned": 10,
            "manual_confirmed": 5, "manual_returned": 3, "pending_review": 2,
        }
        outward_row = {"total_outward": 50, "outward_returned": 5}
        session_row = {"sessions_count": 3, "sessions_settled": 2}

        mock_db = MagicMock()
        mock_db.fetchrow = AsyncMock(side_effect=[inward_row, outward_row, session_row])

        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200
        body = r.json()
        assert body["stp_confirmed"] == 80
        assert body["total_inward"] == 100
        assert body["overall_stp_rate_pct"] == 80.0
        assert body["sessions_count"] == 3

    def test_db_error_returns_zeroed_summary(self):
        """If the DB raises, return zero-filled summary — never 500."""
        mock_db = MagicMock()
        mock_db.fetchrow = AsyncMock(side_effect=Exception("db down"))

        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200
        body = r.json()
        assert body["total_inward"] == 0

    def test_unauthenticated_returns_401(self):
        """No auth override → 401."""
        from apps.api.routers.cts_dashboard import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/cts/dashboard/trend
# ---------------------------------------------------------------------------

class TestDashboardTrend:

    def test_no_db_returns_empty_trend(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/dashboard/trend?days=7")
        assert r.status_code == 200
        body = r.json()
        assert body["bank_id"] == "test-bank"
        assert body["trend"] == []
        assert body["days"] == 7

    def test_with_db_returns_trend_rows(self):
        rows = [
            {"date": "Sep 01", "inward": 40, "stp_rate_pct": 85.0, "return_rate_pct": 10.0},
            {"date": "Sep 02", "inward": 55, "stp_rate_pct": 90.0, "return_rate_pct": 8.0},
        ]
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=rows)

        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/dashboard/trend?days=7")
        assert r.status_code == 200
        body = r.json()
        assert len(body["trend"]) == 2
        assert body["trend"][0]["date"] == "Sep 01"
        assert body["trend"][0]["stp_rate_pct"] == 85.0

    def test_days_param_capped_at_30(self):
        """days > 30 → 422 validation error."""
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/dashboard/trend?days=99")
        assert r.status_code == 422

    def test_days_param_minimum_1(self):
        """days=0 → 422 validation error."""
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/dashboard/trend?days=0")
        assert r.status_code == 422

    def test_db_error_returns_empty_trend(self):
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(side_effect=Exception("db down"))
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/dashboard/trend")
        assert r.status_code == 200
        assert r.json()["trend"] == []


# ---------------------------------------------------------------------------
# GET /v1/cts/exceptions
# ---------------------------------------------------------------------------

class TestExceptions:

    def test_no_db_returns_empty_exceptions(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/exceptions")
        assert r.status_code == 200
        body = r.json()
        assert body["bank_id"] == "test-bank"
        assert body["items"] == []
        assert body["total"] == 0

    def test_with_db_returns_labelled_exceptions(self):
        rows = [
            {
                "exception_id": "EX-001", "instrument_id": "INST001",
                "exception_type": "IET_NEAR_BREACH", "severity": "CRITICAL",
                "occurred_at": "2026-09-09T10:00:00+00:00",
                "detail": "30s margin", "resolved": False, "margin_seconds": 28,
            }
        ]
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=rows)

        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/exceptions")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["label"] == "IET Near-Breach (< 30s margin)"
        assert body["items"][0]["severity"] == "CRITICAL"
        assert body["items"][0]["resolved"] is False

    def test_severity_filter_passed_to_query(self):
        """severity param is accepted without error."""
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=[])
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/exceptions?severity=CRITICAL")
        assert r.status_code == 200

    def test_limit_capped_at_500(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/exceptions?limit=501")
        assert r.status_code == 422

    def test_db_exception_falls_back_to_agent_decisions(self):
        """Primary query fails → fallback to agent_decisions query."""
        fallback_rows = [
            {
                "exception_id": "EX-INST002", "instrument_id": "INST002",
                "exception_type": "OCR_LOW_CONFIDENCE", "severity": "HIGH",
                "occurred_at": "2026-09-09T11:00:00+00:00",
                "detail": "See agent decision for full context",
                "resolved": False, "margin_seconds": None,
            }
        ]
        mock_db = MagicMock()
        # First fetch (workflow_exceptions) raises, second fetch (agent_decisions) succeeds
        mock_db.fetch = AsyncMock(side_effect=[Exception("table missing"), fallback_rows])

        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/exceptions")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["instrument_id"] == "INST002"

    def test_unauthenticated_returns_401(self):
        from apps.api.routers.cts_dashboard import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/exceptions")
        assert r.status_code == 401
