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
from unittest.mock import AsyncMock, MagicMock, patch


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
            bank_type="SB",
        )
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/v1/msv/validate", json={
            "instrument_id": "CHQ-001",
            "bank_id": "kotak-mah",
            "account_number": "1234567890",
            "cheque_image_url": "minio://bucket/img.jpg",
        }, headers=_auth_headers())
        assert resp.status_code == 200

    def _account_meta(self):
        from modules.msv.mandates.models import AccountMandateMeta, MandateRule, MandateRuleType
        return AccountMandateMeta(
            account_hash="hash123", bank_id="kotak-mah", operation_type="S",
            mandate=MandateRule(rule_type=MandateRuleType.ALL_OF, mandatory_ids=["SIG-1"]),
            signatories=[],
        )

    def test_already_started_deterministic_workflow_returns_started_not_pending(self):
        """Real bug class: MSVValidationWorkflow's id is deterministic per instrument
        (msv-{bank_id}-{instrument_id}). Before this fix, a retriggered validation hit
        WorkflowAlreadyStartedError, which the bare `except Exception` treated the same as Temporal being
        unreachable — the caller was told WORKFLOW_PENDING (nothing started) when a validation was in fact
        already running. Exercises the REAL MSVWorkflowInput/MSVInput construction (msv.py used to build it
        with the wrong flat-field shape entirely; fixed the same day as this test)."""
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        from temporalio.exceptions import WorkflowAlreadyStartedError

        captured = {}

        class FakeTemporal:
            async def start_workflow(self, fn, inp, *, id, task_queue):
                captured["inp"] = inp
                raise WorkflowAlreadyStartedError(id, "MSVValidationWorkflow")

        app = FastAPI()
        app.include_router(router_v1)
        app.state.temporal_client = FakeTemporal()
        app.state.db_pool_cts = MagicMock()
        app.state.config_service = MagicMock()
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", bank_type="SB",
        )
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.msv.mandates.repository.load_account_mandate_meta",
                   new=AsyncMock(return_value=self._account_meta())):
            resp = client.post("/v1/msv/validate", json={
                "instrument_id": "CHQ-002",
                "bank_id": "kotak-mah",
                "account_number": "1234567890",
                "cheque_image_url": "minio://bucket/img.jpg",
            }, headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["reason_code"] == "WORKFLOW_STARTED"
        # The real MSVWorkflowInput/MSVInput pydantic models must round-trip without error.
        assert captured["inp"].msv_input.instrument_id == "CHQ-002"
        assert captured["inp"].account_meta.account_hash == "hash123"

    def test_mandate_not_found_routes_to_human_review_not_a_default(self):
        """Vault-miss philosophy: no mandate on record must never be treated as a permissive pass, and
        must not be conflated with Temporal being unavailable."""
        from apps.api.routers.msv import router_v1, get_current_user_context
        from modules.msv.mandates.repository import MandateNotFoundError
        from shared.auth.rbac import Role, UserContext

        app = FastAPI()
        app.include_router(router_v1)
        app.state.temporal_client = MagicMock()
        app.state.db_pool_cts = MagicMock()
        app.state.config_service = MagicMock()
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", bank_type="SB",
        )
        client = TestClient(app, raise_server_exceptions=False)

        with patch("modules.msv.mandates.repository.load_account_mandate_meta",
                   new=AsyncMock(side_effect=MandateNotFoundError("no row"))):
            resp = client.post("/v1/msv/validate", json={
                "instrument_id": "CHQ-003", "bank_id": "kotak-mah",
                "account_number": "1234567890", "cheque_image_url": "minio://bucket/img.jpg",
            }, headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "AMBER" and body["reason_code"] == "MANDATE_NOT_FOUND"

    def test_missing_instrument_id_returns_422(self):
        from apps.api.routers.msv import router_v1, get_current_user_context
        from shared.auth.rbac import Role, UserContext
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: UserContext(
            user_id="test-user", role=Role.OPS_MANAGER,
            bank_id="kotak-mah", bank_type="SB",
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
            bank_id="kotak-mah", bank_type="SB",
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
            bank_id="kotak-mah", bank_type="SB",
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
            bank_id="kotak-mah", bank_type="SB",
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
            bank_id="kotak-mah", bank_type="SB",
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
            bank_id="kotak-mah", bank_type="SB",
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
            bank_id="kotak-mah", bank_type="SB",
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
