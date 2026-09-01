"""
Tests for GET /v1/cts/outward/analytics/daily

Returns 7-day rolling daily aggregates from cts.cheque_instruments
and cts.agent_decisions. Scoped to bank_id from JWT.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from shared.auth.rbac import PermissionLevel, Role, UserContext


def _ctx(bank_id="test-bank", role=Role.OPS_MANAGER):
    return UserContext(
        user_id="u-1",
        bank_id=bank_id,
        role=role,
        permission_level=PermissionLevel.EDIT,
        bank_type="SB",
    )


def _make_app(mock_db=None, ctx=None):
    from apps.api.routers.cts import router_v1, require_user_context

    app = FastAPI()
    app.include_router(router_v1)

    if ctx:
        app.dependency_overrides[require_user_context] = lambda: ctx

    if mock_db is not None:
        app.state.db_pool_cts = mock_db

    return app


def _fake_analytics_rows():
    return [
        {
            "date": "2026-08-26",
            "total": 5210,
            "stp_confirm": 4281,
            "stp_return": 721,
            "human_review": 208,
            "avg_ms": 372.0,
            "ocr_conf": 99.3,
            "sig_prec": 98.1,
        },
        {
            "date": "2026-08-27",
            "total": 4980,
            "stp_confirm": 4101,
            "stp_return": 681,
            "human_review": 198,
            "avg_ms": 401.0,
            "ocr_conf": 99.0,
            "sig_prec": 97.8,
        },
    ]


class TestAnalyticsDaily:
    def test_unauthenticated_returns_401(self):
        from apps.api.routers.cts import router_v1

        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/analytics/daily")
        assert resp.status_code == 401

    def test_returns_200_with_daily_rows(self):
        conn = AsyncMock()
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        conn.fetch = AsyncMock(return_value=_fake_analytics_rows())

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=conn)

        app = _make_app(mock_db=pool, ctx=_ctx())
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/analytics/daily")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily" in data
        assert isinstance(data["daily"], list)
        assert len(data["daily"]) == 2

    def test_response_rows_have_required_fields(self):
        conn = AsyncMock()
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        conn.fetch = AsyncMock(return_value=_fake_analytics_rows())

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=conn)

        app = _make_app(mock_db=pool, ctx=_ctx())
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/analytics/daily")
        row = resp.json()["daily"][0]
        for field in ("date", "total", "stp_confirm", "stp_return", "human_review", "avg_ms"):
            assert field in row, f"Missing field: {field}"

    def test_503_when_no_db(self):
        from apps.api.routers.cts import router_v1, require_user_context

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[require_user_context] = lambda: _ctx()
        # No db_pool_cts on app.state
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/analytics/daily")
        assert resp.status_code == 503

    def test_wrong_role_returns_403(self):
        from apps.api.routers.cts import router_v1, require_user_context

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[require_user_context] = lambda: _ctx(role=Role.RBI_EXAMINER)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/analytics/daily")
        assert resp.status_code == 403
