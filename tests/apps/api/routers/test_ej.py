"""
Tests for apps/api/routers/ej.py

EJ API endpoints:
- POST /v1/ej/inward/log — submit raw EJ log
- GET  /v1/ej/canonical/{canonical_hash} — fetch canonical record
- GET  /v1/ej/atm/{atm_id}/health — ATM health summary
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app_with_auth(bank_id="test-bank"):
    from apps.api.routers.ej import router_v1, get_current_bank_id
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    return app


def _submit_log_payload():
    return {
        "raw_log": "[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
        "atm_id": "ATM001",
        "bank_id": "test-bank",
        "source": "branch-mcp",
    }


class TestEJSubmitRoute:
    def test_submit_unauthenticated_returns_401(self):
        from apps.api.routers.ej import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/ej/inward/log", json=_submit_log_payload())
        assert response.status_code == 401

    def test_submit_authenticated_returns_202(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/log", json=_submit_log_payload(),
                               headers={"Authorization": "Bearer test"})
        assert response.status_code in (200, 202)

    def test_submit_response_has_workflow_id(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/log", json=_submit_log_payload(),
                               headers={"Authorization": "Bearer test"})
        data = response.json()
        assert "workflow_id" in data

    def test_submit_response_has_raw_log_hash(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/log", json=_submit_log_payload(),
                               headers={"Authorization": "Bearer test"})
        data = response.json()
        assert "raw_log_hash" in data

    def test_submit_response_has_status(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/log", json=_submit_log_payload(),
                               headers={"Authorization": "Bearer test"})
        data = response.json()
        assert data["status"] in ("ACCEPTED", "REJECTED")

    def test_submit_invalid_payload_returns_422(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/log", json={"invalid": "data"},
                               headers={"Authorization": "Bearer test"})
        assert response.status_code == 422

    def test_workflow_id_contains_bank_id_and_hash(self):
        """Workflow ID: ej-normalise-{bank_id}-{raw_log_hash} — idempotent."""
        client = TestClient(_make_app_with_auth(bank_id="kotak"), raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/log", json=_submit_log_payload(),
                               headers={"Authorization": "Bearer test"})
        data = response.json()
        assert "kotak" in data["workflow_id"]
        assert data["workflow_id"].startswith("ej-normalise-")


class TestEJCanonicalRoute:
    def test_get_canonical_unauthenticated_returns_401(self):
        from apps.api.routers.ej import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/ej/canonical/abc123")
        assert response.status_code == 401

    def test_get_canonical_authenticated_returns_200(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/abc123",
                              headers={"Authorization": "Bearer test"})
        assert response.status_code == 200

    def test_get_canonical_response_has_canonical_hash(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/abc123",
                              headers={"Authorization": "Bearer test"})
        data = response.json()
        assert data["canonical_hash"] == "abc123"


class TestEJATMHealthRoute:
    def test_get_health_unauthenticated_returns_401(self):
        from apps.api.routers.ej import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/ej/atm/ATM001/health")
        assert response.status_code == 401

    def test_get_health_authenticated_returns_200(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.get("/v1/ej/atm/ATM001/health",
                              headers={"Authorization": "Bearer test"})
        assert response.status_code == 200

    def test_get_health_response_has_atm_id(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.get("/v1/ej/atm/ATM001/health",
                              headers={"Authorization": "Bearer test"})
        data = response.json()
        assert data["atm_id"] == "ATM001"

    def test_get_health_response_has_status(self):
        client = TestClient(_make_app_with_auth(), raise_server_exceptions=False)
        response = client.get("/v1/ej/atm/ATM001/health",
                              headers={"Authorization": "Bearer test"})
        data = response.json()
        assert "status" in data
