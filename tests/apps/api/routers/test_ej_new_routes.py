"""
Tests for new EJ API routes added to apps/api/routers/ej.py:

- POST /v1/ej/inward/{atm_id}/log      — submit EJ log per ATM
- GET  /v1/ej/canonical/{raw_log_hash} — poll workflow status (extended)
- POST /v1/ej/disputes/{npci_claim_id}/resolve — trigger dispute workflow

TDD: written before implementation.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(bank_id="test-bank"):
    from apps.api.routers.ej import router_v1, get_current_bank_id
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    return app


def _make_app_no_auth():
    from apps.api.routers.ej import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


class TestEJLogSubmitByAtmId:
    def test_submit_returns_202(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        payload = {
            "raw_log": "[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
            "source": "branch-mcp",
            "oem_fingerprint": "NCR-SELFSERV-6674",
        }
        response = client.post("/v1/ej/inward/ATM001/log", json=payload)
        assert response.status_code == 202

    def test_submit_requires_auth(self):
        client = TestClient(_make_app_no_auth(), raise_server_exceptions=False)
        payload = {
            "raw_log": "log data",
            "source": "branch-mcp",
            "oem_fingerprint": "NCR-SELFSERV-6674",
        }
        response = client.post("/v1/ej/inward/ATM001/log", json=payload)
        assert response.status_code == 401

    def test_submit_response_has_raw_log_hash(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        payload = {
            "raw_log": "[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
            "source": "branch-mcp",
            "oem_fingerprint": "NCR-SELFSERV-6674",
        }
        response = client.post("/v1/ej/inward/ATM001/log", json=payload)
        data = response.json()
        assert "raw_log_hash" in data
        assert len(data["raw_log_hash"]) > 0

    def test_submit_response_has_workflow_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        payload = {
            "raw_log": "[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
            "source": "branch-mcp",
            "oem_fingerprint": "NCR-SELFSERV-6674",
        }
        response = client.post("/v1/ej/inward/ATM001/log", json=payload)
        data = response.json()
        assert "workflow_id" in data
        assert data["workflow_id"].startswith("ej-normalise-")

    def test_submit_response_status_accepted(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        payload = {
            "raw_log": "log data",
            "source": "branch-mcp",
            "oem_fingerprint": "NCR-SELFSERV-6674",
        }
        response = client.post("/v1/ej/inward/ATM001/log", json=payload)
        data = response.json()
        assert data["status"] == "ACCEPTED"

    def test_workflow_id_contains_bank_id(self):
        client = TestClient(_make_app(bank_id="kotak-mah"), raise_server_exceptions=False)
        payload = {
            "raw_log": "log data",
            "source": "branch-mcp",
            "oem_fingerprint": "NCR-SELFSERV-6674",
        }
        response = client.post("/v1/ej/inward/ATM001/log", json=payload)
        data = response.json()
        assert "kotak-mah" in data["workflow_id"]

    def test_submit_missing_fields_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/ATM001/log", json={"invalid": "data"})
        assert response.status_code == 422


class TestEJCanonicalRoute:
    def test_get_canonical_returns_200(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/abc123def456")
        assert response.status_code == 200

    def test_get_canonical_requires_auth(self):
        client = TestClient(_make_app_no_auth(), raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/abc123")
        assert response.status_code == 401

    def test_get_canonical_response_has_raw_log_hash(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/abc123def456")
        data = response.json()
        assert data["raw_log_hash"] == "abc123def456"

    def test_get_canonical_has_workflow_status(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/abc123def456")
        data = response.json()
        assert "workflow_status" in data

    def test_get_canonical_returns_running_without_temporal(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/abc123def456")
        data = response.json()
        assert data["workflow_status"] == "RUNNING"


class TestEJDisputeRoute:
    def _dispute_payload(self):
        return {
            "atm_id": "ATM001",
            "claim_amount": 5000.0,
            "claim_timestamp": "2026-06-17T10:30:00Z",
            "claim_type": "CASH_NOT_DISPENSED",
        }

    def test_dispute_returns_202(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM-001/resolve", json=self._dispute_payload())
        assert response.status_code == 202

    def test_dispute_requires_auth(self):
        client = TestClient(_make_app_no_auth(), raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM-001/resolve", json=self._dispute_payload())
        assert response.status_code == 401

    def test_dispute_response_has_npci_claim_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM-001/resolve", json=self._dispute_payload())
        data = response.json()
        assert data["npci_claim_id"] == "CLAIM-001"

    def test_dispute_response_has_workflow_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM-001/resolve", json=self._dispute_payload())
        data = response.json()
        assert "workflow_id" in data
        assert data["workflow_id"].startswith("ej-dispute-")

    def test_dispute_response_status_accepted(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM-001/resolve", json=self._dispute_payload())
        data = response.json()
        assert data["status"] == "ACCEPTED"

    def test_dispute_missing_fields_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM-001/resolve", json={"invalid": "data"})
        assert response.status_code == 422

    def test_dispute_workflow_id_contains_bank_id(self):
        client = TestClient(_make_app(bank_id="hdfc-bank"), raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM-XYZ/resolve", json=self._dispute_payload())
        data = response.json()
        assert "hdfc-bank" in data["workflow_id"]
        assert "CLAIM-XYZ" in data["workflow_id"]
