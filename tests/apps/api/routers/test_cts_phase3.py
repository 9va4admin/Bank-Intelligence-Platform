"""
Phase 3 TDD tests — Vault Health & Data endpoints:
  GET /v1/cts/vault/health
  GET /v1/cts/vault/misses
  GET /v1/cts/vault/pps
  GET /v1/cts/vault/stop-cheques

RED phase: all tests expected to FAIL before implementation.
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


def _fraud_ctx(bank_id="saraswat-coop"):
    return UserContext(
        user_id="fa-001",
        bank_id=bank_id,
        bank_type=BankType.SB,
        role=Role.FRAUD_ANALYST,
        permission_level=PermissionLevel.READ_ONLY,
    )


def _mock_pool(rows=None):
    """Build a mock asyncpg pool that returns `rows` on fetch/fetchrow."""
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=rows or [])
    pool.fetchrow = AsyncMock(return_value=rows[0] if rows else None)
    pool.fetchval = AsyncMock(return_value=rows[0] if rows else 0)
    return pool


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/vault/health
# ─────────────────────────────────────────────────────────────────────────────

class TestVaultHealthEndpoint:
    """Vault health summary: key counts + hit rates for sig and PPS vaults."""

    def test_vault_health_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/health")
        assert r.status_code == 401

    def test_vault_health_no_db_returns_empty_stats(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/health")
        assert r.status_code == 200
        body = r.json()
        assert "sig_key_count" in body
        assert "pps_key_count" in body
        assert "sig_status" in body
        assert "pps_status" in body

    def test_vault_health_returns_key_counts_from_db(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        # fetchval returns count for each query
        pool.fetchval = AsyncMock(side_effect=[18432, 12817])
        pool.fetchrow = AsyncMock(return_value=None)
        pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/health")
        assert r.status_code == 200
        body = r.json()
        assert body["sig_key_count"] == 18432
        assert body["pps_key_count"] == 12817

    def test_vault_health_scoped_to_bank_id(self):
        """DB query must use bank_id from JWT — not a param from the caller."""
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _smb_ctx()
        pool = MagicMock()
        pool.fetchval = AsyncMock(side_effect=[2841, 1924])
        pool.fetchrow = AsyncMock(return_value=None)
        pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/health")
        assert r.status_code == 200
        body = r.json()
        assert body["bank_id"] == "vasavi-001"

    def test_vault_health_status_healthy_when_keys_present(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetchval = AsyncMock(side_effect=[5000, 3000])
        pool.fetchrow = AsyncMock(return_value=None)
        pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/health")
        assert r.status_code == 200
        body = r.json()
        assert body["sig_status"] == "HEALTHY"
        assert body["pps_status"] == "HEALTHY"


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/vault/misses
# ─────────────────────────────────────────────────────────────────────────────

class TestVaultMissesEndpoint:
    """Today's vault miss events — accounts that routed to HUMAN_REVIEW."""

    def test_vault_misses_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/misses")
        assert r.status_code == 401

    def test_vault_misses_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/misses")
        assert r.status_code == 200
        body = r.json()
        assert "misses" in body
        assert isinstance(body["misses"], list)

    def test_vault_misses_returns_todays_events(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[
            {
                "instrument_id": "CHQ-001",
                "account_last4": "7821",
                "vault_type": "SIGNATURE",
                "miss_reason": "No specimen",
                "routed_to": "HUMAN_REVIEW",
                "event_time": "2026-09-02T10:42:31+05:30",
            }
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/misses")
        assert r.status_code == 200
        body = r.json()
        assert len(body["misses"]) == 1
        miss = body["misses"][0]
        assert miss["account_last4"] == "7821"
        assert miss["vault_type"] == "SIGNATURE"
        assert miss["routed_to"] == "HUMAN_REVIEW"

    def test_vault_misses_miss_reason_never_exposes_full_account(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[
            {
                "instrument_id": "CHQ-002",
                "account_last4": "1234",
                "vault_type": "PPS",
                "miss_reason": "PPS not registered",
                "routed_to": "HUMAN_REVIEW",
                "event_time": "2026-09-02T09:00:00+05:30",
            }
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/misses")
        body = r.json()
        # account_last4 is max 4 chars — no full account number
        assert len(body["misses"][0]["account_last4"]) <= 4


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/vault/pps
# ─────────────────────────────────────────────────────────────────────────────

class TestVaultPPSEndpoint:
    """List PPS vault entries for the bank."""

    def test_vault_pps_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/pps")
        assert r.status_code == 401

    def test_vault_pps_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/pps")
        assert r.status_code == 200
        body = r.json()
        assert "entries" in body
        assert isinstance(body["entries"], list)

    def test_vault_pps_returns_entries(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[
            {
                "entry_id": "uuid-001",
                "account_last4": "4521",
                "cheque_number": "000001",
                "cheque_date": "2026-09-15",
                "amount_range": "₹[1L-5L]",
                "status": "REGISTERED",
                "expires_at": "2026-12-31",
                "registered_at": "2026-09-01T10:00:00+05:30",
                "registration_channel": "INTERNET_BANKING",
            }
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/pps")
        assert r.status_code == 200
        body = r.json()
        assert len(body["entries"]) == 1
        entry = body["entries"][0]
        assert entry["account_display"] == "****4521"
        assert entry["cheque_number"] == "000001"
        assert entry["status"] == "REGISTERED"

    def test_vault_pps_status_filter(self):
        """Only non-CONFIRMED_PAID entries returned by default."""
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/pps?status=REGISTERED")
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/vault/stop-cheques
# ─────────────────────────────────────────────────────────────────────────────

class TestVaultStopChequesEndpoint:
    """List stop payment instructions for the bank."""

    def test_vault_stop_cheques_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/stop-cheques")
        assert r.status_code == 401

    def test_vault_stop_cheques_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/stop-cheques")
        assert r.status_code == 200
        body = r.json()
        assert "instructions" in body
        assert isinstance(body["instructions"], list)

    def test_vault_stop_cheques_returns_active_instructions(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        pool = MagicMock()
        pool.fetch = AsyncMock(return_value=[
            {
                "stop_id": "uuid-stop-001",
                "account_last4": "2233",
                "scope": "SINGLE_CHEQUE",
                "cheque_number": "000045",
                "reason": "Lost / Stolen",
                "status": "ACTIVE",
                "created_at": "2026-09-01T11:30:00+05:30",
            }
        ])
        app.state.db_pool_cts = pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/stop-cheques")
        assert r.status_code == 200
        body = r.json()
        assert len(body["instructions"]) == 1
        inst = body["instructions"][0]
        assert inst["account_display"] == "****2233"
        assert inst["cheque_number"] == "000045"
        assert inst["status"] == "ACTIVE"

    def test_vault_stop_cheques_fraud_analyst_denied(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _fraud_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/vault/stop-cheques")
        assert r.status_code == 403
