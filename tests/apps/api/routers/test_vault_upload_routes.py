"""
Route-level tests for vault upload endpoints in apps/api/routers/cts.py.

Surfaces under test (HTTP boundary only — processor logic tested separately):
  POST /v1/cts/vault/upload/{vault_type}   → upload_vault_csv
  GET  /v1/cts/vault/batches/{batch_id}    → get_vault_batch_status
  GET  /v1/cts/vault/batches/{batch_id}/errors.csv → download_vault_batch_errors

Every test verifies exactly one concern at the HTTP layer:
  - Auth enforcement (401 / proceeds)
  - Input validation (422 with typed error_code)
  - Response schema correctness
  - bank_id always from JWT, never from request body or CSV
  - Cross-bank isolation (404, not 403, per IDOR fix)
  - Kafka notification published only when rows_failed > 0
"""
from __future__ import annotations

import json
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

BANK_ID = "saraswat-coop"
USER_ID  = "nilesh.shah"


def _ctx(bank_id: str = BANK_ID, role: Role = Role.OPS_MANAGER) -> UserContext:
    return UserContext(
        user_id=USER_ID,
        role=role,
        bank_id=bank_id,
        bank_type=BankType.SB,
        permission_level=PermissionLevel.EDIT,
    )


def _make_app(bank_id: str = BANK_ID) -> FastAPI:
    from apps.api.routers.cts import router_v1, get_current_user_context
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user_context] = lambda: _ctx(bank_id)
    return app


def _pps_csv(n: int = 3) -> bytes:
    lines = ["account_number,cheque_number,cheque_date,amount,payee_name,action"]
    for i in range(1, n + 1):
        lines.append(f"ACC{i:09d},{i:06d},2026-09-01,{i * 1000}.00,Payee {i},UPSERT")
    return "\n".join(lines).encode()


def _make_upload_result(
    batch_id: str = "batch-uuid-001",
    rows_total: int = 3,
    rows_processed: int = 3,
    rows_failed: int = 0,
    errors: list | None = None,
):
    """Returns a fake VaultUploadResult-like object."""
    r = MagicMock()
    r.batch_id = batch_id
    r.rows_total = rows_total
    r.rows_processed = rows_processed
    r.rows_failed = rows_failed
    r.errors = errors or []
    return r


# ---------------------------------------------------------------------------
# 1. Authentication
# ---------------------------------------------------------------------------

class TestVaultUploadAuth:
    def test_unauthenticated_upload_returns_401(self):
        """No auth → 401. The route requires get_current_user_context."""
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)   # no dependency override → real auth
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/vault/upload/PPS",
            files={"file": ("pps.csv", _pps_csv(), "text/csv")},
        )
        assert response.status_code == 401

    def test_unauthenticated_batch_status_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/cts/vault/batches/some-batch-id")
        assert response.status_code == 401

    def test_unauthenticated_errors_csv_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/cts/vault/batches/some-batch-id/errors.csv")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2. vault_type validation
# ---------------------------------------------------------------------------

class TestVaultTypeValidation:
    def test_unknown_vault_type_returns_422(self):
        """GARBAGE is not a valid vault_type → 422 VAULT_UNKNOWN_TYPE."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/v1/cts/vault/upload/GARBAGE",
            files={"file": ("x.csv", b"a,b\n1,2", "text/csv")},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["detail"]["error_code"] == "VAULT_UNKNOWN_TYPE"

    def test_lowercase_vault_type_accepted(self):
        """'pps' should be uppercased internally → accepted."""
        app = _make_app()
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=_make_upload_result())
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/v1/cts/vault/upload/pps",
                files={"file": ("pps.csv", _pps_csv(), "text/csv")},
            )
        assert response.status_code == 200
        assert response.json()["vault_type"] == "PPS"

    def test_empty_file_returns_422(self):
        """Zero-byte file → 422 VAULT_EMPTY_FILE."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/v1/cts/vault/upload/PPS",
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["error_code"] == "VAULT_EMPTY_FILE"

    def test_all_five_valid_vault_types_accepted(self):
        """Sanity: all 5 vault types produce 200, not 422."""
        app = _make_app()
        for vtype in ("PPS", "CHEQUE_BOOK", "LEAF_STATUS", "ACCOUNT_DETAIL", "SIGNATURE"):
            with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
                MockProc.return_value.process = AsyncMock(return_value=_make_upload_result())
                client = TestClient(app, raise_server_exceptions=False)
                r = client.post(
                    f"/v1/cts/vault/upload/{vtype}",
                    files={"file": ("x.csv", b"col\nval", "text/csv")},
                )
            assert r.status_code == 200, f"{vtype} should be accepted, got {r.status_code}"


# ---------------------------------------------------------------------------
# 3. Happy path — response schema, db_table, bank_id isolation
# ---------------------------------------------------------------------------

class TestVaultUploadHappyPath:
    def _upload(self, vault_type="PPS", bank_id=BANK_ID, rows=3, errors=None):
        app = _make_app(bank_id=bank_id)
        result = _make_upload_result(rows_total=rows, rows_processed=rows, errors=errors or [])
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/v1/cts/vault/upload/{vault_type}",
                files={"file": ("upload.csv", _pps_csv(rows), "text/csv")},
            )
        return response

    def test_happy_path_returns_200(self):
        assert self._upload().status_code == 200

    def test_response_has_batch_id(self):
        body = self._upload().json()
        assert body["batch_id"] == "batch-uuid-001"

    def test_response_has_vault_type(self):
        assert self._upload("PPS").json()["vault_type"] == "PPS"

    def test_pps_db_table_is_pps_vault_entries(self):
        assert self._upload("PPS").json()["db_table"] == "cts.pps_vault_entries"

    def test_cheque_book_db_table_correct(self):
        assert self._upload("CHEQUE_BOOK").json()["db_table"] == "cts.cheque_books"

    def test_leaf_status_db_table_correct(self):
        assert self._upload("LEAF_STATUS").json()["db_table"] == "cts.cheque_leaves"

    def test_account_detail_db_table_correct(self):
        assert self._upload("ACCOUNT_DETAIL").json()["db_table"] == "cts.account_vault_detail"

    def test_signature_db_table_correct(self):
        assert self._upload("SIGNATURE").json()["db_table"] == "cts.account_signatories"

    def test_all_valid_rows_gives_complete_status(self):
        assert self._upload().json()["status"] == "COMPLETE"

    def test_row_counts_propagated(self):
        body = self._upload(rows=10).json()
        assert body["rows_total"]     == 10
        assert body["rows_processed"] == 10
        assert body["rows_failed"]    == 0

    def test_bank_id_passed_to_processor_from_jwt_not_csv(self):
        """Processor constructor must receive bank_id from ctx, never from file content."""
        app = _make_app(bank_id="federal-bank")
        result = _make_upload_result()
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(), "text/csv")},
            )
            # bank_id is the FIRST positional arg to VaultUploadProcessor()
            call_kwargs = MockProc.call_args
            assert call_kwargs.kwargs.get("bank_id") == "federal-bank" or \
                   call_kwargs.args[0] == "federal-bank"

    def test_changed_by_includes_user_id_from_jwt(self):
        """changed_by must be 'user:{user_id}' — never empty or hardcoded."""
        app = _make_app()
        result = _make_upload_result()
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(), "text/csv")},
            )
            process_call = MockProc.return_value.process.call_args
            changed_by = process_call.kwargs.get("changed_by") or process_call.args[1]
            assert changed_by == f"user:{USER_ID}"

    def test_upload_channel_is_ui_not_sftp(self):
        """UI path must set upload_channel='UI' — distinguishes from SFTP file drop."""
        app = _make_app()
        result = _make_upload_result()
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(), "text/csv")},
            )
            process_call = MockProc.return_value.process.call_args
            channel = process_call.kwargs.get("upload_channel")
            assert channel == "UI"

    def test_errors_preview_empty_on_clean_batch(self):
        body = self._upload().json()
        assert body["errors_preview"] == []

    def test_kafka_not_published_when_zero_failures(self):
        """No PARTIAL notification when all rows succeed."""
        app = _make_app()
        result = _make_upload_result(rows_failed=0)
        kafka = MagicMock()
        app.state.kafka_producer = kafka
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(), "text/csv")},
            )
        kafka.publish.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Partial batch
# ---------------------------------------------------------------------------

class TestVaultUploadPartialBatch:
    def _partial_upload(self, rows_total=10, rows_processed=7, rows_failed=3):
        app = _make_app()
        errors = [{"row": i + 2, "error": f"bad row {i}"} for i in range(rows_failed)]
        result = _make_upload_result(
            rows_total=rows_total, rows_processed=rows_processed,
            rows_failed=rows_failed, errors=errors,
        )
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(rows_total), "text/csv")},
            )
        return response

    def test_partial_batch_returns_partial_status(self):
        assert self._partial_upload().json()["status"] == "PARTIAL"

    def test_partial_batch_rows_failed_in_response(self):
        body = self._partial_upload(rows_failed=3).json()
        assert body["rows_failed"] == 3
        assert body["rows_processed"] == 7

    def test_errors_preview_capped_at_20(self):
        """Inline errors_preview shows at most 20 rows — full list at /errors.csv."""
        app = _make_app()
        errors = [{"row": i + 2, "error": f"err {i}"} for i in range(50)]
        result = _make_upload_result(rows_total=50, rows_processed=0, rows_failed=50, errors=errors)
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(50), "text/csv")},
            )
        assert len(r.json()["errors_preview"]) == 20

    def test_all_rows_failed_gives_failed_status(self):
        app = _make_app()
        result = _make_upload_result(rows_total=5, rows_processed=0, rows_failed=5,
                                     errors=[{"row": i, "error": "bad"} for i in range(1, 6)])
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(5), "text/csv")},
            )
        assert r.json()["status"] == "FAILED"

    def test_kafka_published_when_rows_failed_gt_zero(self):
        """PARTIAL/FAILED batch → Kafka notification must fire."""
        app = _make_app()
        result = _make_upload_result(rows_total=10, rows_processed=7, rows_failed=3,
                                     errors=[{"row": 2, "error": "bad"}])
        kafka = MagicMock()
        app.state.kafka_producer = kafka
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(return_value=result)
            client = TestClient(app, raise_server_exceptions=False)
            client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", _pps_csv(10), "text/csv")},
            )
        kafka.publish.assert_called_once()


# ---------------------------------------------------------------------------
# 5. CSV parse error (processor raises ValueError)
# ---------------------------------------------------------------------------

class TestVaultUploadParseError:
    def test_processor_value_error_returns_422(self):
        app = _make_app()
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(
                side_effect=ValueError("CSV missing required columns: {'cheque_number'}")
            )
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", b"bad,csv\n1,2", "text/csv")},
            )
        assert r.status_code == 422
        assert r.json()["detail"]["error_code"] == "VAULT_PARSE_ERROR"

    def test_parse_error_message_in_response(self):
        app = _make_app()
        with patch("modules.cts.vaults.vault_upload_processor.VaultUploadProcessor") as MockProc:
            MockProc.return_value.process = AsyncMock(
                side_effect=ValueError("missing required columns")
            )
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/v1/cts/vault/upload/PPS",
                files={"file": ("pps.csv", b"bad,csv\n1,2", "text/csv")},
            )
        assert "missing required columns" in r.json()["detail"]["message"]


# ---------------------------------------------------------------------------
# 6. GET /vault/batches/{batch_id}
# ---------------------------------------------------------------------------

def _mock_db_pool_with_batch(batch_id="batch-uuid-001", bank_id=BANK_ID,
                              vault_type="PPS", status="COMPLETE",
                              rows_total=10, rows_processed=10, rows_failed=0,
                              errors_json=None):
    """Returns a MagicMock db_pool whose conn.fetchrow returns a realistic batch row."""
    row = {
        "id": batch_id, "bank_id": bank_id, "vault_type": vault_type,
        "filename": "upload_20260819.csv",
        "upload_channel": "UI",
        "uploaded_by": f"user:{USER_ID}",
        "status": status, "rows_total": rows_total,
        "rows_processed": rows_processed, "rows_failed": rows_failed,
        "errors_json": errors_json or [],
        "created_at":   MagicMock(timestamp=MagicMock(return_value=1724000000.0)),
        "completed_at": MagicMock(timestamp=MagicMock(return_value=1724000030.0)),
    }

    async def _fetchrow(*args, **kwargs):
        # Return row only if batch_id AND bank_id match (cross-bank isolation)
        if str(args[1]) == batch_id and str(args[2]) == bank_id:
            return row
        return None

    conn = MagicMock()
    conn.fetchrow = _fetchrow

    class _Pool:
        def acquire(self): return self
        async def __aenter__(self): return conn
        async def __aexit__(self, *a): pass

    return _Pool()


class TestVaultBatchStatus:
    def test_batch_status_returns_200_when_found(self):
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_batch()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001")
        assert r.status_code == 200

    def test_batch_status_response_schema(self):
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_batch(
            batch_id="batch-uuid-001", vault_type="PPS", status="COMPLETE",
            rows_total=10, rows_processed=10, rows_failed=0,
        )
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get("/v1/cts/vault/batches/batch-uuid-001").json()
        assert body["batch_id"]       == "batch-uuid-001"
        assert body["bank_id"]        == BANK_ID
        assert body["vault_type"]     == "PPS"
        assert body["status"]         == "COMPLETE"
        assert body["rows_total"]     == 10
        assert body["rows_processed"] == 10
        assert body["rows_failed"]    == 0
        assert body["db_table"]       == "cts.pps_vault_entries"

    def test_batch_not_found_returns_404(self):
        """Batch doesn't exist for this bank → 404 (not 403 — IDOR fix)."""
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_batch(
            batch_id="batch-uuid-001", bank_id=BANK_ID
        )
        client = TestClient(app, raise_server_exceptions=False)
        # Authenticated as saraswat-coop but asking for "other-bank" batch → 404
        r = client.get("/v1/cts/vault/batches/NONEXISTENT-BATCH-ID")
        assert r.status_code == 404
        assert r.json()["detail"]["error_code"] == "VAULT_BATCH_NOT_FOUND"

    def test_cross_bank_batch_returns_404_not_200(self):
        """
        User from bank-A asking for a batch that belongs to bank-B → 404.
        The DB WHERE clause includes bank_id, so bank-B's batch is invisible to bank-A.
        """
        app = _make_app(bank_id="other-bank")  # authenticated as other-bank
        app.state.db_pool = _mock_db_pool_with_batch(
            batch_id="batch-uuid-001", bank_id=BANK_ID  # belongs to saraswat-coop
        )
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001")
        assert r.status_code == 404

    def test_db_unavailable_returns_503(self):
        app = _make_app()
        # db_pool not set on app.state
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# 7. GET /vault/batches/{batch_id}/errors.csv
# ---------------------------------------------------------------------------

def _mock_db_pool_with_errors(batch_id="batch-uuid-001", bank_id=BANK_ID, errors=None):
    raw = errors or [
        {"row": 2, "error": "Account not found"},
        {"row": 5, "error": "Invalid amount"},
    ]
    row = {
        "vault_type": "PPS", "status": "PARTIAL",
        "rows_failed": len(raw),
        "errors_json": raw,
    }

    async def _fetchrow(*args, **kwargs):
        if str(args[1]) == batch_id and str(args[2]) == bank_id:
            return row
        return None

    conn = MagicMock()
    conn.fetchrow = _fetchrow

    class _Pool:
        def acquire(self): return self
        async def __aenter__(self): return conn
        async def __aexit__(self, *a): pass

    return _Pool()


class TestVaultBatchErrorsCsv:
    def test_errors_csv_returns_200_with_csv_content_type(self):
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_errors()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001/errors.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_errors_csv_has_attachment_content_disposition(self):
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_errors()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001/errors.csv")
        assert "attachment" in r.headers["content-disposition"]
        assert "filename" in r.headers["content-disposition"]

    def test_errors_csv_filename_contains_batch_id_prefix(self):
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_errors("batch-uuid-001")
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001/errors.csv")
        assert "batch-uu" in r.headers["content-disposition"]   # first 8 chars of UUID

    def test_errors_csv_has_header_row(self):
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_errors()
        client = TestClient(app, raise_server_exceptions=False)
        content = client.get("/v1/cts/vault/batches/batch-uuid-001/errors.csv").text
        assert "row_number" in content
        assert "error_message" in content

    def test_errors_csv_contains_all_error_rows(self):
        errors = [{"row": i, "error": f"err {i}"} for i in range(1, 6)]
        app = _make_app()
        app.state.db_pool = _mock_db_pool_with_errors(errors=errors)
        client = TestClient(app, raise_server_exceptions=False)
        content = client.get("/v1/cts/vault/batches/batch-uuid-001/errors.csv").text
        lines = [l for l in content.strip().splitlines() if l]
        assert len(lines) == 6   # 1 header + 5 error rows

    def test_errors_csv_cross_bank_returns_404(self):
        app = _make_app(bank_id="other-bank")
        app.state.db_pool = _mock_db_pool_with_errors(bank_id=BANK_ID)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001/errors.csv")
        assert r.status_code == 404

    def test_errors_csv_db_unavailable_returns_503(self):
        app = _make_app()
        # no db_pool on state
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/batches/batch-uuid-001/errors.csv")
        assert r.status_code == 503
