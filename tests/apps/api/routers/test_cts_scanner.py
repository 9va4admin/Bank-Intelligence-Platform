"""
Tests for cts_scanner.py — 6 scanner routes.

Routes tested:
  GET  /v1/cts/scan-monitor/recent
  POST /v1/cts/outward/scan/event
  GET  /v1/cts/outward/session/{session_id}/scan-log
  GET  /v1/cts/outward/scan-events
  POST /v1/cts/admin/scanner/registration-code
  POST /v1/cts/admin/scanner/register
"""
from __future__ import annotations

import json
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import Role, UserContext


# ── shared helpers ────────────────────────────────────────────────────────────

def _ctx(role: str = "ops_manager", bank_id: str = "testbank") -> UserContext:
    ctx = MagicMock(spec=UserContext)
    ctx.role = Role[role.upper()]
    ctx.bank_id = bank_id
    ctx.user_id = "u-test"
    return ctx


def _make_app(ctx: Optional[UserContext] = None, bank_id: str = "testbank"):
    from apps.api.routers import cts_scanner
    from apps.api.routers.cts_deps import (
        get_current_user_context,
        get_current_bank_id,
        get_bank_id_scanner_or_user,
    )

    app = FastAPI()
    app.include_router(cts_scanner.router_v1)

    if ctx is None:
        ctx = _ctx()

    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    app.dependency_overrides[get_bank_id_scanner_or_user] = lambda: bank_id
    return app


# ── 1. GET /scan-monitor/recent ───────────────────────────────────────────────

class TestScanMonitorRecent:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/scan-monitor/recent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["events"] == []
        assert body["total"] == 0

    def test_limit_capped_at_100(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/scan-monitor/recent?limit=999")
        assert resp.status_code == 200

    def test_ops_reviewer_allowed(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/scan-monitor/recent")
        assert resp.status_code == 200

    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/scan-monitor/recent")
        assert resp.status_code == 403

    def test_with_db_returning_rows(self):
        row = {
            "scan_id": "SC-001",
            "micr_suffix": "1234",
            "payee_display": "J***",
            "amount_range": "₹[1L-5L]",
            "outcome": "STP_CONFIRM",
            "lot_id": "LOT-1",
            "mismatch_id": None,
            "mismatch_fields": None,
            "reject_reason": None,
            "scanned_at": "2026-09-03T10:00:00",
        }
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=[row])

        app = _make_app()
        app.state.db = mock_db
        with TestClient(app) as c:
            resp = c.get("/v1/cts/scan-monitor/recent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["events"][0]["scan_id"] == "SC-001"


# ── 2. POST /outward/scan/event ───────────────────────────────────────────────

class TestReportOutwardScanEvent:
    _valid_body = {
        "bank_id": "testbank",
        "branch_id": "BR-01",
        "session_id": "SES-ABC",
        "scan_id": "SC-XYZ",
        "event_type": "DOUBLE_FEED_DETECTED",
        "position_in_batch": 3,
        "micr_suffix": "1234",
    }

    def test_happy_path_202(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/event", json=self._valid_body)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "RECORDED"
        assert "event_id" in body

    def test_bank_id_mismatch_403(self):
        app = _make_app(bank_id="otherbank")
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/event", json=self._valid_body)
        assert resp.status_code == 403

    def test_no_db_still_202(self):
        """Non-fatal DB write — agent must still get 202."""
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/event", json=self._valid_body)
        assert resp.status_code == 202

    def test_db_write_failure_still_202(self):
        """DB failure is logged and swallowed — agent gets 202 so scan session proceeds."""
        mock_pool = MagicMock()
        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=Exception("DB down"))
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=ctx_mgr)

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/event", json=self._valid_body)
        assert resp.status_code == 202

    def test_event_id_is_uuid_like(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/event", json=self._valid_body)
        body = resp.json()
        assert len(body["event_id"]) == 36  # UUID4 length


# ── 3. GET /outward/session/{session_id}/scan-log ─────────────────────────────

class TestScanSessionLog:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/session/SES-001/scan-log")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "SES-001"
        assert body["bank_id"] == "testbank"
        assert body["items"] == []
        assert body["total"] == 0
        assert body["double_feeds"] == 0

    def test_with_rows(self):
        row = {
            "event_id": "EV-001",
            "scan_id": "SC-001",
            "instrument_id": None,
            "workflow_id": None,
            "event_type": "DOUBLE_FEED_DETECTED",
            "position_in_batch": 2,
            "micr_suffix": "5678",
            "imprinter_stamped": False,
            "micr_source": "MOCR",
            "branch_id": "BR-01",
            "created_at_epoch": 1700000000.0,
        }
        mock_pool = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=ctx_mgr)

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/session/SES-001/scan-log")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["double_feeds"] == 1
        assert body["items"][0]["event_type"] == "DOUBLE_FEED_DETECTED"

    def test_branch_id_filter_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/session/SES-001/scan-log?branch_id=BR-01")
        assert resp.status_code == 200


# ── 4. GET /outward/scan-events ───────────────────────────────────────────────

class TestListOutwardScanEvents:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/scan-events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["total"] == 0
        assert body["events"] == []

    def test_limit_capped_at_100(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/scan-events?limit=999")
        assert resp.status_code == 200

    def test_filters_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/v1/cts/outward/scan-events?branch_id=BR-01&event_type=DOUBLE_FEED_DETECTED"
            )
        assert resp.status_code == 200

    def test_with_rows(self):
        row = {
            "scan_id": "SC-999",
            "event_type": "IMPRINTER_FAULT",
            "micr_suffix": "4321",
            "micr_source": "MOCR",
            "branch_id": "BR-01",
            "session_id": "SES-ABC",
            "position_in_batch": 5,
            "created_at": "2026-09-03T09:00:00Z",
        }
        mock_pool = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[row])
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=ctx_mgr)

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/scan-events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["events"][0]["scan_id"] == "SC-999"


# ── 5. POST /admin/scanner/registration-code ──────────────────────────────────

class TestGenerateScannerRegCode:
    def test_invalid_branch_id_empty_string(self):
        app = _make_app(ctx=_ctx("bank_it_admin"))
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/registration-code",
                json={"branch_id": ""},
            )
        assert resp.status_code == 400

    def test_no_db_no_redis_returns_code(self):
        """When DB is absent the branch check is skipped and a code is still generated."""
        app = _make_app(ctx=_ctx("ops_manager"))
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/registration-code",
                json={"branch_id": "BR-01"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["code"]) == 8
        assert body["branch_id"] == "BR-01"
        assert body["bank_id"] == "testbank"
        assert "expires_at" in body

    def test_code_is_alphanumeric_uppercase(self):
        app = _make_app(ctx=_ctx("ops_manager"))
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/registration-code",
                json={"branch_id": "BR-01"},
            )
        body = resp.json()
        assert body["code"].isalnum()
        assert body["code"] == body["code"].upper()

    def test_db_branch_not_found_404(self):
        mock_pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=ctx_mgr)

        app = _make_app(ctx=_ctx("bank_it_admin"))
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/registration-code",
                json={"branch_id": "UNKNOWN-BR"},
            )
        assert resp.status_code == 404

    def test_db_branch_not_sdk_push_mode_400(self):
        row = {"branch_name": "Andheri", "bank_ifsc": "SRWB0000001", "scanner_input_mode": "MANUAL"}
        mock_pool = MagicMock()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=ctx_mgr)

        app = _make_app(ctx=_ctx("bank_it_admin"))
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/registration-code",
                json={"branch_id": "BR-01"},
            )
        assert resp.status_code == 400

    def test_redis_stores_code(self):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.setex = AsyncMock(return_value=True)

        app = _make_app(ctx=_ctx("ops_manager"))
        app.state.redis_client = mock_redis
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/registration-code",
                json={"branch_id": "BR-01"},
            )
        assert resp.status_code == 201
        mock_redis.setex.assert_called_once()


# ── 6. POST /admin/scanner/register ───────────────────────────────────────────

class TestRegisterScanner:
    _valid_reg_data = {
        "bank_id": "testbank",
        "branch_id": "BR-01",
        "branch_name": "Andheri",
        "bank_ifsc": "SRWB0000001",
        "endorsement_text": "PRESENTED BY TESTBANK",
        "enable_imprinter": True,
        "enable_uv_scan": False,
        "mocr_weight": 50,
    }

    def test_invalid_code_format_400(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/register",
                json={"registration_code": "SHORT", "machine_id": "PC-001"},
            )
        assert resp.status_code == 400

    def test_non_alphanumeric_code_400(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/register",
                json={"registration_code": "INVALID!", "machine_id": "PC-001"},
            )
        assert resp.status_code == 400

    def test_no_redis_code_not_found_403(self):
        """Without Redis no code is found — must return 403."""
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/register",
                json={"registration_code": "ABCD1234", "machine_id": "PC-001"},
            )
        assert resp.status_code == 403

    def test_redis_code_not_found_403(self):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])

        app = _make_app()
        app.state.redis_client = mock_redis
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/register",
                json={"registration_code": "ABCD1234", "machine_id": "PC-001"},
            )
        assert resp.status_code == 403

    def test_valid_code_no_db_returns_config(self):
        """Valid code from Redis, no DB → token write skipped, config returned."""
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=["scanner_reg:testbank:ABCD1234"])
        mock_redis.getdel = AsyncMock(return_value=json.dumps(self._valid_reg_data))

        app = _make_app()
        app.state.redis_client = mock_redis
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/register",
                json={"registration_code": "ABCD1234", "machine_id": "PC-ANDHERI-01"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["branch_id"] == "BR-01"
        assert body["bank_ifsc"] == "SRWB0000001"
        assert body["branch_name"] == "Andheri"
        assert body["api_token"].startswith("svc-scanner-")
        assert body["enable_imprinter"] is True
        assert body["enable_uv_scan"] is False
        assert body["mocr_weight"] == 50

    def test_code_is_case_insensitive(self):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=["scanner_reg:testbank:ABCD1234"])
        mock_redis.getdel = AsyncMock(return_value=json.dumps(self._valid_reg_data))

        app = _make_app()
        app.state.redis_client = mock_redis
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/register",
                json={"registration_code": "abcd1234", "machine_id": "PC-001"},  # lowercase input
            )
        assert resp.status_code == 200

    def test_api_url_included_in_response(self):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=["scanner_reg:testbank:ABCD1234"])
        mock_redis.getdel = AsyncMock(return_value=json.dumps(self._valid_reg_data))

        app = _make_app()
        app.state.redis_client = mock_redis
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/admin/scanner/register",
                json={"registration_code": "ABCD1234", "machine_id": "PC-001"},
            )
        body = resp.json()
        assert "api_url" in body
        assert body["api_url"].startswith("http")
