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


# ---------------------------------------------------------------------------
# Auth edge cases — lines 32-36
# ---------------------------------------------------------------------------

class TestEJAuthEdgeCases:
    def test_valid_test_token_prefix_extracts_bank_id(self):
        """Covers line 34: token.removeprefix('test-token-') path."""
        from apps.api.routers.ej import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/v1/ej/inward/log",
            json=_submit_log_payload(),
            headers={"Authorization": "Bearer test-token-mybank"},
        )
        # Should succeed (bank_id extracted as 'mybank')
        assert response.status_code in (200, 202)

    def test_invalid_token_returns_401_on_submit_log(self):
        from apps.api.routers.ej import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/v1/ej/inward/log",
            json=_submit_log_payload(),
            headers={"Authorization": "Bearer invalid-jwt-token"},
        )
        assert response.status_code == 401

    def test_invalid_token_returns_401_on_canonical(self):
        from apps.api.routers.ej import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/ej/canonical/abc123",
            headers={"Authorization": "Bearer some-random-token"},
        )
        assert response.status_code == 401

    def test_invalid_token_returns_401_on_health(self):
        from apps.api.routers.ej import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/ej/atm/ATM001/health",
            headers={"Authorization": "Bearer bad-token"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# New route: POST /v1/ej/inward/{atm_id}/log — lines 177-204
# ---------------------------------------------------------------------------

def _atm_log_payload():
    return {
        "raw_log": "[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
        "source": "branch-mcp",
        "oem_fingerprint": "NCR-APTRA-v6",
    }


def _make_ej_modules_stub():
    """Stub modules.ej.workflows.* so dynamic imports inside route don't fail."""
    import sys
    from unittest.mock import MagicMock
    normalise_mod = MagicMock()
    normalise_mod.EJNormalisationWorkflow = MagicMock()
    normalise_mod.EJNormalisationInput = MagicMock(return_value=MagicMock())
    dispute_mod = MagicMock()
    dispute_mod.DisputeResolutionWorkflow = MagicMock()
    dispute_mod.EJDisputeInput = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("modules", MagicMock())
    sys.modules.setdefault("modules.ej", MagicMock())
    sys.modules.setdefault("modules.ej.workflows", MagicMock())
    sys.modules["modules.ej.workflows.normalise_workflow"] = normalise_mod
    sys.modules["modules.ej.workflows.dispute_workflow"] = dispute_mod
    return normalise_mod, dispute_mod


class TestEJLogByAtmRoute:
    def test_submit_no_temporal_client_returns_202(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/ATM001/log", json=_atm_log_payload())
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "ACCEPTED"
        assert "workflow_id" in data
        assert "raw_log_hash" in data

    def test_submit_with_temporal_client_starts_workflow(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock, MagicMock

        _make_ej_modules_stub()

        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock()

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/ATM002/log", json=_atm_log_payload())
        assert response.status_code == 202
        assert response.json()["status"] == "ACCEPTED"

    def test_submit_already_started_error_still_returns_202(self):
        """'already started' exception is swallowed — idempotent workflow."""
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock

        _make_ej_modules_stub()

        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock(
            side_effect=Exception("workflow already started for this id")
        )

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/ATM003/log", json=_atm_log_payload())
        assert response.status_code == 202

    def test_submit_temporal_error_returns_503(self):
        """Non-'already started' temporal error → 503."""
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock

        _make_ej_modules_stub()

        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock(
            side_effect=Exception("connection refused")
        )

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/inward/ATM004/log", json=_atm_log_payload())
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# New route: GET /v1/ej/canonical/{raw_log_hash} — lines 241-252
# ---------------------------------------------------------------------------

class TestEJCanonicalByHashRoute:
    def test_no_temporal_client_returns_running(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/deadbeef1234")
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_status"] == "RUNNING"

    def test_temporal_client_result_returned(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock, MagicMock

        mock_result = MagicMock()
        mock_result.outcome = "NORMALISED"
        mock_result.canonical_record = {"atm_id": "ATM001", "amount": 5000}

        mock_handle = AsyncMock()
        mock_handle.result = AsyncMock(return_value=mock_result)

        mock_temporal = MagicMock()
        mock_temporal.get_workflow_handle = MagicMock(return_value=mock_handle)

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/deadbeef5678")
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_status"] == "NORMALISED"
        assert data["canonical_record"] is not None

    def test_temporal_client_exception_falls_back_to_running(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock, MagicMock

        mock_handle = AsyncMock()
        mock_handle.result = AsyncMock(side_effect=Exception("workflow not found"))

        mock_temporal = MagicMock()
        mock_temporal.get_workflow_handle = MagicMock(return_value=mock_handle)

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/ej/canonical/deadbeefabcd")
        assert response.status_code == 200
        assert response.json()["workflow_status"] == "RUNNING"


# ---------------------------------------------------------------------------
# New route: POST /v1/ej/disputes/{npci_claim_id}/resolve — lines 282-309
# ---------------------------------------------------------------------------

def _dispute_payload():
    return {
        "atm_id": "ATM001",
        "claim_amount": 5000.0,
        "claim_timestamp": "2026-06-17T10:30:00Z",
        "claim_type": "CASH_NOT_DISPENSED",
    }


class TestEJResolveDisputeRoute:
    def test_no_temporal_client_returns_202(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM001/resolve", json=_dispute_payload())
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "ACCEPTED"
        assert data["npci_claim_id"] == "CLAIM001"

    def test_with_temporal_client_starts_dispute_workflow(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock

        _make_ej_modules_stub()

        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock()

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM002/resolve", json=_dispute_payload())
        assert response.status_code == 202
        assert response.json()["workflow_id"] == "ej-dispute-test-bank-CLAIM002"

    def test_already_started_error_swallowed_returns_202(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock

        _make_ej_modules_stub()

        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock(
            side_effect=Exception("workflow already started")
        )

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM003/resolve", json=_dispute_payload())
        assert response.status_code == 202

    def test_temporal_error_returns_503(self):
        from apps.api.routers.ej import router_v1, get_current_bank_id
        from unittest.mock import AsyncMock

        _make_ej_modules_stub()

        mock_temporal = AsyncMock()
        mock_temporal.start_workflow = AsyncMock(
            side_effect=Exception("grpc connection timeout")
        )

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_temporal

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/ej/disputes/CLAIM004/resolve", json=_dispute_payload())
        assert response.status_code == 503
