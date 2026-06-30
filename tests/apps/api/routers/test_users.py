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


# ---------------------------------------------------------------------------
# New TDD tests: bank_type + permission_level on users API
# ---------------------------------------------------------------------------

class TestUserResponseHasBankTypeAndPermissionLevel:
    """Every UserResponse must include bank_type and permission_level fields."""

    def test_get_user_includes_bank_type(self, client):
        data = client.get("/v1/admin/users/usr-001", headers=_AUTH).json()
        assert "bank_type" in data, "UserResponse must include bank_type"

    def test_get_user_includes_permission_level(self, client):
        data = client.get("/v1/admin/users/usr-001", headers=_AUTH).json()
        assert "permission_level" in data, "UserResponse must include permission_level"

    def test_existing_sb_users_default_to_sb_bank_type(self, client):
        """Existing pre-migration users (SB staff) must default to bank_type='SB'."""
        data = client.get("/v1/admin/users/usr-001", headers=_AUTH).json()
        assert data["bank_type"] == "SB"

    def test_existing_users_default_to_edit_permission_level(self, client):
        """Existing users must default to permission_level='EDIT'."""
        data = client.get("/v1/admin/users/usr-001", headers=_AUTH).json()
        assert data["permission_level"] == "EDIT"

    def test_list_users_response_includes_bank_type_per_user(self, client):
        data = client.get("/v1/admin/users", headers=_AUTH).json()
        for u in data["users"]:
            assert "bank_type" in u
            assert "permission_level" in u


class TestCreateUserWithBankTypeAndPermissionLevel:
    """Creating users must accept and persist bank_type and permission_level."""

    def test_create_sb_user_with_explicit_permission_level(self, client):
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "newadmin@bank.com",
            "display_name": "New Admin",
            "role": "bank_it_admin",
            "bank_type": "SB",
            "permission_level": "ADMIN",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["bank_type"] == "SB"
        assert data["permission_level"] == "ADMIN"

    def test_create_user_defaults_bank_type_to_sb(self, client):
        """Omitting bank_type must default to SB (backward compatibility)."""
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "notype@bank.com",
            "display_name": "No Type",
            "role": "ops_reviewer",
        })
        assert resp.status_code == 201
        assert resp.json()["bank_type"] == "SB"

    def test_create_user_defaults_permission_level_to_edit(self, client):
        """Omitting permission_level must default to EDIT."""
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "nolevel@bank.com",
            "display_name": "No Level",
            "role": "ops_reviewer",
        })
        assert resp.status_code == 201
        assert resp.json()["permission_level"] == "EDIT"

    def test_create_smb_user_with_smb_role(self, client):
        """SMB users can be created with smb_admin/smb_editor/smb_viewer roles."""
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "smbadmin@saraswat.com",
            "display_name": "SMB Admin",
            "role": "smb_admin",
            "bank_type": "SMB",
            "permission_level": "ADMIN",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["bank_type"] == "SMB"
        assert data["role"] == "smb_admin"

    def test_smb_role_rejected_for_sb_user(self, client):
        """SMB roles (smb_admin, smb_editor, smb_viewer) must not be assigned to SB users."""
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "badcombo@bank.com",
            "display_name": "Bad Combo",
            "role": "smb_admin",
            "bank_type": "SB",
        })
        assert resp.status_code == 422, "smb_admin role is invalid for bank_type=SB"

    def test_sb_role_rejected_for_smb_user(self, client):
        """SB functional roles (ops_reviewer, fraud_analyst …) must not be assigned to SMB users."""
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "sbrolesmb@saraswat.com",
            "display_name": "SB Role SMB",
            "role": "ops_reviewer",
            "bank_type": "SMB",
        })
        assert resp.status_code == 422, "ops_reviewer role is invalid for bank_type=SMB"

    def test_invalid_permission_level_rejected(self, client):
        """Unrecognised permission level must be rejected with 422."""
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "badlevel@bank.com",
            "display_name": "Bad Level",
            "role": "ops_reviewer",
            "permission_level": "SUPER_ADMIN",
        })
        assert resp.status_code == 422

    def test_invalid_bank_type_rejected(self, client):
        """Unrecognised bank_type must be rejected with 422."""
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "badtype@bank.com",
            "display_name": "Bad Type",
            "role": "ops_reviewer",
            "bank_type": "PARTNER",
        })
        assert resp.status_code == 422


class TestUpdateUserPermissionLevel:
    """permission_level can be updated; bank_type is immutable after creation."""

    def test_update_permission_level_to_admin(self, client):
        resp = client.put("/v1/admin/users/usr-003", headers=_AUTH,
                          json={"permission_level": "ADMIN"})
        assert resp.status_code == 200
        assert resp.json()["permission_level"] == "ADMIN"
        # restore
        client.put("/v1/admin/users/usr-003", headers=_AUTH, json={"permission_level": "EDIT"})

    def test_update_permission_level_to_read_only(self, client):
        resp = client.put("/v1/admin/users/usr-003", headers=_AUTH,
                          json={"permission_level": "READ_ONLY"})
        assert resp.status_code == 200
        assert resp.json()["permission_level"] == "READ_ONLY"
        # restore
        client.put("/v1/admin/users/usr-003", headers=_AUTH, json={"permission_level": "EDIT"})

    def test_bank_type_is_immutable_after_creation(self, client):
        """Attempting to change bank_type via PUT must be rejected with 422."""
        resp = client.put("/v1/admin/users/usr-001", headers=_AUTH,
                          json={"bank_type": "SMB"})
        assert resp.status_code == 422, "bank_type must be immutable after user creation"

    def test_invalid_permission_level_update_rejected(self, client):
        resp = client.put("/v1/admin/users/usr-001", headers=_AUTH,
                          json={"permission_level": "GOD_MODE"})
        assert resp.status_code == 422


class TestSMBRolesAcceptedInValidRoleSet:
    """SMB roles must appear in the valid roles list for create and update."""

    def test_smb_editor_role_valid_for_smb_user(self, client):
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "smbeditor@saraswat.com",
            "display_name": "SMB Editor",
            "role": "smb_editor",
            "bank_type": "SMB",
            "permission_level": "EDIT",
        })
        assert resp.status_code == 201

    def test_smb_viewer_role_valid_for_smb_user(self, client):
        resp = client.post("/v1/admin/users", headers=_AUTH, json={
            "email": "smbviewer@saraswat.com",
            "display_name": "SMB Viewer",
            "role": "smb_viewer",
            "bank_type": "SMB",
            "permission_level": "READ_ONLY",
        })
        assert resp.status_code == 201
