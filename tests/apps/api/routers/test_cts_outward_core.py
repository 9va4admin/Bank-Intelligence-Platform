"""
Tests for cts_outward_core.py — 14 outward core routes.

Routes tested:
  POST /v1/cts/outward/scan/upload-url
  GET  /v1/cts/outward/scan/image
  POST /v1/cts/outward/scan/submit
  GET  /v1/cts/outward/hub-summary
  PATCH /v1/cts/outward/lots/{lot_id}/seal
  POST /v1/cts/outward/lots/seal-all
  GET  /v1/cts/outward/sessions/{session_id}/report
  POST /v1/cts/vault/upload/{vault_type}
  GET  /v1/cts/vault/batches/{batch_id}
  GET  /v1/cts/vault/batches/{batch_id}/errors.csv
  POST /v1/cts/outward/scanner/session/open
  POST /v1/cts/outward/scanner/session/close
  POST /v1/cts/outward/clearing-session/submit
  GET  /v1/cts/outward/clearing-window
"""
from __future__ import annotations

import io
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

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
    from apps.api.routers import cts_outward_core
    from apps.api.routers.cts_deps import (
        get_current_user_context,
        get_current_bank_id,
    )

    app = FastAPI()
    app.include_router(cts_outward_core.router_v1)

    if ctx is None:
        ctx = _ctx()

    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    return app


def _make_scanner_app(bank_id: str = "testbank"):
    """App where scan routes (using get_bank_id_scanner_or_user) are accessible."""
    from apps.api.routers import cts_outward_core
    from apps.api.routers.cts_deps import (
        get_current_user_context,
        get_bank_id_scanner_or_user,
    )

    app = FastAPI()
    app.include_router(cts_outward_core.router_v1)
    app.dependency_overrides[get_bank_id_scanner_or_user] = lambda: bank_id
    app.dependency_overrides[get_current_user_context] = lambda: _ctx()
    return app


class _async_ctx:
    def __init__(self, val):
        self._val = val

    async def __aenter__(self):
        return self._val

    async def __aexit__(self, *_):
        pass


# ── 1. POST /outward/scan/upload-url ─────────────────────────────────────────

class TestScanUploadURL:
    _body = {"scan_id": "SCAN-001", "include_uv": False}

    def test_no_minio_returns_placeholder_urls(self):
        app = _make_scanner_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/upload-url", json=self._body)
        assert resp.status_code == 200
        body = resp.json()
        assert "SCAN-001" in body["front_presigned_url"]
        assert "SCAN-001" in body["rear_presigned_url"]
        assert body["uv_presigned_url"] is None

    def test_include_uv_returns_uv_url(self):
        app = _make_scanner_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/upload-url", json={"scan_id": "SCAN-001", "include_uv": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["uv_presigned_url"] is not None
        assert body["uv_object_url"] is not None

    def test_minio_error_raises_503(self):
        mock_store = MagicMock()
        mock_store.presigned_put_url = AsyncMock(side_effect=Exception("MinIO down"))
        app = _make_scanner_app()
        app.state.minio_store = mock_store
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/upload-url", json=self._body)
        assert resp.status_code == 503


# ── 2. GET /outward/scan/image ────────────────────────────────────────────────

class TestScanImage:
    def test_no_minio_raises_503(self):
        app = _make_scanner_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/scan/image?scan_id=SCAN-001&view=front_bw")
        assert resp.status_code == 503

    def test_minio_image_not_found_raises_404(self):
        mock_store = MagicMock()
        mock_store.download_bytes = AsyncMock(side_effect=Exception("not found"))
        app = _make_scanner_app()
        app.state.minio_store = mock_store
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/scan/image?scan_id=SCAN-001&view=front_bw")
        assert resp.status_code == 404


# ── 3. POST /outward/scan/submit ──────────────────────────────────────────────

class TestScanSubmit:
    _body = {
        "scan_id": "SCAN-001",
        "instrument_id": "INS-SCAN-001",
        "bank_ifsc": "SBIN0001234",
        "session_id": "SES-001",
        "image_front_url": "s3://cts-images/testbank/outward/SCAN-001/front.tiff",
        "image_rear_url": "s3://cts-images/testbank/outward/SCAN-001/rear.tiff",
    }

    def test_no_temporal_returns_accepted(self):
        app = _make_scanner_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/submit", json=self._body)
        assert resp.status_code == 202
        body = resp.json()
        assert body["scan_id"] == "SCAN-001"
        assert body["status"] == "ACCEPTED"
        assert body["path"] == "LEGACY"

    def test_with_micr_uses_cr120_path(self):
        body = {**self._body, "micr_hardware_raw": "123456789012345678"}
        app = _make_scanner_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/submit", json=body)
        assert resp.status_code == 202
        assert resp.json()["path"] == "CR120"

    def test_workflow_id_in_response_header(self):
        app = _make_scanner_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scan/submit", json=self._body)
        assert "X-Workflow-Id" in resp.headers


# ── 4. GET /outward/hub-summary ───────────────────────────────────────────────

class TestHubSummary:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/hub-summary")
        assert resp.status_code == 403

    def test_ops_manager_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/hub-summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["branches"] == []
        assert body["total_branches"] == 0

    def test_db_error_raises_500(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=Exception("DB error"))
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/hub-summary")
        assert resp.status_code == 500


# ── 5. PATCH /outward/lots/{lot_id}/seal ─────────────────────────────────────

class TestSealLot:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.patch("/v1/cts/outward/lots/LOT-001/seal")
        assert resp.status_code == 403

    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.patch("/v1/cts/outward/lots/LOT-001/seal")
        assert resp.status_code == 503

    def test_lot_not_found_raises_404(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.patch("/v1/cts/outward/lots/LOT-999/seal")
        assert resp.status_code == 404

    def test_already_sealed_raises_409(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "lot_id": "LOT-001", "bank_id": "testbank", "status": "SEALED", "instrument_count": 10
        })
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.patch("/v1/cts/outward/lots/LOT-001/seal")
        assert resp.status_code == 409


# ── 6. POST /outward/lots/seal-all ───────────────────────────────────────────

class TestSealAllLots:
    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/lots/seal-all")
        assert resp.status_code == 403

    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/lots/seal-all")
        assert resp.status_code == 503

    def test_seals_all_open_lots(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"lot_id": "LOT-001"}, {"lot_id": "LOT-002"}
        ])
        mock_conn.execute = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/lots/seal-all")
        assert resp.status_code == 200
        assert resp.json()["sealed"] == 2


# ── 7. GET /outward/sessions/{session_id}/report ──────────────────────────────

class TestSessionReport:
    def test_fraud_analyst_allowed(self):
        # fraud_analyst is in allowed set; no db → 503
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/sessions/SESS-001/report")
        assert resp.status_code == 503

    def test_compliance_officer_forbidden(self):
        app = _make_app(ctx=_ctx("compliance_officer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/sessions/SESS-001/report")
        assert resp.status_code == 403

    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/sessions/SESS-001/report")
        assert resp.status_code == 503


# ── 8. POST /vault/upload/{vault_type} ───────────────────────────────────────

class TestVaultUpload:
    def test_unknown_vault_type_422(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/vault/upload/UNKNOWN_TYPE",
                files={"file": ("test.csv", b"col1,col2\nval1,val2", "text/csv")},
            )
        assert resp.status_code == 422

    def test_empty_file_422(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("empty.csv", b"", "text/csv")},
            )
        assert resp.status_code == 422

    def test_fraud_analyst_allowed(self):
        """VaultUpload has no role check — any authenticated user can upload (bank scoped)."""
        from unittest.mock import patch as _patch

        mock_result = MagicMock()
        mock_result.batch_id = "BATCH-001"
        mock_result.rows_total = 1
        mock_result.rows_processed = 1
        mock_result.rows_failed = 0
        mock_result.errors = []

        mock_processor = MagicMock()
        mock_processor.process = AsyncMock(return_value=mock_result)

        app = _make_app(ctx=_ctx("fraud_analyst"))
        with _patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor", return_value=mock_processor), \
             _patch("apps.api.routers.cts_outward_core.VaultUploadProcessor", mock_processor, create=True):
            with TestClient(app) as c:
                resp = c.post(
                    "/v1/cts/vault/upload/PPS",
                    files={"file": ("test.csv", b"col1,col2\nval1,val2", "text/csv")},
                )
        assert resp.status_code == 200
        assert resp.json()["vault_type"] == "PPS"


# ── 9. GET /vault/batches/{batch_id} ─────────────────────────────────────────

class TestVaultBatchStatus:
    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/batches/BATCH-001")
        assert resp.status_code == 503


# ── 10. GET /vault/batches/{batch_id}/errors.csv ─────────────────────────────

class TestVaultBatchErrorsCSV:
    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/vault/batches/BATCH-001/errors.csv")
        assert resp.status_code == 503


# ── 11. POST /outward/scanner/session/open ────────────────────────────────────

class TestScannerSessionOpen:
    _body = {"branch_id": "BR-01", "hub_type": "EEH", "cert_fingerprint": "ABCD1234"}

    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scanner/session/open", json=self._body)
        assert resp.status_code == 403

    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scanner/session/open", json=self._body)
        assert resp.status_code == 503

    def test_existing_session_409(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"session_id": "SES-EXISTING"})
        mock_conn.execute = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scanner/session/open", json=self._body)
        assert resp.status_code == 409


# ── 12. POST /outward/scanner/session/close ───────────────────────────────────

class TestScannerSessionClose:
    _body = {"session_id": "SES-001"}

    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scanner/session/close", json=self._body)
        assert resp.status_code == 403

    def test_no_db_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scanner/session/close", json=self._body)
        assert resp.status_code == 503

    def test_session_not_found_404(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scanner/session/close", json=self._body)
        assert resp.status_code == 404

    def test_cross_bank_close_forbidden(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "session_id": "SES-001", "status": "ACTIVE", "bank_id": "otherbank"
        })
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_async_ctx(mock_conn))
        app = _make_app(bank_id="testbank")
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/scanner/session/close", json=self._body)
        assert resp.status_code == 403


# ── 13. POST /outward/clearing-session/submit ─────────────────────────────────

class TestClearingSessionSubmit:
    _body = {
        "clearing_date": "2026-09-12",
        "session_type": "MORNING",
        "deployment_mode": "SB_NGCH",
        "pu_ids": [],
    }

    def test_ops_reviewer_forbidden(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/clearing-session/submit", json=self._body)
        assert resp.status_code == 403

    def test_no_temporal_raises_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/outward/clearing-session/submit", json=self._body)
        assert resp.status_code == 503


# ── 14. GET /outward/clearing-window ─────────────────────────────────────────

class TestClearingWindow:
    def test_any_role_gets_window(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/clearing-window")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert "open_time_utc" in body
        assert "close_time_utc" in body
        assert "is_open" in body
        assert "clearing_date" in body

    def test_response_fields_valid_format(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/outward/clearing-window")
        body = resp.json()
        assert ":" in body["open_time_utc"]
        assert isinstance(body["is_open"], bool)
