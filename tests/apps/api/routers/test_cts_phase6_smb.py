"""
Phase 6 TDD tests — SMB forwarding log (all SMBs, SB-level) and SMB list:
  GET /v1/cts/smb/forwarding-log
  GET /v1/cts/smb  (existing, but test the shape for frontend wiring)

RED phase: forwarding-log tests expected to FAIL before implementation.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext


def _make_app():
    from apps.api.routers.cts import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _sb_ctx(bank_id="saraswat-coop"):
    return UserContext(
        user_id="ops-001",
        bank_id=bank_id,
        bank_type=BankType.SB,
        role=Role.OPS_MANAGER,
        permission_level=PermissionLevel.EDIT,
    )


def _smb_ctx(bank_id="vasavi-001"):
    return UserContext(
        user_id="ops-smb-001",
        bank_id=bank_id,
        bank_type=BankType.SMB,
        role=Role.OPS_MANAGER,
        permission_level=PermissionLevel.EDIT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/smb/forwarding-log — All SMBs' forwarding events (SB-only)
# ─────────────────────────────────────────────────────────────────────────────

class TestSMBForwardingLogAllEndpoint:
    """All-SMBs forwarding log for SB view — consolidates events from all sponsored SMBs."""

    def test_forwarding_log_all_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/forwarding-log")
        assert r.status_code == 401

    def test_forwarding_log_all_smb_user_forbidden(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _smb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/forwarding-log")
        assert r.status_code == 403

    def test_forwarding_log_all_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/forwarding-log")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert isinstance(body["items"], list)

    def test_forwarding_log_all_returns_items_with_bank_name(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[
            {
                "forwarding_id": "fwd-aabbccdd",
                "instrument_id": "CHQ-MH-20260901-00001",
                "sub_member_id": "smb-mh-vasavi",
                "bank_name": "Vasavi Co-operative Bank",
                "micr_prefix_matched": "400053",
                "forwarding_status": "COMPLETED",
                "terminal_decision": "STP_CONFIRM",
                "iet_deadline_utc": "2026-09-01T12:45:00Z",
                "received_at": "2026-09-01T09:41:12Z",
                "forwarded_at": "2026-09-01T09:41:13Z",
                "completed_at": "2026-09-01T09:41:14Z",
                "iet_seconds_remaining": 11027,
                "failure_reason": None,
            },
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/forwarding-log")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["forwarding_id"] == "fwd-aabbccdd"
        assert item["bank_name"] == "Vasavi Co-operative Bank"
        assert item["forwarding_status"] == "COMPLETED"

    def test_forwarding_log_all_respects_limit(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/forwarding-log?limit=50")
        assert r.status_code == 200

    def test_forwarding_log_all_failed_only_filter(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/forwarding-log?status_filter=FAILED")
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/smb — SMB list endpoint (existing, test shape for wiring)
# ─────────────────────────────────────────────────────────────────────────────

class TestSMBListEndpoint:
    """Verify SMB list returns fields needed by CTSSMBRegistry."""

    def test_smb_list_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb")
        assert r.status_code == 401

    def test_smb_list_smb_user_forbidden(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _smb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb")
        assert r.status_code == 403

    def test_smb_list_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb")
        assert r.status_code == 200
        body = r.json()
        assert "sub_members" in body
        assert "total" in body
        assert body["total"] == 0
