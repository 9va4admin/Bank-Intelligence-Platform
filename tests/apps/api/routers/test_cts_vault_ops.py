"""
Tests for cts_vault_ops.py — 7 vault operational routes.

Routes tested:
  GET  /v1/cts/vault-sync/status
  POST /v1/cts/vault-sync/trigger
  GET  /v1/cts/vault/sync-status
  GET  /v1/cts/vault/health
  GET  /v1/cts/vault/misses
  GET  /v1/cts/vault/pps
  GET  /v1/cts/vault/stop-cheques
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import Role, UserContext


def _ctx(role: str = "ops_manager", bank_id: str = "testbank") -> UserContext:
    ctx = MagicMock(spec=UserContext)
    ctx.role = Role[role.upper()]
    ctx.bank_id = bank_id
    ctx.user_id = "u-test"
    return ctx


def _make_app(ctx: Optional[UserContext] = None, bank_id: str = "testbank"):
    from apps.api.routers import cts_vault_ops
    from apps.api.routers.cts_deps import (
        get_current_user_context,
        get_current_bank_id,
    )

    app = FastAPI()
    app.include_router(cts_vault_ops.router_v1)

    if ctx is None:
        ctx = _ctx()

    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    return app


# ── 1. GET /vault-sync/status ─────────────────────────────────────────────────

class TestGetVaultSyncStatus:
    def test_no_temporal_returns_unknown(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault-sync/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "UNKNOWN"

    def test_temporal_exception_returns_unknown(self):
        mock_tc = MagicMock()
        handle = MagicMock()
        handle.result = AsyncMock(side_effect=Exception("workflow not found"))
        mock_tc.get_workflow_handle = MagicMock(return_value=handle)

        app = _make_app()
        app.state.temporal_client = mock_tc
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault-sync/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "UNKNOWN"


# ── 2. POST /vault-sync/trigger ───────────────────────────────────────────────

class TestTriggerVaultSync:
    def test_no_temporal_still_returns_triggered(self):
        """Without Temporal the trigger is best-effort — returns TRIGGERED."""
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/vault-sync/trigger")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "TRIGGERED"
        assert "workflow_id" in body

    def test_workflow_id_contains_bank_id(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.post("/v1/cts/vault-sync/trigger")
        body = resp.json()
        assert "mybank" in body["workflow_id"]

    def test_temporal_error_raises_503(self):
        mock_tc = MagicMock()
        mock_tc.start_workflow = AsyncMock(side_effect=Exception("Temporal unavailable"))

        app = _make_app()
        app.state.temporal_client = mock_tc
        with TestClient(app) as c:
            resp = c.post("/v1/cts/vault-sync/trigger")
        assert resp.status_code == 503


# ── 3. GET /vault/sync-status ─────────────────────────────────────────────────

class TestVaultSyncStatusNew:
    def test_no_db_returns_empty_history(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/sync-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["history"] == []

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetchval = AsyncMock(side_effect=Exception("DB error"))

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/sync-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["history"] == []


# ── 4. GET /vault/health ──────────────────────────────────────────────────────

class TestVaultHealth:
    def test_no_db_returns_unknown(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["sig_status"] == "UNKNOWN"
        assert body["pps_status"] == "UNKNOWN"
        assert body["sig_key_count"] == 0
        assert body["miss_action"] == "HUMAN_REVIEW"

    def test_with_db_counts(self):
        mock_pool = MagicMock()
        mock_pool.fetchval = AsyncMock(side_effect=[5, 3])
        mock_pool.fetchrow = AsyncMock(side_effect=[
            {"last_sync": "2026-09-03T06:00:00"},
            {"last_sync": "2026-09-03T06:05:00"},
        ])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sig_key_count"] == 5
        assert body["pps_key_count"] == 3
        assert body["sig_status"] == "HEALTHY"

    def test_db_error_returns_unknown(self):
        mock_pool = MagicMock()
        mock_pool.fetchval = AsyncMock(side_effect=Exception("DB error"))

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sig_status"] == "UNKNOWN"


# ── 5. GET /vault/misses ──────────────────────────────────────────────────────

class TestVaultMisses:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/misses")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["misses"] == []
        assert body["total_count"] == 0

    def test_date_filter_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/misses?date=2026-09-01")
        assert resp.status_code == 200

    def test_with_rows(self):
        row = {
            "instrument_id": "INST-001",
            "account_last4": "4321",
            "vault_type": "SIGNATURE",
            "miss_reason": "KEY_NOT_FOUND",
            "routed_to": "HUMAN_REVIEW",
            "event_time": "2026-09-03T10:00:00",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/misses")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["misses"][0]["vault_type"] == "SIGNATURE"


# ── 6. GET /vault/pps ─────────────────────────────────────────────────────────

class TestVaultPPS:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/pps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["entries"] == []

    def test_status_filter_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/pps?status=REGISTERED")
        assert resp.status_code == 200

    def test_account_display_masked(self):
        row = {
            "entry_id": "PPS-001",
            "account_last4": "9876",
            "cheque_number": "123456",
            "cheque_date": "2026-09-01",
            "amount_range": "₹[1L-5L]",
            "status": "REGISTERED",
            "expires_at": "2026-12-31",
            "registered_at": "2026-09-01T00:00:00",
            "registration_channel": "CBS",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/pps")
        body = resp.json()
        assert body["entries"][0]["account_display"] == "****9876"


# ── 7. GET /vault/stop-cheques ────────────────────────────────────────────────

class TestVaultStopCheques:
    def test_ops_reviewer_forbidden(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/stop-cheques")
        assert resp.status_code == 403

    def test_ops_manager_allowed(self):
        app = _make_app(ctx=_ctx("ops_manager"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/stop-cheques")
        assert resp.status_code == 200

    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/stop-cheques")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["instructions"] == []

    def test_include_revoked_flag_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/stop-cheques?include_revoked=true")
        assert resp.status_code == 200

    def test_account_display_masked(self):
        row = {
            "stop_id": "STOP-001",
            "account_last4": "5555",
            "scope": "CHEQUE",
            "cheque_number": "999999",
            "reason": "Lost cheque",
            "status": "ACTIVE",
            "created_at": "2026-09-01T00:00:00",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/stop-cheques")
        body = resp.json()
        assert body["instructions"][0]["account_display"] == "****5555"
