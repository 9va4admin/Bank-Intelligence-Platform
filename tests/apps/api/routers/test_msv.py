"""
Tests for apps/api/routers/msv.py — MSV REST API.

Routes tested:
  POST /v1/msv/validate
  GET  /v1/msv/accounts/{account_number}/signatories
  GET  /v1/msv/enrollment/jobs/{job_id}/progress

Security:
  - Unauthenticated → 401
  - Valid request → 200 with typed response
  - account_number never raw in response body
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock


def _make_app():
    from apps.api.routers.msv import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _auth_headers(bank_id="kotak-mah"):
    return {"Authorization": f"Bearer test-token-{bank_id}"}


def test_test_token_bearer_header_no_longer_grants_access():
    """Regression guard for ASTRA-01: get_current_user_context now delegates
    to the shared, middleware-backed require_user_context — a bare
    test-token-* Bearer header (formerly a universal backdoor) must never
    grant access on its own."""
    from apps.api.routers.msv import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/v1/msv/accounts/1234567890/signatories",
        headers=_auth_headers("any-bank"),
    )
    assert response.status_code == 401


class TestMSVValidateRoute:
    def test_unauthenticated_returns_401(self):
        from apps.api.routers.msv import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/v1/msv/validate", json={
            "instrument_id": "CHQ-001",
            "bank_id": "kotak-mah",
            "account_number": "1234567890",
            "cheque_image_url": "minio://bucket/img.jpg",
        })
        assert resp.status_code == 401

    def test_valid_request_returns_200(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user",
            role=Role.OPS_MANAGER,
            bank_id="kotak-mah",
            clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/v1/msv/validate", json={
            "instrument_id": "CHQ-001",
            "bank_id": "kotak-mah",
            "account_number": "1234567890",
            "cheque_image_url": "minio://bucket/img.jpg",
        }, headers=_auth_headers())
        assert resp.status_code == 200

    def test_missing_instrument_id_returns_422(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/v1/msv/validate", json={
            # missing instrument_id
            "bank_id": "kotak-mah",
            "account_number": "1234567890",
            "cheque_image_url": "minio://bucket/img.jpg",
        }, headers=_auth_headers())
        assert resp.status_code == 422

    def test_response_has_outcome_field(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/v1/msv/validate", json={
            "instrument_id": "CHQ-001",
            "bank_id": "kotak-mah",
            "account_number": "1234567890",
            "cheque_image_url": "minio://bucket/img.jpg",
        }, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "outcome" in data
        assert "instrument_id" in data
        assert data["instrument_id"] == "CHQ-001"

    def test_response_is_json(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/v1/msv/validate", json={
            "instrument_id": "CHQ-001",
            "bank_id": "kotak-mah",
            "account_number": "1234567890",
            "cheque_image_url": "minio://bucket/img.jpg",
        }, headers=_auth_headers())
        assert resp.headers.get("content-type", "").startswith("application/json")


class TestMSVSignatoriesRoute:
    def test_unauthenticated_returns_401(self):
        from apps.api.routers.msv import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/msv/accounts/1234567890/signatories")
        assert resp.status_code == 401

    def test_authenticated_returns_200(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/v1/msv/accounts/1234567890/signatories",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200

    def test_raw_account_number_not_in_response_body(self):
        """Raw account number must NEVER appear in the response."""
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/v1/msv/accounts/9876543210/signatories",
            headers=_auth_headers(),
        )
        # Raw account number must never be in the response body
        assert "9876543210" not in resp.text

    def test_response_has_account_display_field(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/v1/msv/accounts/1234567890/signatories",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "account_display" in data
        assert "****" in data["account_display"]  # must be masked


class TestMSVEnrollmentJobRoute:
    def test_unauthenticated_returns_401(self):
        from apps.api.routers.msv import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/v1/msv/enrollment/jobs/job-001/progress")
        assert resp.status_code == 401

    def test_authenticated_returns_200(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", clearing_zone="DEFAULT",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/v1/msv/enrollment/jobs/job-001/progress",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] == "job-001"
