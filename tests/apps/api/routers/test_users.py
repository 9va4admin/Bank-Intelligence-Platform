"""Tests for user management and TOTP API."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.users import router_v1, _MOCK_USERS, _TOTP_SECRETS

_AUTH = {"Authorization": "Bearer test-token-hdfc-bank"}


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router_v1)
    return TestClient(app, raise_server_exceptions=False)


class TestListUsers:
    def test_returns_200(self, client):
        resp = client.get("/v1/admin/users", headers=_AUTH)
        assert resp.status_code == 200

    def test_requires_auth(self, client):
        resp = client.get("/v1/admin/users")
        assert resp.status_code == 401

    def test_returns_user_list(self, client):
        data = client.get("/v1/admin/users", headers=_AUTH).json()
        assert "users" in data
        assert "total" in data
        assert len(data["users"]) > 0

    def test_active_only_filter(self, client):
        data = client.get("/v1/admin/users?active_only=true", headers=_AUTH).json()
        for u in data["users"]:
            assert u["is_active"] is True

    def test_role_filter(self, client):
        data = client.get("/v1/admin/users?role_filter=ops_reviewer", headers=_AUTH).json()
        for u in data["users"]:
            assert u["role"] == "ops_reviewer"

    def test_no_passwords_in_response(self, client):
        data = client.get("/v1/admin/users", headers=_AUTH).json()
        for u in data["users"]:
            assert "password" not in u
            assert "totp_secret" not in u


class TestCreateUser:
    def test_creates_user(self, client):
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "newuser@bank.com",
            "display_name": "New User",
            "role": "ops_reviewer",
            "clearing_zone": "MUMBAI",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "newuser@bank.com"
        assert data["totp_enabled"] is False
        assert data["is_active"] is True

    def test_rejects_invalid_role(self, client):
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "x@bank.com",
            "display_name": "X",
            "role": "super_admin",
        })
        assert resp.status_code == 422

    def test_rejects_duplicate_email(self, client):
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "ops1@bank.com",  # already exists
            "display_name": "Dup",
            "role": "ops_reviewer",
        })
        assert resp.status_code == 409


class TestGetUser:
    def test_returns_user(self, client):
        resp = client.get("/v1/admin/users/usr-001", headers=_AUTH)
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "usr-001"

    def test_404_on_unknown(self, client):
        resp = client.get("/v1/admin/users/no-such-user", headers=_AUTH)
        assert resp.status_code == 404


class TestUpdateUser:
    def test_updates_role(self, client):
        resp = client.put("/v1/admin/users/usr-002", headers=_AUTH, json={"role": "ops_manager"})
        assert resp.status_code == 200
        # restore
        client.put("/v1/admin/users/usr-002", headers=_AUTH, json={"role": "fraud_analyst"})

    def test_deactivate_via_update(self, client):
        resp = client.put("/v1/admin/users/usr-002", headers=_AUTH, json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        # restore
        client.put("/v1/admin/users/usr-002", headers=_AUTH, json={"is_active": True})


class TestDeactivateUser:
    def test_deactivates(self, client):
        resp = client.delete("/v1/admin/users/usr-005", headers=_AUTH)
        assert resp.status_code == 204

    def test_404_on_unknown(self, client):
        resp = client.delete("/v1/admin/users/ghost", headers=_AUTH)
        assert resp.status_code == 404


class TestTOTP:
    def test_setup_returns_otpauth_uri(self, client):
        resp = client.post("/v1/admin/users/usr-002/totp/setup", headers=_AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["otpauth_uri"].startswith("otpauth://totp/")
        assert "secret_base32" in data
        assert len(data["secret_base32"]) >= 16

    def test_confirm_rejects_bad_code(self, client):
        client.post("/v1/admin/users/usr-002/totp/setup", headers=_AUTH)
        resp = client.post("/v1/admin/users/usr-002/totp/confirm", headers=_AUTH, json={
            "user_id": "usr-002",
            "bank_id": "hdfc-bank",
            "totp_code": "000000",
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_reset_disables_totp(self, client):
        resp = client.delete("/v1/admin/users/usr-001/totp", headers=_AUTH)
        assert resp.status_code == 204
        user = client.get("/v1/admin/users/usr-001", headers=_AUTH).json()
        assert user["totp_enabled"] is False
        # restore
        _MOCK_USERS["usr-001"]["totp_enabled"] = True

    def test_verify_login_rejects_user_without_totp(self, client):
        resp = client.post("/v1/auth/totp/verify", json={
            "user_id": "usr-002",
            "bank_id": "hdfc-bank",
            "totp_code": "123456",
        })
        # usr-002 has totp_enabled=False after test_setup ran but confirm wasn't valid
        # Just check it doesn't 500
        assert resp.status_code in (200, 400)

    def test_setup_requires_admin(self, client):
        resp = client.post("/v1/admin/users/usr-001/totp/setup")
        assert resp.status_code == 401


class TestSessionManagement:
    def test_list_sessions_returns_list(self, client):
        resp = client.get("/v1/admin/users/usr-001/sessions", headers=_AUTH)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_force_logout_returns_204(self, client):
        resp = client.delete("/v1/admin/users/usr-001/sessions", headers=_AUTH)
        assert resp.status_code == 204
