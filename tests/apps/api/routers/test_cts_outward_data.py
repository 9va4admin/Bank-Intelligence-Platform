"""
Tests for cts_outward_data.py — 17 outward data routes.

Routes tested:
  POST /v1/cts/endorsement/batch
  GET  /v1/cts/outward/files/{filename}/download-url
  POST /v1/cts/iqa/{scan_id}/rescan
  GET  /v1/cts/sessions/{session_id}/download/{report_type}
  GET  /v1/cts/outward/human-review-queue
  POST /v1/cts/outward/review/{instrument_id}/decide
  GET  /v1/cts/outward/settlement
  GET  /v1/cts/outward/lots/{lot_id}/instruments
  GET  /v1/cts/outward/analytics/daily
  GET  /v1/cts/outward/reconciliation
  GET  /v1/cts/outward/lots
  GET  /v1/cts/outward/sessions
  GET  /v1/cts/outward/compliance
  GET  /v1/cts/outward/endorsement-queue
  GET  /v1/cts/outward/decisions
  GET  /v1/cts/outward/iqa-results
  GET  /v1/cts/outward/pipeline
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
    from apps.api.routers import cts_outward_data
    from apps.api.routers.cts_deps import (
        get_current_user_context,
        get_current_bank_id,
    )

    app = FastAPI()
    app.include_router(cts_outward_data.router_v1)

    if ctx is None:
        ctx = _ctx()

    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    return app


# ── 1. POST /endorsement/batch ────────────────────────────────────────────────

class TestEndorsementBatch:
    _body = {
        "lot_number": "LOT-001",
        "instrument_ids": ["INST-001", "INST-002"],
        "bank_ifsc": "SBIN0001234",
        "session_id": "SESS-001",
    }

    def test_ops_reviewer_forbidden(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/endorsement/batch", json=self._body)
        assert resp.status_code == 403

    def test_ops_manager_no_temporal_returns_triggered(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/endorsement/batch", json=self._body)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "TRIGGERED"
        assert body["lot_number"] == "LOT-001"
        assert body["instrument_count"] == 2

    def test_workflow_id_contains_bank_id_and_lot(self):
        app = _make_app(ctx=_ctx("ops_manager", bank_id="mybank"), bank_id="mybank")
        with TestClient(app) as c:
            resp = c.post("/v1/cts/endorsement/batch", json=self._body)
        body = resp.json()
        assert "mybank" in body["workflow_id"]
        assert "LOT-001" in body["workflow_id"]

    def test_temporal_error_raises_503(self):
        mock_tc = MagicMock()
        mock_tc.start_workflow = AsyncMock(side_effect=Exception("Temporal down"))
        app = _make_app()
        app.state.temporal_client = mock_tc
        with TestClient(app) as c:
            resp = c.post("/v1/cts/endorsement/batch", json=self._body)
        assert resp.status_code == 503


# ── 2. GET /outward/files/{filename}/download-url ─────────────────────────────

class TestOutwardFileDownload:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/files/lot001.zip/download-url")
        assert resp.status_code == 403

    def test_ops_manager_no_minio_returns_placeholder(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/files/lot001.zip/download-url")
        assert resp.status_code == 200
        body = resp.json()
        assert "lot001.zip" in body["download_url"]
        assert body["filename"] == "lot001.zip"

    def test_ops_reviewer_allowed(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/files/lot001.zip/download-url")
        assert resp.status_code == 200


# ── 3. POST /iqa/{scan_id}/rescan ─────────────────────────────────────────────

class TestIQARescan:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/iqa/SCAN-001/rescan")
        assert resp.status_code == 403

    def test_ops_manager_no_temporal_returns_triggered(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/iqa/SCAN-001/rescan")
        assert resp.status_code == 202
        body = resp.json()
        assert body["scan_id"] == "SCAN-001"
        assert body["status"] == "TRIGGERED"
        assert "workflow_id" in body

    def test_temporal_error_raises_503(self):
        mock_tc = MagicMock()
        mock_tc.start_workflow = AsyncMock(side_effect=Exception("Temporal down"))
        app = _make_app()
        app.state.temporal_client = mock_tc
        with TestClient(app) as c:
            resp = c.post("/v1/cts/iqa/SCAN-001/rescan")
        assert resp.status_code == 503


# ── 4. GET /sessions/{session_id}/download/{report_type} ─────────────────────

class TestSessionDownload:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/sessions/SESS-001/download/npci")
        assert resp.status_code == 403

    def test_unknown_report_type_422(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/sessions/SESS-001/download/invalid_type")
        assert resp.status_code == 422

    def test_valid_type_no_minio_returns_placeholder(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/sessions/SESS-001/download/npci")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "SESS-001"
        assert body["report_type"] == "npci"
        assert "SESS-001" in body["download_url"]

    def test_mis_and_settlement_types_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            for report_type in ("mis", "settlement"):
                resp = c.get(f"/v1/cts/sessions/SESS-001/download/{report_type}")
                assert resp.status_code == 200


# ── 5. GET /outward/human-review-queue ───────────────────────────────────────

class TestOutwardHumanReviewQueue:
    def test_compliance_officer_forbidden(self):
        app = _make_app(ctx=_ctx("compliance_officer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/human-review-queue")
        assert resp.status_code == 403

    def test_ops_reviewer_no_db_returns_empty(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/human-review-queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["items"] == []
        assert body["total"] == 0

    def test_db_error_raises_503(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/human-review-queue")
        assert resp.status_code == 503

    def test_with_rows_returned(self):
        row = {
            "instrument_id": "INST-001",
            "cheque_number": "SCAN-001",
            "account_display": None,
            "payee_display": "Test Co",
            "amount_range": "₹[1L-5L]",
            "status": "HUMAN_REVIEW",
            "fraud_score": None,
            "ocr_confidence": None,
            "review_reason": "Low confidence",
            "received_at": "2026-09-12T10:00:00",
            "branch_id": "BR-01",
            "lot_id": "LOT-001",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/human-review-queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["outcome"] == "HUMAN_REVIEW"


# ── 6. POST /outward/review/{instrument_id}/decide ────────────────────────────

class TestOutwardReviewDecide:
    _body = {"action": "CONFIRMED", "reason": "All fields match", "reason_category": "manual"}

    def test_compliance_officer_forbidden(self):
        app = _make_app(ctx=_ctx("compliance_officer"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/review/INST-001/decide", json=self._body)
        assert resp.status_code == 403

    def test_ops_manager_no_temporal_succeeds(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/review/INST-001/decide", json=self._body)
        assert resp.status_code == 200
        body = resp.json()
        assert body["instrument_id"] == "INST-001"
        assert body["action"] == "CONFIRMED"
        assert body["workflow_signal_sent"] is False

    def test_rejected_action_accepted(self):
        app = _make_app()
        reject_body = {"action": "REJECTED", "reason": "Forgery suspected", "reason_category": "fraud"}
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/review/INST-001/decide", json=reject_body)
        assert resp.status_code == 200
        assert resp.json()["action"] == "REJECTED"


# ── 7. GET /outward/settlement ────────────────────────────────────────────────

class TestOutwardSettlement:
    def test_ops_reviewer_forbidden(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/settlement")
        assert resp.status_code == 403

    def test_ops_manager_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/settlement")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["sessions"] == []
        assert body["total_instruments"] == 0

    def test_date_filter_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/settlement?clearing_date=2026-09-12")
        assert resp.status_code == 200
        assert resp.json()["clearing_date"] == "2026-09-12"

    def test_db_error_raises_503(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/settlement")
        assert resp.status_code == 503


# ── 8. GET /outward/lots/{lot_id}/instruments ─────────────────────────────────

class TestLotInstruments:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/lots/LOT-001/instruments")
        assert resp.status_code == 403

    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/lots/LOT-001/instruments")
        assert resp.status_code == 503

    def test_lot_not_found_raises_404(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/lots/LOT-999/instruments")
        assert resp.status_code == 404

    def test_cross_bank_lot_raises_403(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "lot_id": "LOT-001",
            "bank_id": "otherbank",
            "status": "OPEN",
            "instrument_count": 5,
        })
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app(bank_id="testbank")
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/lots/LOT-001/instruments")
        assert resp.status_code == 403


# ── 9. GET /outward/analytics/daily ──────────────────────────────────────────

class TestOutwardAnalyticsDaily:
    def test_compliance_officer_forbidden(self):
        app = _make_app(ctx=_ctx("compliance_officer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/analytics/daily")
        assert resp.status_code == 403

    def test_ops_manager_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/analytics/daily")
        assert resp.status_code == 503

    def test_days_param_clamped(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/analytics/daily?days=999")
        assert resp.status_code == 200
        assert resp.json()["days"] == 30


# ── 10. GET /outward/reconciliation ──────────────────────────────────────────

class TestOutwardReconciliation:
    def test_ops_reviewer_forbidden(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/reconciliation")
        assert resp.status_code == 403

    def test_ops_manager_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/reconciliation")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["sessions"] == []
        assert body["discrepancies"] == []

    def test_date_filter_in_response(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/reconciliation?recon_date=2026-09-12")
        assert resp.json()["recon_date"] == "2026-09-12"

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/reconciliation")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []


# ── 11. GET /outward/lots ──────────────────────────────────────────────────────

class TestOutwardLots:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/lots")
        assert resp.status_code == 403

    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/lots")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["lots"] == []

    def test_clearing_date_filter_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/lots?clearing_date=2026-09-12")
        assert resp.status_code == 200
        assert resp.json()["clearing_date"] == "2026-09-12"


# ── 12. GET /outward/sessions ─────────────────────────────────────────────────

class TestClearingSessions:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["sessions"] == []
        assert body["total"] == 0

    def test_any_role_allowed(self):
        for role in ("ops_manager", "ops_reviewer", "bank_it_admin"):
            app = _make_app(ctx=_ctx(role))
            with TestClient(app) as c:
                resp = c.get("/v1/cts/outward/sessions")
            assert resp.status_code == 200

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/sessions")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []


# ── 13. GET /outward/compliance ───────────────────────────────────────────────

class TestOutwardCompliance:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/compliance")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["items"] == []
        assert body["total_checked"] == 0

    def test_result_filter_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/compliance?result=FAIL")
        assert resp.status_code == 200

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        mock_pool.fetchrow = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/compliance")
        assert resp.status_code == 200
        assert resp.json()["total_checked"] == 0


# ── 14. GET /outward/endorsement-queue ───────────────────────────────────────

class TestEndorsementQueue:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/endorsement-queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["items"] == []
        assert body["total"] == 0

    def test_any_role_allowed(self):
        for role in ("ops_manager", "ops_reviewer"):
            app = _make_app(ctx=_ctx(role))
            with TestClient(app) as c:
                resp = c.get("/v1/cts/outward/endorsement-queue")
            assert resp.status_code == 200

    def test_with_rows(self):
        row = {
            "instrument_id": "INST-001",
            "cheque_number": "100001",
            "account_suffix": "4321",
            "lot_number": "LOT-001",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/endorsement-queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == "INST-001"


# ── 15. GET /outward/decisions ────────────────────────────────────────────────

class TestOutwardDecisions:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/decisions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["items"] == []
        assert body["total"] == 0

    def test_outcome_filter_accepted(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/decisions?outcome=STP_CONFIRM")
        assert resp.status_code == 200

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/decisions")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


# ── 16. GET /outward/iqa-results ──────────────────────────────────────────────

class TestIQAResults:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/iqa-results")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["items"] == []
        assert body["total"] == 0

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/iqa-results")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_with_rows_account_masked(self):
        row = {
            "instrument_id": "INST-001",
            "account_suffix": "4321",
            "lot_number": "LOT-001",
            "scanner_id": "SCAN-01",
            "iqa_status": "IQA_PASS",
            "iqa_fail_reason": None,
            "scanned_at": None,
            "ocr_confidence": 0.97,
            "scan_dpi": 200,
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/iqa-results")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert "****4321" == body["items"][0]["account"]


# ── 17. GET /outward/pipeline ─────────────────────────────────────────────────

class TestOutwardPipeline:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/pipeline")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["instruments"] == []

    def test_db_error_raises_503(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/pipeline")
        assert resp.status_code == 503

    def test_with_rows_stage_mapped(self):
        row = {
            "instrument_id": "INST-001",
            "scan_id": "SCAN-001",
            "payee_display": "Test Co",
            "amount_range": "₹[1L-5L]",
            "outcome": "NGCH_FILED",
            "lot_id": "LOT-001",
            "branch_id": "BR-01",
            "reject_reason": None,
            "scanned_at": "2026-09-12T10:00:00",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/pipeline")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["instruments"]) == 1
        assert body["instruments"][0]["stage"] == "NGCH"


# ── Helpers ───────────────────────────────────────────────────────────────────

class _async_ctx:
    """Async context manager returning the given value."""
    def __init__(self, val):
        self._val = val

    async def __aenter__(self):
        return self._val

    async def __aexit__(self, *_):
        pass
