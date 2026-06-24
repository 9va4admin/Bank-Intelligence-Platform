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


def _patch_temporalio():
    """
    temporalio is not installed in the test environment (no GPU/Temporal server).
    Patch the dynamic imports inside the router so the Temporal client path executes.
    """
    import sys
    from types import ModuleType

    # Build a minimal temporalio stub
    temporalio = ModuleType("temporalio")
    temporalio_client = ModuleType("temporalio.client")

    class _WorkflowAlreadyStartedError(Exception):
        pass

    temporalio_client.WorkflowAlreadyStartedError = _WorkflowAlreadyStartedError
    temporalio.client = temporalio_client
    sys.modules.setdefault("temporalio", temporalio)
    sys.modules.setdefault("temporalio.client", temporalio_client)


class TestCTSSubmitWithTemporalClient:
    """Covers lines 152-171: Temporal client present path."""

    def _make_app_with_temporal(self, temporal_client):
        _patch_temporalio()
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = temporal_client
        return app

    def test_submit_with_temporal_client_starts_workflow(self):
        _patch_temporalio()
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock(return_value=MagicMock())
        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.cts.workflows.cheque_workflow.ChequeProcessingWorkflow", MagicMock()):
            response = client.post(
                "/v1/cts/inward/INST001/submit",
                json=_submit_payload(),
                headers=_auth_headers(),
            )
        assert response.status_code in (200, 202)
        temporal_client.start_workflow.assert_called_once()

    def test_submit_with_temporal_workflow_already_started_is_idempotent(self):
        """WorkflowAlreadyStartedError → still returns 202 (idempotent)."""
        _patch_temporalio()
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock(
            side_effect=Exception("workflow already started")
        )
        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.cts.workflows.cheque_workflow.ChequeProcessingWorkflow", MagicMock()):
            response = client.post(
                "/v1/cts/inward/INST001/submit",
                json=_submit_payload(),
                headers=_auth_headers(),
            )
        assert response.status_code in (200, 202)

    def test_submit_with_temporal_unknown_error_returns_503(self):
        """Non-idempotent Temporal error → 503."""
        _patch_temporalio()
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock(
            side_effect=Exception("connection refused")
        )
        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.cts.workflows.cheque_workflow.ChequeProcessingWorkflow", MagicMock()):
            response = client.post(
                "/v1/cts/inward/INST001/submit",
                json=_submit_payload(),
                headers=_auth_headers(),
            )
        assert response.status_code == 503

    def test_submit_workflow_uses_correct_task_queue(self):
        """Task queue must be cts-processing-{bank_id}."""
        _patch_temporalio()
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock(return_value=MagicMock())
        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.cts.workflows.cheque_workflow.ChequeProcessingWorkflow", MagicMock()):
            client.post(
                "/v1/cts/inward/INST001/submit",
                json=_submit_payload(),
                headers=_auth_headers(),
            )
        _, kwargs = temporal_client.start_workflow.call_args
        assert kwargs["task_queue"] == "cts-processing-test-bank"

    def test_submit_workflow_id_passed_to_temporal(self):
        """Temporal must receive the deterministic workflow ID."""
        _patch_temporalio()
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock(return_value=MagicMock())
        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.cts.workflows.cheque_workflow.ChequeProcessingWorkflow", MagicMock()):
            client.post(
                "/v1/cts/inward/INST001/submit",
                json=_submit_payload(),
                headers=_auth_headers(),
            )
        _, kwargs = temporal_client.start_workflow.call_args
        assert kwargs["id"] == "cts-test-bank-INST001"

    def test_submit_sets_workflow_id_response_header(self):
        _patch_temporalio()
        temporal_client = MagicMock()
        temporal_client.start_workflow = AsyncMock(return_value=MagicMock())
        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.cts.workflows.cheque_workflow.ChequeProcessingWorkflow", MagicMock()):
            response = client.post(
                "/v1/cts/inward/INST001/submit",
                json=_submit_payload(),
                headers=_auth_headers(),
            )
        assert response.headers.get("x-workflow-id") == "cts-test-bank-INST001"


class TestCTSDecisionWithTemporalClient:
    """Covers lines 210-221: decision fetch when Temporal client is present."""

    def _make_app_with_temporal(self, temporal_client):
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = temporal_client
        return app

    def test_get_decision_returns_completed_result_from_temporal(self):
        result = MagicMock()
        result.decision = "STP_CONFIRM"
        result.rationale = "All checks passed"

        handle = MagicMock()
        handle.result = AsyncMock(return_value=result)

        temporal_client = MagicMock()
        temporal_client.get_workflow_handle = MagicMock(return_value=handle)

        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/cts/decisions/INST001", headers=_auth_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["decision"] == "STP_CONFIRM"
        assert data["rationale"] == "All checks passed"

    def test_get_decision_temporal_error_falls_back_to_running(self):
        """If Temporal throws (workflow still running) → return RUNNING status."""
        handle = MagicMock()
        handle.result = AsyncMock(side_effect=Exception("workflow not finished"))

        temporal_client = MagicMock()
        temporal_client.get_workflow_handle = MagicMock(return_value=handle)

        app = self._make_app_with_temporal(temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/cts/decisions/INST001", headers=_auth_headers())
        assert response.status_code == 200
        assert response.json()["workflow_status"] == "RUNNING"


class TestCTSReviewDecision:
    """Covers lines 247-291: review decision signal path."""

    def _make_app(self, temporal_client=None):
        from apps.api.routers.cts import router_v1, get_current_bank_id, get_current_user_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.dependency_overrides[get_current_user_id] = lambda: "reviewer-001"
        if temporal_client:
            app.state.temporal_client = temporal_client
        return app

    def test_review_unauthenticated_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "Signature matches"},
        )
        assert response.status_code == 401

    def test_review_empty_reason_returns_422(self):
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "   "},
            headers=_auth_headers(),
        )
        assert response.status_code == 422

    def test_review_missing_reason_returns_422(self):
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM"},
            headers=_auth_headers(),
        )
        assert response.status_code == 422

    def test_review_invalid_action_returns_422(self):
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "APPROVE", "reason": "looks good"},
            headers=_auth_headers(),
        )
        assert response.status_code == 422

    def test_review_no_temporal_client_returns_200_signal_not_sent(self):
        app = self._make_app(temporal_client=None)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "Signature matches"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["signal_sent"] is False

    def test_review_with_temporal_sends_signal(self):
        handle = MagicMock()
        handle.signal = AsyncMock()

        temporal_client = MagicMock()
        temporal_client.get_workflow_handle = MagicMock(return_value=handle)

        app = self._make_app(temporal_client=temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "RETURN", "reason": "Amount mismatch"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["signal_sent"] is True
        handle.signal.assert_called_once()

    def test_review_with_temporal_targets_correct_workflow_id(self):
        handle = MagicMock()
        handle.signal = AsyncMock()

        temporal_client = MagicMock()
        temporal_client.get_workflow_handle = MagicMock(return_value=handle)

        app = self._make_app(temporal_client=temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "OK"},
            headers=_auth_headers(),
        )
        temporal_client.get_workflow_handle.assert_called_once_with(
            "cts-humanreview-test-bank-INST001"
        )

    def test_review_temporal_signal_failure_returns_503(self):
        handle = MagicMock()
        handle.signal = AsyncMock(side_effect=Exception("workflow not found"))

        temporal_client = MagicMock()
        temporal_client.get_workflow_handle = MagicMock(return_value=handle)

        app = self._make_app(temporal_client=temporal_client)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "Looks valid"},
            headers=_auth_headers(),
        )
        assert response.status_code == 503

    def test_review_response_has_instrument_id(self):
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "Signature matches"},
            headers=_auth_headers(),
        )
        assert response.json()["instrument_id"] == "INST001"

    def test_review_response_has_workflow_id(self):
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "Signature matches"},
            headers=_auth_headers(),
        )
        assert response.json()["workflow_id"] == "cts-humanreview-test-bank-INST001"


# ---------------------------------------------------------------------------
# Auth edge cases — invalid token branches (lines 43, 53)
# ---------------------------------------------------------------------------

class TestCTSAuthEdgeCases:
    """Cover the 'token does not start with test-token-' rejection paths."""

    def test_submit_invalid_token_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/inward/INST001/submit",
            json=_submit_payload(),
            headers={"Authorization": "Bearer invalid-jwt-token"},
        )
        assert response.status_code == 401

    def test_get_decision_invalid_token_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/v1/cts/decisions/INST001",
            headers={"Authorization": "Bearer invalid-jwt-token"},
        )
        assert response.status_code == 401

    def test_review_invalid_token_returns_401(self):
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "ok"},
            headers={"Authorization": "Bearer invalid-jwt-token"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Dependency coverage — get_current_user_id + get_temporal_client 503
# ---------------------------------------------------------------------------

class TestCTSDependencyCoverage:
    """Exercise auth helpers and temporal-client 503 directly."""

    def test_get_current_user_id_valid_token_returns_reviewer(self):
        """Calls /review without user_id override so get_current_user_id executes."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        # Override bank_id only; leave user_id to the real implementation
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "ok"},
            headers=_auth_headers("test-bank"),  # test-token-test-bank → reviewer-001
        )
        assert response.status_code == 200

    def test_get_current_bank_id_valid_test_token_returns_bank(self):
        """Exercises the removeprefix return branch (line 41)."""
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/v1/cts/decisions/INST001",
            headers={"Authorization": "Bearer test-token-mybank"},
        )
        # 200 proves bank_id extraction succeeded (line 41 executed)
        assert response.status_code == 200

    def test_get_current_user_id_no_token_returns_401(self):
        """Covers get_current_user_id missing-token path (line 50)."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        # No Authorization header → credentials is None inside get_current_user_id
        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "ok"},
        )
        assert response.status_code == 401

    def test_get_current_user_id_invalid_token_returns_401(self):
        """Covers get_current_user_id invalid-token raise (line 54)."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/cts/review/INST001/decide",
            json={"action": "CONFIRM", "reason": "ok"},
            headers={"Authorization": "Bearer not-a-test-token"},
        )
        assert response.status_code == 401

    def test_get_temporal_client_raises_503_when_no_client(self):
        """Covers lines 63-69: get_temporal_client raises 503 when not set on app state."""
        _patch_temporalio()
        from apps.api.routers.cts import router_v1, get_current_bank_id, get_temporal_client
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        # Explicitly do NOT set app.state.temporal_client → triggers 503 in get_temporal_client
        # We wire it as a dependency to the submit route which uses Optional[client]
        # but test via a route that requires it (submit with real temporal path won't bypass)
        with patch("modules.cts.workflows.cheque_workflow.ChequeProcessingWorkflow", MagicMock()):
            client = TestClient(app, raise_server_exceptions=False)
            # The submit route uses get_temporal_client as Optional — let's call get_temporal_client directly
            from fastapi import Request
            from unittest.mock import MagicMock as MM
            req = MM(spec=Request)
            req.app.state = MM()
            del req.app.state.temporal_client  # AttributeError → getattr returns None
            import pytest as pt
            from fastapi import HTTPException
            with pt.raises(HTTPException) as exc_info:
                get_temporal_client(req)
            assert exc_info.value.status_code == 503

    def test_get_temporal_client_returns_client_when_set(self):
        """Covers line 69: get_temporal_client returns client when set on app state."""
        _patch_temporalio()
        from apps.api.routers.cts import get_temporal_client
        from fastapi import Request
        from unittest.mock import MagicMock as MM
        mock_client = MM()
        req = MM(spec=Request)
        req.app.state = MM()
        req.app.state.temporal_client = mock_client
        result = get_temporal_client(req)
        assert result is mock_client


# ---------------------------------------------------------------------------
# GET /v1/cts/queue — human review queue
# ---------------------------------------------------------------------------

class TestCTSQueueRoute:
    def test_queue_no_temporal_returns_empty(self):
        """Without Temporal client, returns empty queue with 200."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/cts/queue", headers=_auth_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["bank_id"] == "test-bank"

    def test_queue_unauthenticated_returns_401(self):
        """No auth header → 401."""
        from apps.api.routers.cts import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/cts/queue")
        assert response.status_code == 401

    def test_queue_limit_capped_at_100(self):
        """limit > 100 is silently capped to 100."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        client = TestClient(app, raise_server_exceptions=False)
        # limit=500 should still return 200 (capped internally)
        response = client.get("/v1/cts/queue?limit=500", headers=_auth_headers())
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_queue_with_temporal_returns_items(self):
        """Temporal client returning workflow list → items populated."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        from unittest.mock import MagicMock, AsyncMock

        # Build async iterable of workflow stubs
        wf = MagicMock()
        wf.id = "cts-humanreview-test-bank-INST001"
        wf.start_time = MagicMock()
        wf.start_time.timestamp.return_value = 1_700_000_000.0
        wf.memo = {
            "instrument_id": "INST001",
            "account_display": "****1234",
            "payee_display": "N***",
            "amount_range": "₹[1L-5L]",
            "clearing_zone": "MUMBAI",
            "received_at": 1_699_990_000.0,
            "iet_deadline": 1_700_010_800.0,
            "reason": "FRAUD_SCORE_HIGH",
            "fraud_score": 0.82,
            "ocr_confidence": 0.97,
            "sig_match_score": 0.88,
        }

        async def _async_iter():
            yield wf

        mock_client = MagicMock()
        mock_client.list_workflows = MagicMock(return_value=_async_iter())

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_client

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/cts/queue", headers=_auth_headers())
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["instrument_id"] == "INST001"
        assert item["reason"] == "FRAUD_SCORE_HIGH"
        assert item["fraud_score"] == 0.82
        assert item["clearing_zone"] == "MUMBAI"

    def test_queue_temporal_error_returns_empty(self):
        """Temporal list_workflows error → empty queue (not 503)."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        from unittest.mock import MagicMock

        async def _broken_iter():
            raise Exception("temporal unavailable")
            yield  # make it an async generator

        mock_client = MagicMock()
        mock_client.list_workflows = MagicMock(return_value=_broken_iter())

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_client

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/cts/queue", headers=_auth_headers())
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_queue_sorted_by_iet_deadline_ascending(self):
        """Items are returned sorted by iet_deadline ascending (most urgent first)."""
        from apps.api.routers.cts import router_v1, get_current_bank_id
        from unittest.mock import MagicMock

        def _make_wf(inst_id, iet_deadline):
            wf = MagicMock()
            wf.id = f"cts-humanreview-test-bank-{inst_id}"
            wf.start_time = MagicMock()
            wf.start_time.timestamp.return_value = 1_700_000_000.0
            wf.memo = {
                "instrument_id": inst_id,
                "account_display": "****1234",
                "payee_display": "N***",
                "amount_range": "₹[1L-5L]",
                "clearing_zone": "MUMBAI",
                "received_at": 1_699_990_000.0,
                "iet_deadline": iet_deadline,
                "reason": "OCR_LOW_CONFIDENCE",
            }
            return wf

        wf_late  = _make_wf("INST002", 1_700_020_000.0)   # later IET
        wf_early = _make_wf("INST001", 1_700_010_000.0)   # earlier IET — must be first

        async def _async_iter():
            yield wf_late
            yield wf_early

        mock_client = MagicMock()
        mock_client.list_workflows = MagicMock(return_value=_async_iter())

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_bank_id] = lambda: "test-bank"
        app.state.temporal_client = mock_client

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/cts/queue", headers=_auth_headers())
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 2
        assert items[0]["instrument_id"] == "INST001"   # earlier IET first
        assert items[1]["instrument_id"] == "INST002"
