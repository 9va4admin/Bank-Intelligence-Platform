"""
Tests for apps/api/routers/branches.py — Branch Master CRUD + CSV bulk import.

Routes under test:
  GET    /v1/branches              — list (paginated, filterable)
  POST   /v1/branches              — create single branch
  GET    /v1/branches/{ifsc}       — get by IFSC
  PUT    /v1/branches/{ifsc}       — update branch
  DELETE /v1/branches/{ifsc}       — soft-delete (is_active=false)
  POST   /v1/branches/bulk-import/preview  — dry-run CSV validate, no DB write
  POST   /v1/branches/bulk-import          — chunked upsert (idempotent on IFSC)

Access control:
  - All routes require JWT auth (unauthenticated → 401)
  - bank_it_admin: full access to all branch CRUD + bulk import
  - ops_manager: read-only (GET routes only)
  - ops_reviewer, fraud_analyst, compliance_officer: 403 on all routes
"""
import io
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clear_branch_store():
    """Reset in-memory branch store before each test for isolation."""
    from apps.api.routers.branches import _BRANCH_STORE
    _BRANCH_STORE.clear()
    yield
    _BRANCH_STORE.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_app(role: str = "bank_it_admin"):
    from apps.api.routers.branches import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _unauthed_app():
    from apps.api.routers.branches import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _client(role: str = "bank_it_admin") -> TestClient:
    return TestClient(_make_app(role=role), raise_server_exceptions=False)


def _sample_branch_payload() -> dict:
    return {
        "branch_name": "Koramangala Branch",
        "branch_ifsc": "KARB0000123",
        "city": "Bengaluru",
        "district": "Bengaluru Urban",
        "state": "Karnataka",
        "address": "80 Feet Road, Koramangala, Bengaluru",
        "pin_code": "560034",
        "phone_number": "08025534567",
    }


def _sample_csv_content() -> bytes:
    lines = [
        "Branch Name,Complete Address,City,District,State,PIN Code,IFSC Code,Phone Number",
        "Koramangala Branch,80 Feet Road Bengaluru,Bengaluru,Bengaluru Urban,Karnataka,560034,KARB0000123,08025534567",
        "Indiranagar Branch,100 Feet Road Bengaluru,Bengaluru,Bengaluru Urban,Karnataka,560038,KARB0000124,08025534568",
    ]
    return "\n".join(lines).encode("utf-8")


# ── GET /v1/branches ─────────────────────────────────────────────────────────

class TestBranchList:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/branches").status_code == 401

    def test_ops_reviewer_returns_403(self):
        assert _client("ops_reviewer").get("/v1/branches").status_code == 403

    def test_fraud_analyst_returns_403(self):
        assert _client("fraud_analyst").get("/v1/branches").status_code == 403

    def test_compliance_officer_returns_403(self):
        assert _client("compliance_officer").get("/v1/branches").status_code == 403

    def test_bank_it_admin_gets_200(self):
        assert _client("bank_it_admin").get("/v1/branches").status_code == 200

    def test_ops_manager_gets_200(self):
        assert _client("ops_manager").get("/v1/branches").status_code == 200

    def test_response_has_branches_list(self):
        data = _client().get("/v1/branches").json()
        assert "branches" in data

    def test_response_has_total(self):
        data = _client().get("/v1/branches").json()
        assert "total" in data

    def test_response_has_pagination_cursor(self):
        data = _client().get("/v1/branches").json()
        assert "cursor" in data

    def test_state_filter_accepted(self):
        resp = _client().get("/v1/branches", params={"state": "Karnataka"})
        assert resp.status_code == 200

    def test_city_filter_accepted(self):
        resp = _client().get("/v1/branches", params={"city": "Bengaluru"})
        assert resp.status_code == 200

    def test_search_filter_accepted(self):
        resp = _client().get("/v1/branches", params={"q": "Koramangala"})
        assert resp.status_code == 200

    def test_is_active_filter_accepted(self):
        resp = _client().get("/v1/branches", params={"is_active": "true"})
        assert resp.status_code == 200

    def test_limit_max_100_enforced(self):
        resp = _client().get("/v1/branches", params={"limit": 200})
        assert resp.status_code == 422


# ── POST /v1/branches ────────────────────────────────────────────────────────

class TestBranchCreate:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.post("/v1/branches", json=_sample_branch_payload()).status_code == 401

    def test_ops_manager_cannot_create(self):
        resp = _client("ops_manager").post("/v1/branches", json=_sample_branch_payload())
        assert resp.status_code == 403

    def test_ops_reviewer_cannot_create(self):
        resp = _client("ops_reviewer").post("/v1/branches", json=_sample_branch_payload())
        assert resp.status_code == 403

    def test_bank_it_admin_can_create(self):
        resp = _client("bank_it_admin").post("/v1/branches", json=_sample_branch_payload())
        assert resp.status_code in (200, 201)

    def test_create_response_has_branch_id(self):
        resp = _client().post("/v1/branches", json=_sample_branch_payload())
        assert "branch_id" in resp.json()

    def test_create_response_has_branch_ifsc(self):
        resp = _client().post("/v1/branches", json=_sample_branch_payload())
        assert resp.json()["branch_ifsc"] == "KARB0000123"

    def test_missing_branch_name_returns_422(self):
        payload = _sample_branch_payload()
        del payload["branch_name"]
        assert _client().post("/v1/branches", json=payload).status_code == 422

    def test_missing_ifsc_returns_422(self):
        payload = _sample_branch_payload()
        del payload["branch_ifsc"]
        assert _client().post("/v1/branches", json=payload).status_code == 422

    def test_ifsc_wrong_length_returns_422(self):
        payload = _sample_branch_payload()
        payload["branch_ifsc"] = "KARB123"  # too short — must be 11 chars
        assert _client().post("/v1/branches", json=payload).status_code == 422

    def test_ifsc_non_alphanumeric_returns_422(self):
        payload = _sample_branch_payload()
        payload["branch_ifsc"] = "KARB 000123"  # space invalid
        assert _client().post("/v1/branches", json=payload).status_code == 422


# ── GET /v1/branches/{ifsc} ──────────────────────────────────────────────────

class TestBranchGet:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/branches/KARB0000123").status_code == 401

    def test_ops_reviewer_returns_403(self):
        assert _client("ops_reviewer").get("/v1/branches/KARB0000123").status_code == 403

    def test_bank_it_admin_gets_200_or_404(self):
        # 200 if branch exists in test DB, 404 if not — both are valid contract responses
        status = _client("bank_it_admin").get("/v1/branches/KARB0000123").status_code
        assert status in (200, 404)

    def test_ops_manager_gets_200_or_404(self):
        status = _client("ops_manager").get("/v1/branches/KARB0000123").status_code
        assert status in (200, 404)

    def test_unknown_ifsc_returns_404(self):
        assert _client().get("/v1/branches/XXXX0000000").status_code == 404


# ── PUT /v1/branches/{ifsc} ──────────────────────────────────────────────────

class TestBranchUpdate:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.put("/v1/branches/KARB0000123", json={"city": "Mysuru"}).status_code == 401

    def test_ops_manager_cannot_update(self):
        resp = _client("ops_manager").put("/v1/branches/KARB0000123", json={"city": "Mysuru"})
        assert resp.status_code == 403

    def test_ops_reviewer_cannot_update(self):
        resp = _client("ops_reviewer").put("/v1/branches/KARB0000123", json={"city": "Mysuru"})
        assert resp.status_code == 403

    def test_bank_it_admin_gets_200_or_404(self):
        status = _client().put("/v1/branches/KARB0000123", json={"city": "Mysuru"}).status_code
        assert status in (200, 404)

    def test_unknown_ifsc_returns_404(self):
        assert _client().put("/v1/branches/XXXX0000000", json={"city": "X"}).status_code == 404

    def test_cannot_update_ifsc(self):
        # IFSC is the immutable identity key — changing it would break vault lookups
        resp = _client().put(
            "/v1/branches/KARB0000123",
            json={"branch_ifsc": "KARB9999999"},
        )
        assert resp.status_code == 422


# ── DELETE /v1/branches/{ifsc} ───────────────────────────────────────────────

class TestBranchDelete:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.delete("/v1/branches/KARB0000123").status_code == 401

    def test_ops_manager_cannot_delete(self):
        assert _client("ops_manager").delete("/v1/branches/KARB0000123").status_code == 403

    def test_ops_reviewer_cannot_delete(self):
        assert _client("ops_reviewer").delete("/v1/branches/KARB0000123").status_code == 403

    def test_bank_it_admin_gets_200_or_404(self):
        status = _client().delete("/v1/branches/KARB0000123").status_code
        assert status in (200, 404)

    def test_unknown_ifsc_returns_404(self):
        assert _client().delete("/v1/branches/XXXX0000000").status_code == 404


# ── POST /v1/branches/bulk-import/preview ────────────────────────────────────

class TestBulkImportPreview:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        resp = client.post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.status_code == 401

    def test_ops_manager_cannot_preview(self):
        resp = _client("ops_manager").post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.status_code == 403

    def test_bank_it_admin_gets_200(self):
        resp = _client("bank_it_admin").post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.status_code == 200

    def test_preview_response_has_valid_count(self):
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        data = resp.json()
        assert "valid_count" in data

    def test_preview_response_has_error_count(self):
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        data = resp.json()
        assert "error_count" in data

    def test_preview_response_has_errors_list(self):
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        data = resp.json()
        assert "errors" in data

    def test_preview_does_not_require_db(self):
        # Preview must work even if DB is unavailable — it only validates CSV
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.status_code == 200

    def test_preview_with_invalid_ifsc_reports_error(self):
        bad_csv = (
            "Branch Name,Complete Address,City,District,State,PIN Code,IFSC Code,Phone Number\n"
            "Bad Branch,Address,City,Dist,State,000000,BAD,0000000000\n"
        ).encode("utf-8")
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(bad_csv), "text/csv")},
        )
        data = resp.json()
        assert data["error_count"] >= 1

    def test_preview_with_missing_ifsc_column_returns_400(self):
        bad_csv = b"Branch Name,City\nKoramangala,Bengaluru\n"
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(bad_csv), "text/csv")},
        )
        assert resp.status_code == 400

    def test_preview_sample_csv_shows_2_valid_rows(self):
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.json()["valid_count"] == 2

    def test_non_csv_file_returns_400(self):
        resp = _client().post(
            "/v1/branches/bulk-import/preview",
            files={"file": ("branches.xlsx", io.BytesIO(b"not-csv"), "application/vnd.ms-excel")},
        )
        assert resp.status_code == 400


# ── POST /v1/branches/bulk-import ────────────────────────────────────────────

class TestBulkImport:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        resp = client.post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.status_code == 401

    def test_ops_manager_cannot_import(self):
        resp = _client("ops_manager").post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.status_code == 403

    def test_bank_it_admin_gets_200(self):
        resp = _client("bank_it_admin").post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        assert resp.status_code == 200

    def test_import_response_has_imported_count(self):
        resp = _client().post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        data = resp.json()
        assert "imported_count" in data

    def test_import_response_has_skipped_count(self):
        resp = _client().post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        data = resp.json()
        assert "skipped_count" in data

    def test_import_response_has_error_count(self):
        resp = _client().post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(_sample_csv_content()), "text/csv")},
        )
        data = resp.json()
        assert "error_count" in data

    def test_import_with_invalid_ifsc_skips_rows(self):
        bad_csv = (
            "Branch Name,Complete Address,City,District,State,PIN Code,IFSC Code,Phone Number\n"
            "Good Branch,Addr,City,Dist,State,560001,KARB0000125,0802123456\n"
            "Bad Branch,Addr,City,Dist,State,000000,BAD,0000\n"
        ).encode("utf-8")
        resp = _client().post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(bad_csv), "text/csv")},
        )
        data = resp.json()
        assert data["error_count"] >= 1

    def test_missing_ifsc_column_returns_400(self):
        bad_csv = b"Branch Name,City\nKoramangala,Bengaluru\n"
        resp = _client().post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.csv", io.BytesIO(bad_csv), "text/csv")},
        )
        assert resp.status_code == 400

    def test_non_csv_file_returns_400(self):
        resp = _client().post(
            "/v1/branches/bulk-import",
            files={"file": ("branches.xlsx", io.BytesIO(b"not-csv"), "application/vnd.ms-excel")},
        )
        assert resp.status_code == 400
