"""
Phase 4 TDD tests — Ops Dashboard data endpoints:
  GET /v1/cts/dashboard/today
  GET /v1/cts/dashboard/trend

RED phase: all tests expected to FAIL before implementation.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext


def _make_app():
    from apps.api.routers.cts import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _ops_ctx(bank_id="saraswat-coop"):
    return UserContext(
        user_id="ops-001",
        bank_id=bank_id,
        bank_type=BankType.SB,
        role=Role.OPS_MANAGER,
        permission_level=PermissionLevel.EDIT,
    )


def _smb_ctx(bank_id="vasavi-001"):
    return UserContext(
        user_id="ops-smb-001",
        bank_id=bank_id,
        bank_type=BankType.SMB,
        role=Role.OPS_MANAGER,
        permission_level=PermissionLevel.EDIT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/dashboard/today
# ─────────────────────────────────────────────────────────────────────────────

class TestDashboardTodayEndpoint:
    """Today's clearing summary — inward + outward counts, STP/return rates."""

    def test_dashboard_today_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 401

    def test_dashboard_today_no_db_returns_zeroes(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _ops_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200
        body = r.json()
        assert "clearing_date" in body
        assert "total_inward" in body
        assert "total_outward" in body
        assert "stp_confirmed" in body
        assert "sessions_count" in body
        assert body["total_inward"] == 0
        assert body["stp_confirmed"] == 0

    def test_dashboard_today_returns_live_inward_count(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _ops_ctx()
        pool = MagicMock()
        # fetchrow for inward stats
        pool.fetchrow = AsyncMock(side_effect=[
            {   # inward query result
                "total_inward": 5175,
                "stp_confirmed": 3674,
                "stp_returned": 724,
                "manual_confirmed": 466,
                "manual_returned": 259,
                "pending_review": 52,
            },
            {   # outward query result
                "total_outward": 3480,
                "outward_returned": 278,
            },
            {   # sessions query
                "sessions_count": 4,
                "sessions_settled": 2,
            },
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200
        body = r.json()
        assert body["total_inward"] == 5175
        assert body["stp_confirmed"] == 3674
        assert body["stp_returned"] == 724

    def test_dashboard_today_computes_stp_rate(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _ops_ctx()
        pool = MagicMock()
        pool.fetchrow = AsyncMock(side_effect=[
            {"total_inward": 100, "stp_confirmed": 80, "stp_returned": 10, "manual_confirmed": 5, "manual_returned": 5, "pending_review": 0},
            {"total_outward": 50, "outward_returned": 5},
            {"sessions_count": 2, "sessions_settled": 1},
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200
        body = r.json()
        # STP rate = stp_confirmed / total_inward * 100 = 80.0
        assert body["overall_stp_rate_pct"] == 80.0

    def test_dashboard_today_bank_scoped(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _smb_ctx()
        pool = MagicMock()
        pool.fetchrow = AsyncMock(side_effect=[
            {"total_inward": 318, "stp_confirmed": 224, "stp_returned": 49, "manual_confirmed": 30, "manual_returned": 15, "pending_review": 0},
            {"total_outward": 90, "outward_returned": 8},
            {"sessions_count": 2, "sessions_settled": 1},
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/today")
        assert r.status_code == 200
        body = r.json()
        assert body["bank_id"] == "vasavi-001"


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/dashboard/trend
# ─────────────────────────────────────────────────────────────────────────────

class TestDashboardTrendEndpoint:
    """7-day trend data for the ops dashboard sparklines."""

    def test_dashboard_trend_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/trend")
        assert r.status_code == 401

    def test_dashboard_trend_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _ops_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/trend")
        assert r.status_code == 200
        body = r.json()
        assert "trend" in body
        assert isinstance(body["trend"], list)

    def test_dashboard_trend_returns_daily_rows(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _ops_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[
            {"date": "Sep 01", "inward": 4800, "stp_rate_pct": 84.5, "return_rate_pct": 18.2},
            {"date": "Aug 31", "inward": 4650, "stp_rate_pct": 83.1, "return_rate_pct": 19.4},
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/trend")
        assert r.status_code == 200
        body = r.json()
        rows = body["trend"]
        assert len(rows) == 2
        assert rows[0]["date"] == "Sep 01"
        assert rows[0]["inward"] == 4800

    def test_dashboard_trend_respects_days_param(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _ops_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/dashboard/trend?days=14")
        assert r.status_code == 200
