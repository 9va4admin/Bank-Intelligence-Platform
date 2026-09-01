"""
Tests for GET /v1/cts/outward/lots/{lot_id}/instruments

Returns accepted instruments for a lot (from cts.outward_scan_events).
Used by CTSPresentmentFile.jsx live mode.
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


def _make_app(lot_row=None, scan_rows=None, ctx=None):
    from apps.api.routers.cts import router_v1, require_user_context

    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)

    # fetchrow for lot ownership check
    conn.fetchrow = AsyncMock(return_value=lot_row)
    # fetch for scan events
    conn.fetch = AsyncMock(return_value=scan_rows or [])

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)

    app = FastAPI()
    app.include_router(router_v1)
    app.state.db_pool_cts = pool

    if ctx:
        app.dependency_overrides[require_user_context] = lambda: ctx

    return app


_SAMPLE_SCAN_ROWS = [
    {
        "scan_id": "SCAN-001",
        "instrument_id": "INST-001",
        "micr_suffix": "4521",
        "payee_display": "R***",
        "amount_range": "STANDARD",
        "outcome": "ACCEPTED",
        "scanned_at": "2026-09-01T10:00:00+05:30",
    },
    {
        "scan_id": "SCAN-002",
        "instrument_id": "INST-002",
        "micr_suffix": "7890",
        "payee_display": "S***",
        "amount_range": "HIGH_VALUE",
        "outcome": "ACCEPTED",
        "scanned_at": "2026-09-01T10:01:00+05:30",
    },
]

_SAMPLE_LOT_ROW = {
    "lot_id": "LOT-001",
    "bank_id": "test-bank",
    "status": "OPEN",
    "instrument_count": 2,
}


class TestLotInstruments:
    def test_unauthenticated_returns_401(self):
        from apps.api.routers.cts import router_v1

        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/lots/LOT-001/instruments")
        assert resp.status_code == 401

    def test_returns_200_with_instrument_list(self):
        app = _make_app(
            lot_row=_SAMPLE_LOT_ROW,
            scan_rows=_SAMPLE_SCAN_ROWS,
            ctx=_ctx(),
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/lots/LOT-001/instruments")
        assert resp.status_code == 200
        data = resp.json()
        assert "instruments" in data
        assert len(data["instruments"]) == 2

    def test_instrument_row_shape(self):
        app = _make_app(
            lot_row=_SAMPLE_LOT_ROW,
            scan_rows=_SAMPLE_SCAN_ROWS,
            ctx=_ctx(),
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/lots/LOT-001/instruments")
        row = resp.json()["instruments"][0]
        for field in ("scan_id", "instrument_id", "micr_suffix", "payee_display",
                      "amount_range", "outcome", "scanned_at"):
            assert field in row, f"Missing field: {field}"

    def test_404_unknown_lot(self):
        app = _make_app(
            lot_row=None,           # fetchrow returns None → lot not found
            scan_rows=[],
            ctx=_ctx(),
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/lots/NONEXISTENT/instruments")
        assert resp.status_code == 404

    def test_403_cross_bank_lot(self):
        cross_bank_lot = {**_SAMPLE_LOT_ROW, "bank_id": "other-bank"}  # different bank
        app = _make_app(
            lot_row=cross_bank_lot,
            scan_rows=_SAMPLE_SCAN_ROWS,
            ctx=_ctx(bank_id="test-bank"),
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/lots/LOT-001/instruments")
        assert resp.status_code == 403

    def test_503_no_db(self):
        from apps.api.routers.cts import router_v1, require_user_context

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[require_user_context] = lambda: _ctx()
        # No db_pool_cts
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/cts/outward/lots/LOT-001/instruments")
        assert resp.status_code == 503
