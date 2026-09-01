"""
TDD — RED first.
Tests for:
  POST /v1/cts/outward/scanner/session/open   → opens EEH session in cts.eeh_sessions
  POST /v1/cts/outward/scanner/session/close  → marks session CLOSED
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from shared.auth.rbac import Role, BankType, PermissionLevel, UserContext


def _make_ctx(role="ops_manager", bank_id="test-bank", bank_type=BankType.SB):
    return UserContext(
        user_id="u-test",
        role=Role(role),
        bank_id=bank_id,
        bank_type=bank_type,
        permission_level=PermissionLevel.READ_ONLY,
    )


@pytest.fixture
def app():
    from apps.api.main import app as _app
    return _app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def _auth_override(ctx):
    from apps.api.routers.cts import get_current_user_context
    app_ref = None
    async def _dep():
        return ctx
    return {get_current_user_context: _dep}


# ── POST /v1/cts/outward/scanner/session/open ────────────────────────────────

class TestScannerSessionOpen:

    def test_open_session_returns_session_id(self, app, client):
        ctx = _make_ctx()
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.fetchrow = AsyncMock(return_value=None)  # no existing ACTIVE session
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        app.state.db_pool_cts = mock_pool

        resp = client.post(
            "/v1/cts/outward/scanner/session/open",
            json={"branch_id": "BR-MUM-001", "hub_type": "EEH", "cert_fingerprint": "abc123"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 201
        data = resp.json()
        assert "session_id" in data
        assert data["session_id"].startswith("SES-")
        assert data["status"] == "ACTIVE"

    def test_open_session_403_wrong_role(self, app, client):
        ctx = _make_ctx(role="fraud_analyst")
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx

        resp = client.post(
            "/v1/cts/outward/scanner/session/open",
            json={"branch_id": "BR-MUM-001", "hub_type": "EEH", "cert_fingerprint": "abc123"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_open_session_409_already_active(self, app, client):
        ctx = _make_ctx()
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        # existing ACTIVE session found
        mock_conn.fetchrow = AsyncMock(return_value={"session_id": "SES-EXISTING"})

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        app.state.db_pool_cts = mock_pool

        resp = client.post(
            "/v1/cts/outward/scanner/session/open",
            json={"branch_id": "BR-MUM-001", "hub_type": "EEH", "cert_fingerprint": "abc123"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 409

    def test_open_session_503_no_db(self, app, client):
        ctx = _make_ctx()
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx
        if hasattr(app.state, "db_pool_cts"):
            del app.state.db_pool_cts

        resp = client.post(
            "/v1/cts/outward/scanner/session/open",
            json={"branch_id": "BR-MUM-001", "hub_type": "EEH", "cert_fingerprint": "abc123"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 503


# ── POST /v1/cts/outward/scanner/session/close ───────────────────────────────

class TestScannerSessionClose:

    def test_close_session_success(self, app, client):
        ctx = _make_ctx()
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.fetchrow = AsyncMock(return_value={
            "session_id": "SES-ABC", "status": "ACTIVE", "bank_id": "test-bank",
        })
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        app.state.db_pool_cts = mock_pool

        resp = client.post(
            "/v1/cts/outward/scanner/session/close",
            json={"session_id": "SES-ABC"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["status"] == "CLOSED"

    def test_close_session_404_not_found(self, app, client):
        ctx = _make_ctx()
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        app.state.db_pool_cts = mock_pool

        resp = client.post(
            "/v1/cts/outward/scanner/session/close",
            json={"session_id": "SES-NOTEXIST"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 404

    def test_close_session_409_already_closed(self, app, client):
        ctx = _make_ctx()
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.fetchrow = AsyncMock(return_value={
            "session_id": "SES-ABC", "status": "CLOSED", "bank_id": "test-bank",
        })

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        app.state.db_pool_cts = mock_pool

        resp = client.post(
            "/v1/cts/outward/scanner/session/close",
            json={"session_id": "SES-ABC"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 409

    def test_close_session_403_cross_bank(self, app, client):
        ctx = _make_ctx(bank_id="bank-A")
        from apps.api.routers.cts import get_current_user_context
        app.dependency_overrides[get_current_user_context] = lambda: ctx

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        # session belongs to a different bank
        mock_conn.fetchrow = AsyncMock(return_value={
            "session_id": "SES-ABC", "status": "ACTIVE", "bank_id": "bank-B",
        })

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        app.state.db_pool_cts = mock_pool

        resp = client.post(
            "/v1/cts/outward/scanner/session/close",
            json={"session_id": "SES-ABC"},
        )
        app.dependency_overrides.clear()
        assert resp.status_code == 403
