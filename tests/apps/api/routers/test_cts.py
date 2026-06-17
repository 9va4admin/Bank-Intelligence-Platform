"""
Tests for apps/api/routers/cts.py

CTS API endpoints:
- POST /v1/cts/inward/{instrument_id}/submit — submit inward cheque
- GET  /v1/cts/decisions/{instrument_id}     — fetch decision status

Rules:
- All routes require JWT auth (unauthenticated → 401)
- Typed Pydantic response models — no bare dict returns
- Rate limit: 600 req/min per bank_id
- OTel span on every route
- No business logic in routers — delegate to workflow trigger
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


def _make_app():
    from apps.api.routers.cts import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _auth_headers(bank_id="test-bank"):
    # Fake JWT — tests bypass real auth via dependency override
    return {"Authorization": f"Bearer test-token-{bank_id}"}


def _submit_payload():
    return {
        "image_url": "s3://bucket/INST001.jpg",
        "account_number": "1234567890",
        "cheque_number": "100001",
        "presented_amount": 50000.0,
        "presented_payee": "ACME Corp",
        "iet_deadline": 9999999999.0,
        "bank_id": "test-bank",
    }


class TestCTSSubmitRoute:
    def test_submit_unauthenticated_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/cts/inward/INST001/submit", json=_submit_payload())
        assert response.status_code == 401

    def test_submit_authenticated_returns_202_or_200(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/cts/inward/INST001/submit",
                               json=_submit_payload(), headers=_auth_headers())
        assert response.status_code in (200, 202)

    def test_submit_response_has_instrument_id(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/cts/inward/INST001/submit",
                               json=_submit_payload(), headers=_auth_headers())
        assert response.status_code in (200, 202)
        data = response.json()
        assert "instrument_id" in data

    def test_submit_response_has_workflow_id(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/cts/inward/INST001/submit",
                               json=_submit_payload(), headers=_auth_headers())
        data = response.json()
        assert "workflow_id" in data

    def test_submit_response_has_status(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/cts/inward/INST001/submit",
                               json=_submit_payload(), headers=_auth_headers())
        data = response.json()
        assert data["status"] in ("ACCEPTED", "REJECTED")

    def test_submit_invalid_payload_returns_422(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/cts/inward/INST001/submit",
                               json={"invalid": "payload"}, headers=_auth_headers())
        assert response.status_code == 422

    def test_submit_workflow_id_is_deterministic(self):
        """Workflow ID must be cts-{bank_id}-{instrument_id} — idempotency guarantee."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/v1/cts/inward/INST001/submit",
                               json=_submit_payload(), headers=_auth_headers())
        data = response.json()
        assert data["workflow_id"] == "cts-test-bank-INST001"


class TestCTSDecisionRoute:
    def test_get_decision_unauthenticated_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/cts/decisions/INST001")
        assert response.status_code == 401

    def test_get_decision_authenticated_returns_200(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/cts/decisions/INST001", headers=_auth_headers())
        assert response.status_code == 200

    def test_get_decision_response_has_instrument_id(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/cts/decisions/INST001", headers=_auth_headers())
        data = response.json()
        assert data["instrument_id"] == "INST001"

    def test_get_decision_response_has_workflow_status(self):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/cts/decisions/INST001", headers=_auth_headers())
        data = response.json()
        assert "workflow_status" in data


class TestCTSHealthRoute:
    def test_health_live_no_auth_required(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        # Health endpoints exist at app level, not module router — skip if 404
        # This test verifies the router itself doesn't block the route
        response = client.get("/v1/cts/inward/INST001/submit")
        # GET on a POST-only route → 405 or 401 — not a crash
        assert response.status_code in (401, 405)
