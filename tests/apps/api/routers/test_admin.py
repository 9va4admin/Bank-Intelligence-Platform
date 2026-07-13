"""
Tests for apps/api/routers/admin.py

Admin API endpoints:
  GET    /v1/admin/config/thresholds          — list Layer 3 thresholds (bank_it_admin, ops_manager)
  POST   /v1/admin/config/thresholds          — maker submits threshold change (ops_manager only)
  POST   /v1/admin/config/thresholds/{change_id}/approve  — checker approves (bank_it_admin only)
  POST   /v1/admin/config/thresholds/{change_id}/reject   — checker rejects (bank_it_admin only)
  GET    /v1/admin/users                      — list bank users (bank_it_admin only)
  POST   /v1/admin/users/{user_id}/role       — assign role (bank_it_admin only)
  POST   /v1/admin/onboard                    — trigger BankOnboardingWorkflow (bank_it_admin only)
  GET    /v1/admin/health                     — infra health summary (bank_it_admin only)

Rules enforced:
  - All routes require JWT auth (unauthenticated → 401)
  - Role-specific access: maker/checker separation enforced
  - ops_reviewer and fraud_analyst cannot access admin routes
  - compliance_officer cannot access admin routes
  - Maker cannot approve their own change
  - No PII — threshold keys/values only, user IDs not full profiles
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(role="bank_it_admin"):
    from apps.api.routers.admin import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _unauthed_app():
    from apps.api.routers.admin import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


class TestThresholdsListRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_access(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        assert response.status_code == 403

    def test_fraud_analyst_cannot_access(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        assert response.status_code == 403

    def test_compliance_officer_cannot_access(self):
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        assert response.status_code == 403

    def test_bank_it_admin_gets_200(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        assert response.status_code == 200

    def test_ops_manager_gets_200(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        assert response.status_code == 200

    def test_response_has_thresholds_list(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        data = response.json()
        assert "thresholds" in data

    def test_response_has_total(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        data = response.json()
        assert "total" in data


class TestThresholdChangeSubmitRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "config_key": "iet_minutes",
            "new_value": "180",
            "reason": "Regulatory update",
        })
        assert response.status_code == 401

    def test_bank_it_admin_cannot_submit_maker_change(self):
        # bank_it_admin is the checker — only ops_manager can be maker
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "config_key": "iet_minutes",
            "new_value": "180",
            "reason": "Test",
        })
        assert response.status_code == 403

    def test_ops_manager_can_submit_change(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "config_key": "iet_minutes",
            "new_value": "180",
            "reason": "Regulatory update",
        })
        assert response.status_code in (200, 201, 202)

    def test_missing_config_key_returns_422(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "new_value": "180",
            "reason": "Missing key",
        })
        assert response.status_code == 422

    def test_missing_reason_returns_422(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "config_key": "iet_minutes",
            "new_value": "180",
        })
        assert response.status_code == 422

    def test_response_has_change_id(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "config_key": "iet_minutes",
            "new_value": "180",
            "reason": "Regulatory update",
        })
        if response.status_code in (200, 201, 202):
            assert "change_id" in response.json()

    def test_response_has_status_pending(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "config_key": "iet_minutes",
            "new_value": "180",
            "reason": "Regulatory update",
        })
        if response.status_code in (200, 201, 202):
            assert response.json().get("status") == "PENDING_APPROVAL"


class TestThresholdApproveRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds/chg-001/approve")
        assert response.status_code == 401

    def test_ops_manager_cannot_approve(self):
        # ops_manager is the maker — cannot also be checker
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds/chg-001/approve")
        assert response.status_code == 403

    def test_bank_it_admin_can_approve(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds/chg-001/approve")
        assert response.status_code in (200, 404)

    def test_response_has_status(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds/chg-001/approve")
        if response.status_code == 200:
            assert "status" in response.json()


class TestThresholdRejectRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds/chg-001/reject")
        assert response.status_code == 401

    def test_ops_manager_cannot_reject(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds/chg-001/reject")
        assert response.status_code == 403

    def test_bank_it_admin_can_reject(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds/chg-001/reject")
        assert response.status_code in (200, 404)


class TestUsersListRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/admin/users")
        assert response.status_code == 401

    def test_ops_manager_cannot_list_users(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.get("/v1/admin/users")
        assert response.status_code == 403

    def test_bank_it_admin_gets_200(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.get("/v1/admin/users")
        assert response.status_code == 200

    def test_response_has_users_list(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.get("/v1/admin/users")
        assert "users" in response.json()

    def test_response_never_contains_password(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.get("/v1/admin/users")
        assert "password" not in response.text


class TestUserRoleAssignRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/admin/users/user-001/role", json={"role": "ops_reviewer"})
        assert response.status_code == 401

    def test_ops_manager_cannot_assign_role(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/admin/users/user-001/role", json={"role": "ops_reviewer"})
        assert response.status_code == 403

    def test_bank_it_admin_can_assign_role(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/admin/users/user-001/role", json={"role": "ops_reviewer"})
        assert response.status_code in (200, 404)

    def test_invalid_role_returns_422(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/admin/users/user-001/role", json={"role": "super_admin"})
        assert response.status_code == 422

    def test_missing_role_returns_422(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/admin/users/user-001/role", json={})
        assert response.status_code == 422


class TestHealthRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/admin/health")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_access(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/admin/health")
        assert response.status_code == 403

    def test_bank_it_admin_gets_200(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.get("/v1/admin/health")
        assert response.status_code == 200

    def test_response_has_services(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.get("/v1/admin/health")
        assert "services" in response.json()

    def test_response_has_overall_status(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.get("/v1/admin/health")
        assert "overall_status" in response.json()


class TestAdminAuthEdgeCases:
    """get_current_user delegates to the shared, middleware-backed
    require_user_context — no per-router token parsing, no test-token backdoor."""

    def test_invalid_token_returns_401(self):
        from apps.api.routers.admin import router_v1
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/admin/users",
            headers={"Authorization": "Bearer not-a-valid-token"},
        )
        assert response.status_code == 401

    def test_test_token_bearer_header_no_longer_grants_access(self):
        """Regression guard for ASTRA-01: admin.py minted bank_it_admin — the
        most privileged role — from a bare test-token-* Bearer header. That
        must never work again; only a validated session cookie can."""
        from apps.api.routers.admin import router_v1
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/admin/users",
            headers={"Authorization": "Bearer test-token-any-bank-i-want"},
        )
        assert response.status_code == 401
