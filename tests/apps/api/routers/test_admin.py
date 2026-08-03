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


# ---------------------------------------------------------------------------
# Vault Sig-Sync Status  GET /v1/admin/vault/sig-sync-status
# ---------------------------------------------------------------------------

class TestVaultSigSyncStatusRoute:
    def _client(self, role="bank_it_admin", db_counts=None, redis_key_count=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.api.routers.admin import router_v1, get_current_user
        from apps.api.routers.admin import get_vault_db_pool, get_vault_redis

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "test-bank", "user_id": "user-001", "role": role
        }

        # Mock DB pool returning counts
        _db_counts = db_counts or {"accounts": 50000, "specimens": 127000}

        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        async def _fake_db_pool():
            pool = MagicMock()
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value={
                "accounts": _db_counts["accounts"],
                "specimens": _db_counts["specimens"],
            })
            conn.fetchval = AsyncMock(return_value=None)  # no last_sync_at
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            return pool

        # Mock Redis with a scan_iter that yields N keys
        _redis_keys = redis_key_count if redis_key_count is not None else 49200

        def _fake_redis():
            redis = MagicMock()
            redis.scan_iter = MagicMock(return_value=iter(
                [f"sig:test-bank:key{i}" for i in range(_redis_keys)]
            ))
            return redis

        app.dependency_overrides[get_vault_db_pool] = _fake_db_pool
        app.dependency_overrides[get_vault_redis] = _fake_redis
        return TestClient(app, raise_server_exceptions=False)

    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/admin/vault/sig-sync-status")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_access(self):
        client = self._client(role="ops_reviewer")
        response = client.get("/v1/admin/vault/sig-sync-status")
        assert response.status_code == 403

    def test_bank_it_admin_gets_200(self):
        client = self._client(role="bank_it_admin")
        response = client.get("/v1/admin/vault/sig-sync-status")
        assert response.status_code == 200

    def test_ops_manager_gets_200(self):
        client = self._client(role="ops_manager")
        response = client.get("/v1/admin/vault/sig-sync-status")
        assert response.status_code == 200

    def test_response_has_yugabyte_counts(self):
        client = self._client(db_counts={"accounts": 50000, "specimens": 127000})
        data = client.get("/v1/admin/vault/sig-sync-status").json()
        assert data["yugabyte_accounts"] == 50000
        assert data["yugabyte_specimens"] == 127000

    def test_response_has_redis_key_count(self):
        client = self._client(redis_key_count=49200)
        data = client.get("/v1/admin/vault/sig-sync-status").json()
        assert data["redis_sig_keys"] == 49200

    def test_coverage_pct_computed(self):
        client = self._client(db_counts={"accounts": 1000, "specimens": 2000},
                              redis_key_count=800)
        data = client.get("/v1/admin/vault/sig-sync-status").json()
        assert data["coverage_pct"] == pytest.approx(80.0, abs=0.1)

    def test_gap_accounts_is_difference(self):
        client = self._client(db_counts={"accounts": 1000, "specimens": 2000},
                              redis_key_count=800)
        data = client.get("/v1/admin/vault/sig-sync-status").json()
        assert data["gap_accounts"] == 200

    def test_response_has_request_id(self):
        client = self._client()
        data = client.get("/v1/admin/vault/sig-sync-status").json()
        assert "request_id" in data

    def test_full_coverage_when_redis_exceeds_db(self):
        """Redis can have slightly more keys than DB if warm ran concurrently — clamp to 100."""
        client = self._client(db_counts={"accounts": 1000, "specimens": 2000},
                              redis_key_count=1050)
        data = client.get("/v1/admin/vault/sig-sync-status").json()
        assert data["coverage_pct"] <= 100.0


# ---------------------------------------------------------------------------
# Vault Warm-Redis  POST /v1/admin/vault/warm-redis
# ---------------------------------------------------------------------------

class TestVaultWarmRedisRoute:
    def _client(self, role="ops_manager", trigger_result=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.api.routers.admin import router_v1, get_current_user
        from apps.api.routers.admin import get_vault_warm_trigger

        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "test-bank", "user_id": "user-001", "role": role
        }

        _result = trigger_result or {
            "workflow_id": "cts-warmredis-test-bank-20260723T143200",
            "status": "TRIGGERED",
        }

        async def _fake_trigger(bank_id: str):
            return _result

        app.dependency_overrides[get_vault_warm_trigger] = lambda: _fake_trigger
        return TestClient(app, raise_server_exceptions=False)

    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/admin/vault/warm-redis")
        assert response.status_code == 401

    def test_bank_it_admin_cannot_trigger(self):
        """Warm-redis is a maker action — ops_manager only."""
        client = self._client(role="bank_it_admin")
        response = client.post("/v1/admin/vault/warm-redis")
        assert response.status_code == 403

    def test_ops_reviewer_cannot_trigger(self):
        client = self._client(role="ops_reviewer")
        response = client.post("/v1/admin/vault/warm-redis")
        assert response.status_code == 403

    def test_ops_manager_gets_202(self):
        client = self._client(role="ops_manager")
        response = client.post("/v1/admin/vault/warm-redis")
        assert response.status_code == 202

    def test_response_has_workflow_id(self):
        client = self._client()
        data = client.post("/v1/admin/vault/warm-redis").json()
        assert "workflow_id" in data
        assert data["workflow_id"]

    def test_response_status_triggered(self):
        client = self._client()
        data = client.post("/v1/admin/vault/warm-redis").json()
        assert data["status"] == "TRIGGERED"

    def test_response_has_triggered_at(self):
        client = self._client()
        data = client.post("/v1/admin/vault/warm-redis").json()
        assert "triggered_at" in data

    def test_response_has_request_id(self):
        client = self._client()
        data = client.post("/v1/admin/vault/warm-redis").json()
        assert "request_id" in data
