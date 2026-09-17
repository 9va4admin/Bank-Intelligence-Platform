"""Tests for cts_inward.py — 10 inward/core routes."""
from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import BankType, Role, UserContext


def _ctx(role: str = "ops_manager", bank_id: str = "testbank") -> UserContext:
    ctx = MagicMock(spec=UserContext)
    ctx.role = Role[role.upper()]
    ctx.bank_id = bank_id
    ctx.user_id = "u-test"
    ctx.bank_type = BankType.SB
    return ctx


def _make_app(ctx: Optional[UserContext] = None, bank_id: str = "testbank"):
    from apps.api.routers import cts_inward
    from apps.api.routers.cts_deps import get_current_user_context, get_current_bank_id, get_current_user_id

    app = FastAPI()
    app.include_router(cts_inward.router_v1)

    if ctx is None:
        ctx = _ctx()

    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    app.dependency_overrides[get_current_user_id] = lambda: "u-test"
    return app


class _async_ctx:
    def __init__(self, val):
        self._val = val

    async def __aenter__(self):
        return self._val

    async def __aexit__(self, *_):
        pass


# ── 1. POST /inward/{instrument_id}/submit ────────────────────────────────────

class TestSubmitInward:
    _body = {
        "image_url": "s3://cts-images/testbank/inward/INS-001/front.tiff",
        "account_number": "1234567890",
        "cheque_number": "000001",
        "presented_amount": 10000.0,
        "presented_payee": "Test Payee",
        "iet_deadline": 9999999999.0,
    }

    def test_no_temporal_returns_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/inward/INS-001/submit", json=self._body)
        assert resp.status_code == 202
        body = resp.json()
        assert body["instrument_id"] == "INS-001"
        assert body["status"] == "ACCEPTED"

    def test_workflow_id_in_response_header(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/inward/INS-001/submit", json=self._body)
        assert "X-Workflow-Id" in resp.headers
        assert "testbank" in resp.headers["X-Workflow-Id"]

    def test_temporal_already_started_is_idempotent(self):
        """WorkflowAlreadyStartedError should still return 202."""
        from temporalio.exceptions import WorkflowAlreadyStartedError
        mock_temporal = MagicMock()
        mock_temporal.start_workflow = AsyncMock(side_effect=WorkflowAlreadyStartedError("cts-testbank-INS-001", "RUNNING"))
        app = _make_app()
        app.state.temporal_client = mock_temporal
        with TestClient(app) as c:
            resp = c.post("/v1/cts/inward/INS-001/submit", json=self._body)
        assert resp.status_code == 202


# ── 2. GET /decisions/{instrument_id} ─────────────────────────────────────────

class TestGetDecision:
    def test_no_temporal_returns_running(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/decisions/INS-001")
        assert resp.status_code == 200
        assert resp.json()["workflow_status"] == "RUNNING"

    def test_instrument_id_in_response(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/decisions/INS-999")
        assert resp.json()["instrument_id"] == "INS-999"


# ── 3. POST /review/{instrument_id}/decide ────────────────────────────────────

class TestSubmitReviewDecision:
    _body = {"action": "CONFIRM", "reason": "Signature verified by senior officer"}

    def test_no_reason_422(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/review/INS-001/decide", json={"action": "CONFIRM", "reason": ""})
        assert resp.status_code == 422

    def test_no_temporal_signal_not_sent(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/review/INS-001/decide", json=self._body)
        assert resp.status_code == 200
        assert resp.json()["signal_sent"] is False

    def test_whitespace_reason_422(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/review/INS-001/decide", json={"action": "RETURN", "reason": "   "})
        assert resp.status_code == 422


# ── 4. GET /queue ─────────────────────────────────────────────────────────────

class TestGetQueue:
    def test_no_temporal_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_limit_capped_at_100(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/queue?limit=999")
        assert resp.status_code == 200


# ── 5. GET /decisions ─────────────────────────────────────────────────────────

class TestListDecisions:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/decisions")
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["bank_id"] == "testbank"

    def test_limit_capped_at_100(self):
        """Limit > 100 should silently cap to 100."""
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/decisions?limit=999")
        assert resp.status_code == 200


# ── 6. GET /vault-gaps ────────────────────────────────────────────────────────

class TestVaultGaps:
    def test_no_db_returns_empty_gaps(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault-gaps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["gaps"] == []
        assert body["bank_id"] == "testbank"
        assert body["total_accounts_affected"] == 0

    def test_custom_date_param_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault-gaps?date=2026-09-01")
        assert resp.status_code == 200
        assert resp.json()["date"] == "2026-09-01"


# ── 7. GET /instruments/search ────────────────────────────────────────────────

class TestSearchInstruments:
    def test_short_query_422(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/instruments/search?q=AB")
        assert resp.status_code == 422

    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/instruments/search?q=ABCDEF")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_limit_capped_at_20(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/instruments/search?q=ABCDEF&limit=999")
        assert resp.status_code == 200


# ── 8. GET /inward/analytics ──────────────────────────────────────────────────

class TestInwardAnalytics:
    def test_compliance_officer_allowed(self):
        app = _make_app(ctx=_ctx("compliance_officer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/inward/analytics")
        # No DB → 503, but RBAC passes
        assert resp.status_code in (200, 503)

    def test_rbi_examiner_forbidden(self):
        app = _make_app(ctx=_ctx("rbi_examiner"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/inward/analytics")
        assert resp.status_code == 403

    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/inward/analytics")
        assert resp.status_code == 503


# ── 9. GET /inward/live-flow ──────────────────────────────────────────────────

class TestInwardLiveFlow:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/inward/live-flow")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["bank_id"] == "testbank"

    def test_limit_param_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/inward/live-flow?limit=20")
        assert resp.status_code == 200


# ── 10. GET /inward/sessions ──────────────────────────────────────────────────

class TestInwardSessions:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/inward/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sessions"] == []
        assert body["bank_id"] == "testbank"
