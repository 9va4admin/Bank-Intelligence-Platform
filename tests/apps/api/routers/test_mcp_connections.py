"""
Tests for apps/api/routers/mcp_connections.py

MCP Connections API — configure CBS and vault MCP connections per bank / SMB.

Routes:
  GET    /v1/admin/mcp-connections/preflight     — pre-flight gate for clearing
  GET    /v1/admin/mcp-connections/              — list connections (scoped)
  POST   /v1/admin/mcp-connections/              — create connection
  GET    /v1/admin/mcp-connections/{id}          — get single connection
  PUT    /v1/admin/mcp-connections/{id}          — update connection
  DELETE /v1/admin/mcp-connections/{id}          — delete connection
  POST   /v1/admin/mcp-connections/{id}/test     — test connectivity
  POST   /v1/admin/mcp-connections/{id}/sync     — trigger vault sync

Coverage targets:
  - Auth: 401 unauthenticated, 403 wrong role
  - SB admin sees all connections; SMB admin sees only their own
  - SMB_CBS requires smb_id → 422 without it
  - Duplicate connection → 409
  - endpoint_url is masked in every response (never returned raw)
  - SMB admin cannot access another SMB's connection → 403
  - test_connection: success path + failure path
  - trigger_sync: only CBS types, only ACTIVE connections
  - preflight: all ACTIVE → clearing_allowed=True; any non-ACTIVE → blocked
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── App factory helpers ──────────────────────────────────────────────────────

def _make_app(role="bank_it_admin", bank_type="SB", smb_id=None, bank_id="saraswat-coop"):
    from apps.api.routers.mcp_connections import (
        router_v1,
        get_current_user,
        get_connection_tester,
        get_store,
        _ConnectionStore,
    )
    app = FastAPI()
    app.include_router(router_v1)

    fresh_store = _ConnectionStore()
    app.dependency_overrides[get_store] = lambda: fresh_store
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": bank_id,
        "user_id": f"user-{bank_id}",
        "role": role,
        "bank_type": bank_type,
        "smb_id": smb_id,
    }

    async def _mock_tester_success(row):
        return True, 38, None

    app.dependency_overrides[get_connection_tester] = lambda: _mock_tester_success
    return app, fresh_store


def _unauthed_app():
    from apps.api.routers.mcp_connections import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


# ── Shared payload helpers ───────────────────────────────────────────────────

_SB_CBS_PAYLOAD = {
    "connection_type": "SB_CBS",
    "cbs_vendor": "finacle",
    "endpoint_url": "https://cbs.saraswat.internal/finacle/api",
    "vault_secret_ref": "secret/astra/saraswat-coop/cbs/finacle",
}

_SMB_CBS_PAYLOAD = {
    "connection_type": "SMB_CBS",
    "smb_id": "smb-ucb-001",
    "smb_name": "Citizen UCB",
    "cbs_vendor": "bancs",
    "endpoint_url": "https://cbs.citizen-ucb.internal/bancs/api",
    "vault_secret_ref": "secret/astra/saraswat-coop/smb/smb-ucb-001/cbs",
}

_SIG_VAULT_PAYLOAD = {
    "connection_type": "SIGNATURE_VAULT",
    "endpoint_url": "redis://redis-cts.astra-cts-saraswat-coop:6379",
    "vault_secret_ref": "secret/astra/saraswat-coop/redis/cts/auth_token",
}


# ── 1. Authentication ────────────────────────────────────────────────────────

class TestAuthentication:
    def test_list_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/admin/mcp-connections/").status_code == 401

    def test_create_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).status_code == 401

    def test_preflight_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/admin/mcp-connections/preflight").status_code == 401


# ── 2. Role-based access ─────────────────────────────────────────────────────

class TestRoleAccess:
    def test_ops_reviewer_cannot_list(self):
        app, _ = _make_app(role="ops_reviewer")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/v1/admin/mcp-connections/").status_code == 403

    def test_fraud_analyst_cannot_create(self):
        app, _ = _make_app(role="fraud_analyst")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).status_code == 403

    def test_compliance_officer_cannot_access(self):
        app, _ = _make_app(role="compliance_officer")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/v1/admin/mcp-connections/").status_code == 403

    def test_bank_it_admin_can_list(self):
        app, _ = _make_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/v1/admin/mcp-connections/").status_code == 200

    def test_ops_manager_can_list(self):
        app, _ = _make_app(role="ops_manager")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/v1/admin/mcp-connections/").status_code == 200


# ── 3. List connections ──────────────────────────────────────────────────────

class TestListConnections:
    def test_empty_list_for_new_bank(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/admin/mcp-connections/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connections"] == []
        assert data["total"] == 0
        assert data["bank_id"] == "saraswat-coop"

    def test_sb_admin_sees_all_connections(self):
        app, store = _make_app(bank_type="SB")
        # Seed SB_CBS + SMB_CBS + SIGNATURE_VAULT
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD)
        client.post("/v1/admin/mcp-connections/", json=_SIG_VAULT_PAYLOAD)

        resp = client.get("/v1/admin/mcp-connections/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

    def test_smb_admin_sees_only_own_connection(self):
        sb_app, sb_store = _make_app(bank_type="SB", bank_id="saraswat-coop")
        sb_client = TestClient(sb_app, raise_server_exceptions=False)
        sb_client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        sb_client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD)

        # SMB admin for smb-ucb-001 using same bank_id (sponsor bank)
        from apps.api.routers.mcp_connections import get_current_user, get_connection_tester, get_store
        from fastapi import FastAPI
        from apps.api.routers.mcp_connections import router_v1
        smb_app = FastAPI()
        smb_app.include_router(router_v1)
        smb_app.dependency_overrides[get_store] = lambda: sb_store   # same store
        smb_app.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "saraswat-coop",
            "user_id": "smb-admin",
            "role": "bank_it_admin",
            "bank_type": "SMB",
            "smb_id": "smb-ucb-001",
        }
        async def _ok(row): return True, 10, None
        smb_app.dependency_overrides[get_connection_tester] = lambda: _ok

        smb_client = TestClient(smb_app, raise_server_exceptions=False)
        resp = smb_client.get("/v1/admin/mcp-connections/")
        assert resp.status_code == 200
        conns = resp.json()["connections"]
        # SMB sees only their SMB_CBS row, not SB_CBS
        assert all(c["smb_id"] == "smb-ucb-001" for c in conns)
        assert all(c["connection_type"] == "SMB_CBS" for c in conns)


# ── 4. Create connection ─────────────────────────────────────────────────────

class TestCreateConnection:
    def test_create_sb_cbs_returns_201(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert data["connection_type"] == "SB_CBS"
        assert data["status"] == "PENDING"
        assert data["bank_id"] == "saraswat-coop"

    def test_create_smb_cbs_returns_201(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD)
        assert resp.status_code == 201
        assert resp.json()["smb_id"] == "smb-ucb-001"
        assert resp.json()["smb_name"] == "Citizen UCB"

    def test_create_signature_vault_returns_201(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/v1/admin/mcp-connections/", json=_SIG_VAULT_PAYLOAD)
        assert resp.status_code == 201
        assert resp.json()["connection_type"] == "SIGNATURE_VAULT"

    def test_create_pps_vault_returns_201(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        payload = {
            "connection_type": "PPS_VAULT",
            "endpoint_url": "redis://redis-cts.astra-cts-saraswat-coop:6379",
            "vault_secret_ref": "secret/astra/saraswat-coop/redis/cts/auth_token",
        }
        resp = client.post("/v1/admin/mcp-connections/", json=payload)
        assert resp.status_code == 201

    def test_create_cancelled_leaf_returns_201(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        payload = {
            "connection_type": "CANCELLED_LEAF",
            "endpoint_url": "redis://redis-cts.astra-cts-saraswat-coop:6379",
            "vault_secret_ref": "secret/astra/saraswat-coop/redis/cts/auth_token",
        }
        resp = client.post("/v1/admin/mcp-connections/", json=payload)
        assert resp.status_code == 201

    def test_smb_cbs_without_smb_id_returns_422(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        payload = {"connection_type": "SMB_CBS", "cbs_vendor": "bancs"}
        resp = client.post("/v1/admin/mcp-connections/", json=payload)
        assert resp.status_code == 422

    def test_duplicate_sb_cbs_returns_409(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        resp = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        assert resp.status_code == 409

    def test_duplicate_smb_cbs_same_smb_returns_409(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD)
        resp = client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD)
        assert resp.status_code == 409

    def test_two_smb_cbs_different_smb_ids_both_succeed(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD)
        smb2 = {**_SMB_CBS_PAYLOAD, "smb_id": "smb-ucb-002", "smb_name": "Merchant UCB"}
        resp = client.post("/v1/admin/mcp-connections/", json=smb2)
        assert resp.status_code == 201

    def test_endpoint_url_masked_in_create_response(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        data = resp.json()
        assert "endpoint_url_masked" in data
        # Full URL must not appear in response
        assert "endpoint_url" not in data or data.get("endpoint_url") is None
        # Masked value should contain *** and the domain
        masked = data["endpoint_url_masked"]
        assert "***" in masked
        assert "cbs.saraswat.internal" in masked

    def test_created_by_set_to_current_user(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        assert resp.json()["created_by"] == "user-saraswat-coop"

    def test_smb_admin_cannot_create_for_different_smb(self):
        from apps.api.routers.mcp_connections import get_current_user, get_connection_tester, get_store, router_v1, _ConnectionStore
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router_v1)
        fresh = _ConnectionStore()
        app.dependency_overrides[get_store] = lambda: fresh
        app.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "saraswat-coop",
            "user_id": "smb-admin",
            "role": "bank_it_admin",
            "bank_type": "SMB",
            "smb_id": "smb-ucb-001",
        }
        async def _ok(row): return True, 10, None
        app.dependency_overrides[get_connection_tester] = lambda: _ok

        client = TestClient(app, raise_server_exceptions=False)
        payload = {**_SMB_CBS_PAYLOAD, "smb_id": "smb-ucb-DIFFERENT"}
        resp = client.post("/v1/admin/mcp-connections/", json=payload)
        assert resp.status_code == 403


# ── 5. Get single connection ─────────────────────────────────────────────────

class TestGetConnection:
    def test_get_existing_returns_200(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        resp = client.get(f"/v1/admin/mcp-connections/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_nonexistent_returns_404(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/admin/mcp-connections/does-not-exist")
        assert resp.status_code == 404

    def test_smb_admin_cannot_get_different_smb_connection(self):
        sb_app, sb_store = _make_app(bank_type="SB", bank_id="saraswat-coop")
        sb_client = TestClient(sb_app, raise_server_exceptions=False)
        created = sb_client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD).json()

        from apps.api.routers.mcp_connections import get_current_user, get_connection_tester, get_store, router_v1
        from fastapi import FastAPI
        smb_app2 = FastAPI()
        smb_app2.include_router(router_v1)
        smb_app2.dependency_overrides[get_store] = lambda: sb_store
        smb_app2.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "saraswat-coop",
            "user_id": "other-smb-admin",
            "role": "bank_it_admin",
            "bank_type": "SMB",
            "smb_id": "smb-ucb-DIFFERENT",  # different SMB
        }
        async def _ok(row): return True, 10, None
        smb_app2.dependency_overrides[get_connection_tester] = lambda: _ok

        smb_client2 = TestClient(smb_app2, raise_server_exceptions=False)
        resp = smb_client2.get(f"/v1/admin/mcp-connections/{created['id']}")
        assert resp.status_code == 403


# ── 6. Update connection ─────────────────────────────────────────────────────

class TestUpdateConnection:
    def test_update_endpoint_url(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        resp = client.put(
            f"/v1/admin/mcp-connections/{created['id']}",
            json={"endpoint_url": "https://cbs-new.saraswat.internal/api"},
        )
        assert resp.status_code == 200
        # Status reset to PENDING on update
        assert resp.json()["status"] == "PENDING"

    def test_update_resets_status_to_pending(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        # Manually mark ACTIVE
        store.update(created["id"], {"status": "ACTIVE"})
        resp = client.put(
            f"/v1/admin/mcp-connections/{created['id']}",
            json={"cbs_vendor": "flexcube"},
        )
        assert resp.json()["status"] == "PENDING"

    def test_update_nonexistent_returns_404(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.put("/v1/admin/mcp-connections/no-such-id", json={"cbs_vendor": "bancs"})
        assert resp.status_code == 404


# ── 7. Delete connection ─────────────────────────────────────────────────────

class TestDeleteConnection:
    def test_delete_returns_204(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        resp = client.delete(f"/v1/admin/mcp-connections/{created['id']}")
        assert resp.status_code == 204

    def test_deleted_connection_no_longer_listed(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        client.delete(f"/v1/admin/mcp-connections/{created['id']}")
        resp = client.get("/v1/admin/mcp-connections/")
        assert resp.json()["total"] == 0

    def test_delete_nonexistent_returns_404(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/v1/admin/mcp-connections/no-such-id")
        assert resp.status_code == 404


# ── 8. Test connection ───────────────────────────────────────────────────────

class TestTestConnection:
    def test_test_connection_success_returns_200(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        resp = client.post(f"/v1/admin/mcp-connections/{created['id']}/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["latency_ms"] == 38
        assert data["error"] is None
        assert data["connection_id"] == created["id"]

    def test_test_connection_sets_status_active_on_success(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        client.post(f"/v1/admin/mcp-connections/{created['id']}/test")
        resp = client.get(f"/v1/admin/mcp-connections/{created['id']}")
        assert resp.json()["status"] == "ACTIVE"

    def test_test_connection_failure_sets_status_error(self):
        from apps.api.routers.mcp_connections import get_current_user, get_connection_tester, get_store, router_v1, _ConnectionStore
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router_v1)
        fresh = _ConnectionStore()
        app.dependency_overrides[get_store] = lambda: fresh
        app.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "saraswat-coop", "user_id": "admin", "role": "bank_it_admin",
            "bank_type": "SB", "smb_id": None,
        }

        async def _fail(row):
            return False, None, "Connection refused: CBS unreachable"

        app.dependency_overrides[get_connection_tester] = lambda: _fail
        client = TestClient(app, raise_server_exceptions=False)

        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        resp = client.post(f"/v1/admin/mcp-connections/{created['id']}/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Connection refused" in data["error"]

        # Status must be ERROR
        get_resp = client.get(f"/v1/admin/mcp-connections/{created['id']}")
        assert get_resp.json()["status"] == "ERROR"

    def test_test_nonexistent_connection_returns_404(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/v1/admin/mcp-connections/no-such-id/test")
        assert resp.status_code == 404

    def test_test_connection_records_latency(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        client.post(f"/v1/admin/mcp-connections/{created['id']}/test")
        get_resp = client.get(f"/v1/admin/mcp-connections/{created['id']}")
        assert get_resp.json()["last_test_latency_ms"] == 38


# ── 9. Trigger sync ──────────────────────────────────────────────────────────

class TestTriggerSync:
    def _active_cbs_connection(self, client, store, payload=None):
        payload = payload or _SB_CBS_PAYLOAD
        created = client.post("/v1/admin/mcp-connections/", json=payload).json()
        store.update(created["id"], {"status": "ACTIVE"})
        return created

    def test_trigger_sync_returns_workflow_id(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = self._active_cbs_connection(client, store)
        resp = client.post(f"/v1/admin/mcp-connections/{created['id']}/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert "workflow_id" in data
        assert data["connection_id"] == created["id"]
        assert "cts-vaultsync" in data["workflow_id"]

    def test_trigger_sync_on_pending_connection_returns_409(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        # status is PENDING (not ACTIVE)
        resp = client.post(f"/v1/admin/mcp-connections/{created['id']}/sync")
        assert resp.status_code == 409

    def test_trigger_sync_on_vault_type_returns_422(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = client.post("/v1/admin/mcp-connections/", json=_SIG_VAULT_PAYLOAD).json()
        store.update(created["id"], {"status": "ACTIVE"})
        resp = client.post(f"/v1/admin/mcp-connections/{created['id']}/sync")
        assert resp.status_code == 422

    def test_trigger_sync_updates_last_sync_at(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        created = self._active_cbs_connection(client, store)
        client.post(f"/v1/admin/mcp-connections/{created['id']}/sync")
        get_resp = client.get(f"/v1/admin/mcp-connections/{created['id']}")
        assert get_resp.json()["last_sync_at"] is not None

    def test_trigger_sync_nonexistent_returns_404(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/v1/admin/mcp-connections/no-such-id/sync")
        assert resp.status_code == 404


# ── 10. Preflight ────────────────────────────────────────────────────────────

class TestPreflight:
    def test_preflight_empty_bank_clearing_allowed(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/admin/mcp-connections/preflight")
        assert resp.status_code == 200
        data = resp.json()
        assert data["clearing_allowed"] is True
        assert data["blocking_count"] == 0

    def test_preflight_all_active_clearing_allowed(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        c1 = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        c2 = client.post("/v1/admin/mcp-connections/", json=_SIG_VAULT_PAYLOAD).json()
        store.update(c1["id"], {"status": "ACTIVE"})
        store.update(c2["id"], {"status": "ACTIVE"})

        resp = client.get("/v1/admin/mcp-connections/preflight")
        assert resp.json()["clearing_allowed"] is True
        assert resp.json()["blocking_count"] == 0

    def test_preflight_pending_connection_blocks_clearing(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        c1 = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        store.update(c1["id"], {"status": "ACTIVE"})
        # Vault connection is PENDING
        client.post("/v1/admin/mcp-connections/", json=_SIG_VAULT_PAYLOAD)

        resp = client.get("/v1/admin/mcp-connections/preflight")
        assert resp.json()["clearing_allowed"] is False
        assert resp.json()["blocking_count"] >= 1

    def test_preflight_error_connection_blocks_clearing(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        c1 = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        store.update(c1["id"], {"status": "ERROR"})

        resp = client.get("/v1/admin/mcp-connections/preflight")
        assert resp.json()["clearing_allowed"] is False

    def test_preflight_response_includes_check_list(self):
        app, store = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        c1 = client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD).json()
        store.update(c1["id"], {"status": "ACTIVE"})

        resp = client.get("/v1/admin/mcp-connections/preflight")
        checks = resp.json()["checks"]
        assert len(checks) == 1
        assert checks[0]["connection_type"] == "SB_CBS"
        assert checks[0]["status"] == "ACTIVE"


# ── 11. Security invariants ──────────────────────────────────────────────────

class TestSecurityInvariants:
    def test_full_endpoint_url_never_returned(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        payload = {**_SB_CBS_PAYLOAD, "endpoint_url": "https://secret:P@ssw0rd@cbs.internal/api"}
        resp = client.post("/v1/admin/mcp-connections/", json=payload)
        body = resp.text
        assert "P@ssw0rd" not in body
        assert "secret:" not in body

    def test_list_response_urls_all_masked(self):
        app, _ = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)
        client.post("/v1/admin/mcp-connections/", json=_SMB_CBS_PAYLOAD)
        resp = client.get("/v1/admin/mcp-connections/")
        for conn in resp.json()["connections"]:
            # raw endpoint_url must not be a field in the response model
            assert "endpoint_url" not in conn or conn.get("endpoint_url") is None
            if conn.get("endpoint_url_masked"):
                assert "***" in conn["endpoint_url_masked"]

    def test_bank_isolation_different_bank_cannot_see_connections(self):
        app_a, store_a = _make_app(bank_id="bank-alpha")
        client_a = TestClient(app_a, raise_server_exceptions=False)
        client_a.post("/v1/admin/mcp-connections/", json=_SB_CBS_PAYLOAD)

        # Bank B with separate store (as it would be in production — separate namespace)
        app_b, _ = _make_app(bank_id="bank-beta")
        client_b = TestClient(app_b, raise_server_exceptions=False)
        resp = client_b.get("/v1/admin/mcp-connections/")
        assert resp.json()["total"] == 0   # bank-beta cannot see bank-alpha's connections
