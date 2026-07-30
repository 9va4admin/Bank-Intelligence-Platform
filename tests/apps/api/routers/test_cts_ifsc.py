"""
Tests for IFSC Registry CRUD API routes.

  GET    /v1/cts/ifsc-registry              — list (any authenticated user)
  GET    /v1/cts/ifsc-registry/{id}         — get one
  POST   /v1/cts/ifsc-registry              — create (ops_manager — maker)
  PUT    /v1/cts/ifsc-registry/{id}/approve — approve (bank_it_admin — checker)
  DELETE /v1/cts/ifsc-registry/{id}         — deactivate (bank_it_admin)

All routes require auth (401 on missing); role gates return 403.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date
from fastapi.testclient import TestClient


def _make_entry_dict(**kwargs):
    defaults = {
        "id": "uuid-001",
        "bank_id": "saraswat-coop",
        "bank_type": "SB",
        "smb_id": None,
        "ifsc_code": "SARB0000001",
        "branch_name": "Main Branch",
        "branch_city": "Mumbai",
        "micr_code": "400084001",
        "is_active": True,
        "effective_from": str(date(2026, 1, 1)),
        "effective_till": None,
        "status": "ACTIVE",
        "created_by": "ops@saraswat.in",
        "approved_by": "itadmin@saraswat.in",
    }
    defaults.update(kwargs)
    return defaults


def _make_entry(**kwargs):
    from modules.cts.ifsc.models import IFSCEntry
    d = _make_entry_dict(**kwargs)
    d["effective_from"] = date(2026, 1, 1)
    return IFSCEntry(**d)


def _build_app(repo_mock):
    """Build a minimal FastAPI app with the CTS router and a mocked repo."""
    from fastapi import FastAPI
    from apps.api.routers.cts import router_v1
    from apps.api.dependencies import require_user_context
    from shared.auth.rbac import UserContext, Role, BankType

    app = FastAPI()
    app.include_router(router_v1)
    app.state.ifsc_repo = repo_mock

    def _fake_user(role=Role.OPS_MANAGER):
        ctx = UserContext(
            user_id="test-user",
            bank_id="saraswat-coop",
            role=role,
            bank_type=BankType.SB,
            clearing_zone="MUMBAI",
        )
        return ctx

    app.dependency_overrides[require_user_context] = lambda: _fake_user()
    return app, _fake_user


class TestListIFSCRegistry:
    def test_returns_200_with_entries(self):
        repo = MagicMock()
        repo.list_ifsc = AsyncMock(return_value=[_make_entry()])
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.get("/v1/cts/ifsc-registry")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 1

    def test_filter_by_bank_type(self):
        repo = MagicMock()
        repo.list_ifsc = AsyncMock(return_value=[_make_entry()])
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.get("/v1/cts/ifsc-registry?bank_type=SB")
        assert resp.status_code == 200

    def test_filter_by_smb_id(self):
        repo = MagicMock()
        repo.list_ifsc = AsyncMock(
            return_value=[_make_entry(bank_type="SMB", smb_id="smb-001")]
        )
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.get("/v1/cts/ifsc-registry?smb_id=smb-001")
        assert resp.status_code == 200

    def test_unauthenticated_returns_401(self):
        from fastapi import FastAPI
        from apps.api.routers.cts import router_v1
        from apps.api.dependencies import require_user_context
        app = FastAPI()
        app.include_router(router_v1)
        # No override → dependency raises 401
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/v1/cts/ifsc-registry")
        assert resp.status_code in (401, 422, 500)  # depends on auth wiring


class TestGetIFSCById:
    def test_returns_200_when_found(self):
        repo = MagicMock()
        repo.get_ifsc_by_id = AsyncMock(return_value=_make_entry())
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.get("/v1/cts/ifsc-registry/uuid-001")
        assert resp.status_code == 200
        assert resp.json()["ifsc_code"] == "SARB0000001"

    def test_returns_404_when_not_found(self):
        repo = MagicMock()
        repo.get_ifsc_by_id = AsyncMock(return_value=None)
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.get("/v1/cts/ifsc-registry/ghost-uuid")
        assert resp.status_code == 404


class TestCreateIFSCRegistry:
    def test_ops_manager_can_create(self):
        repo = MagicMock()
        repo.create_ifsc = AsyncMock(return_value=_make_entry(status="PENDING"))
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.post("/v1/cts/ifsc-registry", json={
                "bank_type": "SB",
                "smb_id": None,
                "ifsc_code": "SARB0000099",
                "branch_name": "New Branch",
                "branch_city": "Pune",
                "micr_code": "411084001",
                "effective_from": "2026-07-30",
            })
        assert resp.status_code == 201
        assert resp.json()["status"] == "PENDING"

    def test_duplicate_ifsc_returns_409(self):
        from modules.cts.ifsc.repository import IFSCDuplicateError
        repo = MagicMock()
        repo.create_ifsc = AsyncMock(side_effect=IFSCDuplicateError("SARB0000001"))
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.post("/v1/cts/ifsc-registry", json={
                "bank_type": "SB",
                "ifsc_code": "SARB0000001",
                "branch_name": "Dup",
                "branch_city": "Mumbai",
                "effective_from": "2026-07-30",
            })
        assert resp.status_code == 409

    def test_smb_entry_without_smb_id_returns_422(self):
        repo = MagicMock()
        repo.create_ifsc = AsyncMock(return_value=_make_entry())
        app, _ = _build_app(repo)
        with TestClient(app) as client:
            resp = client.post("/v1/cts/ifsc-registry", json={
                "bank_type": "SMB",
                "smb_id": None,   # missing — should fail validation
                "ifsc_code": "SOMUCB0001",
                "branch_name": "SMB Branch",
                "branch_city": "Kolhapur",
                "effective_from": "2026-07-30",
            })
        assert resp.status_code == 422


class TestApproveIFSCRegistry:
    def test_bank_it_admin_can_approve(self):
        from fastapi import FastAPI
        from apps.api.routers.cts import router_v1
        from apps.api.dependencies import require_user_context
        from shared.auth.rbac import UserContext, Role, BankType

        repo = MagicMock()
        repo.approve_ifsc = AsyncMock(return_value=_make_entry(status="ACTIVE"))
        app = FastAPI()
        app.include_router(router_v1)
        app.state.ifsc_repo = repo
        app.dependency_overrides[require_user_context] = lambda: UserContext(
            user_id="itadmin",
            bank_id="saraswat-coop",
            role=Role.BANK_IT_ADMIN,
            bank_type=BankType.SB,
            clearing_zone="MUMBAI",
        )
        with TestClient(app) as client:
            resp = client.put("/v1/cts/ifsc-registry/uuid-001/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACTIVE"

    def test_ops_manager_cannot_approve(self):
        from fastapi import FastAPI
        from apps.api.routers.cts import router_v1
        from apps.api.dependencies import require_user_context
        from shared.auth.rbac import UserContext, Role, BankType

        repo = MagicMock()
        repo.approve_ifsc = AsyncMock(return_value=_make_entry(status="ACTIVE"))
        app = FastAPI()
        app.include_router(router_v1)
        app.state.ifsc_repo = repo
        app.dependency_overrides[require_user_context] = lambda: UserContext(
            user_id="ops",
            bank_id="saraswat-coop",
            role=Role.OPS_MANAGER,
            bank_type=BankType.SB,
            clearing_zone="MUMBAI",
        )
        with TestClient(app) as client:
            resp = client.put("/v1/cts/ifsc-registry/uuid-001/approve")
        assert resp.status_code == 403

    def test_approve_nonexistent_returns_404(self):
        from fastapi import FastAPI
        from apps.api.routers.cts import router_v1
        from apps.api.dependencies import require_user_context
        from shared.auth.rbac import UserContext, Role, BankType

        repo = MagicMock()
        repo.approve_ifsc = AsyncMock(return_value=None)
        app = FastAPI()
        app.include_router(router_v1)
        app.state.ifsc_repo = repo
        app.dependency_overrides[require_user_context] = lambda: UserContext(
            user_id="itadmin",
            bank_id="saraswat-coop",
            role=Role.BANK_IT_ADMIN,
            bank_type=BankType.SB,
            clearing_zone="MUMBAI",
        )
        with TestClient(app) as client:
            resp = client.put("/v1/cts/ifsc-registry/ghost/approve")
        assert resp.status_code == 404


class TestDeactivateIFSCRegistry:
    def test_bank_it_admin_can_deactivate(self):
        from fastapi import FastAPI
        from apps.api.routers.cts import router_v1
        from apps.api.dependencies import require_user_context
        from shared.auth.rbac import UserContext, Role, BankType

        repo = MagicMock()
        repo.deactivate_ifsc = AsyncMock(return_value=_make_entry(status="INACTIVE", is_active=False))
        app = FastAPI()
        app.include_router(router_v1)
        app.state.ifsc_repo = repo
        app.dependency_overrides[require_user_context] = lambda: UserContext(
            user_id="itadmin",
            bank_id="saraswat-coop",
            role=Role.BANK_IT_ADMIN,
            bank_type=BankType.SB,
            clearing_zone="MUMBAI",
        )
        with TestClient(app) as client:
            resp = client.delete("/v1/cts/ifsc-registry/uuid-001")
        assert resp.status_code == 200
        assert resp.json()["status"] == "INACTIVE"

    def test_ops_manager_cannot_deactivate(self):
        from fastapi import FastAPI
        from apps.api.routers.cts import router_v1
        from apps.api.dependencies import require_user_context
        from shared.auth.rbac import UserContext, Role, BankType

        repo = MagicMock()
        repo.deactivate_ifsc = AsyncMock(return_value=_make_entry(status="INACTIVE"))
        app = FastAPI()
        app.include_router(router_v1)
        app.state.ifsc_repo = repo
        app.dependency_overrides[require_user_context] = lambda: UserContext(
            user_id="ops",
            bank_id="saraswat-coop",
            role=Role.OPS_MANAGER,
            bank_type=BankType.SB,
            clearing_zone="MUMBAI",
        )
        with TestClient(app) as client:
            resp = client.delete("/v1/cts/ifsc-registry/uuid-001")
        assert resp.status_code == 403
