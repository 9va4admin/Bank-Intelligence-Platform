"""
TDD — RED: tests for GET /v1/cts/inward/analytics

Returns 7-day rolling aggregates from cts.agent_decisions (inward pipeline):
daily throughput, fraud score distribution, risk flags, return reasons,
branch breakdown, and IET near-breach trend.
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


def _fake_daily():
    return [
        {"date": "Sep 01", "total": 4820, "stp_confirm": 3921,
         "stp_return": 641, "human_review": 258, "avg_ms": 389.0,
         "ocr_conf": 99.1, "sig_prec": 97.9},
    ]


def _fake_fraud_dist():
    return [
        {"range": "0–10",  "count": 3120},
        {"range": "10–30", "count": 890},
        {"range": "30–50", "count": 410},
        {"range": "50–70", "count": 280},
        {"range": "70–90", "count": 310},
        {"range": "90–100","count": 440},
    ]


def _fake_risk_flags_row():
    return {
        "high_value": 841, "very_high_value": 92, "vault_miss": 612,
        "alteration": 380, "stop_payment": 198, "ocr_low_conf": 143,
        "sig_low_conf": 127, "dormant": 274,
    }


def _fake_return_reasons():
    return [
        {"reason": "Fraud Risk",        "count": 440},
        {"reason": "Sig Mismatch",       "count": 310},
        {"reason": "Alteration",         "count": 180},
        {"reason": "Insufficient Funds", "count":  90},
        {"reason": "Stop Payment",       "count":  78},
        {"reason": "Dormant Account",    "count":  62},
        {"reason": "Other",              "count":  40},
    ]


def _fake_branches():
    return [
        {"branch": "MAHB0001234", "processed": 1840, "hrq_pct": 4.8,
         "vault_miss": 22, "avg_ms": 381.0, "returns": 182},
    ]


def _fake_iet_trend():
    return [
        {"date": "Sep 01", "near_breach": 2},
    ]


def _mock_conn(fetch_side_effect=None, fetchrow_return=None):
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    if fetch_side_effect is not None:
        conn.fetch = AsyncMock(side_effect=fetch_side_effect)
    if fetchrow_return is not None:
        conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool


class TestInwardAnalytics:
    def test_unauthenticated_returns_401(self):
        from apps.api.routers.cts import router_v1

        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/inward/analytics")
        assert resp.status_code == 401

    def test_returns_200_with_all_sections(self):
        pool = _mock_conn(
            fetch_side_effect=[
                _fake_daily(),
                _fake_fraud_dist(),
                _fake_return_reasons(),
                _fake_branches(),
                _fake_iet_trend(),
            ],
            fetchrow_return=_fake_risk_flags_row(),
        )
        app = _make_app(mock_db=pool, ctx=_ctx())
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/inward/analytics")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("daily", "fraud_dist", "risk_flags", "return_reasons", "branches", "iet_trend"):
            assert key in data, f"Missing section: {key}"

    def test_daily_rows_have_required_fields(self):
        pool = _mock_conn(
            fetch_side_effect=[
                _fake_daily(),
                _fake_fraud_dist(),
                _fake_return_reasons(),
                _fake_branches(),
                _fake_iet_trend(),
            ],
            fetchrow_return=_fake_risk_flags_row(),
        )
        app = _make_app(mock_db=pool, ctx=_ctx())
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/inward/analytics")
        row = resp.json()["daily"][0]
        for field in ("date", "total", "stp_confirm", "stp_return", "human_review", "avg_ms", "ocr_conf", "sig_prec"):
            assert field in row, f"Missing daily field: {field}"

    def test_iet_trend_has_near_breach_field(self):
        pool = _mock_conn(
            fetch_side_effect=[
                _fake_daily(),
                _fake_fraud_dist(),
                _fake_return_reasons(),
                _fake_branches(),
                _fake_iet_trend(),
            ],
            fetchrow_return=_fake_risk_flags_row(),
        )
        app = _make_app(mock_db=pool, ctx=_ctx())
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/inward/analytics")
        trend = resp.json()["iet_trend"]
        assert len(trend) > 0
        assert "nearBreach" in trend[0]

    def test_risk_flags_has_expected_flag_names(self):
        pool = _mock_conn(
            fetch_side_effect=[
                _fake_daily(),
                _fake_fraud_dist(),
                _fake_return_reasons(),
                _fake_branches(),
                _fake_iet_trend(),
            ],
            fetchrow_return=_fake_risk_flags_row(),
        )
        app = _make_app(mock_db=pool, ctx=_ctx())
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/inward/analytics")
        flags = {f["flag"] for f in resp.json()["risk_flags"]}
        assert "VAULT_MISS" in flags
        assert "ALTERATION" in flags

    def test_503_when_no_db(self):
        from apps.api.routers.cts import router_v1, require_user_context

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[require_user_context] = lambda: _ctx()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/inward/analytics")
        assert resp.status_code == 503

    def test_wrong_role_returns_403(self):
        from apps.api.routers.cts import router_v1, require_user_context

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[require_user_context] = lambda: _ctx(role=Role.RBI_EXAMINER)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/inward/analytics")
        assert resp.status_code == 403
