"""
Tests for apps/api/routers/scanner.py — Scanner Registration & Fleet Monitoring.

Routes under test:
  POST   /v1/cts/scanner/register                    — admin provisions scanner slot
  POST   /v1/cts/scanner/{registration_id}/heartbeat — SDK heartbeat (Bearer token, NOT JWT)
  GET    /v1/cts/scanner/fleet                        — fleet status (all registrations for bank)
  GET    /v1/cts/scanner/{branch_ifsc}/status         — per-branch scanner status
  DELETE /v1/cts/scanner/{registration_id}            — deactivate registration
  POST   /v1/cts/scanner/agent/heartbeat              — Go CGO agent heartbeat (machine token)
  GET    /v1/cts/scanner/agent/status                 — branch scanner state: ACTIVE/IDLE/OFFLINE

Auth model:
  - Admin routes (register/fleet/status/delete): JWT via get_current_user dependency
  - Heartbeat: Authorization: Bearer <registration_token>  — machine identity, never a user JWT
  - Agent heartbeat: Authorization: Bearer <machine-token>  — Go CGO agent on teller PC
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_scanner_store():
    from apps.api.routers.scanner import _SCANNER_STORE, _AGENT_STORE
    _SCANNER_STORE.clear()
    _AGENT_STORE.clear()
    yield
    _SCANNER_STORE.clear()
    _AGENT_STORE.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app(role: str = "bank_it_admin"):
    from apps.api.routers.scanner import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _unauthed_app():
    from apps.api.routers.scanner import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _client(role: str = "bank_it_admin") -> TestClient:
    return TestClient(_make_app(role=role), raise_server_exceptions=False)


def _seed_registration(
    bank_id: str = "test-bank",
    branch_ifsc: str = "SRCB0000001",
    status: str = "PENDING",
    is_active: bool = True,
) -> tuple[str, str]:
    """Insert a registration directly into the in-memory store. Returns (reg_id, plaintext_token)."""
    from apps.api.routers.scanner import _SCANNER_STORE
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reg_id = str(uuid.uuid4())
    _SCANNER_STORE[reg_id] = {
        "registration_id": reg_id,
        "bank_id": bank_id,
        "branch_ifsc": branch_ifsc,
        "branch_id": f"br-{branch_ifsc.lower()}",
        "scanner_config_id": None,
        "sdk_version": None,
        "registration_token_hash": token_hash,
        "status": status,
        "last_heartbeat_at": None,
        "last_scan_submitted_at": None,
        "heartbeat_interval_seconds": 60,
        "scans_today": 0,
        "errors_today": 0,
        "last_error": None,
        "registered_at": "2026-08-11T00:00:00+00:00",
        "registered_by": "user-001",
        "is_active": is_active,
    }
    return reg_id, token


_REG_PAYLOAD = {
    "branch_ifsc": "SRCB0000001",
    "branch_id": "br-srcb0000001",
}


# ── POST /register ────────────────────────────────────────────────────────────

class TestRegister:
    def test_returns_registration_id_and_token(self):
        r = _client().post("/v1/cts/scanner/register", json=_REG_PAYLOAD)
        assert r.status_code == 201
        body = r.json()
        assert "registration_id" in body
        assert "token" in body
        assert len(body["token"]) >= 20

    def test_token_stored_as_hash_not_plaintext(self):
        r = _client().post("/v1/cts/scanner/register", json=_REG_PAYLOAD)
        assert r.status_code == 201
        from apps.api.routers.scanner import _SCANNER_STORE
        reg = _SCANNER_STORE[r.json()["registration_id"]]
        assert reg["registration_token_hash"] != r.json()["token"]

    def test_initial_status_is_pending(self):
        r = _client().post("/v1/cts/scanner/register", json=_REG_PAYLOAD)
        from apps.api.routers.scanner import _SCANNER_STORE
        reg = _SCANNER_STORE[r.json()["registration_id"]]
        assert reg["status"] == "PENDING"

    def test_unauthenticated_returns_401(self):
        r = TestClient(_unauthed_app(), raise_server_exceptions=False).post(
            "/v1/cts/scanner/register", json=_REG_PAYLOAD
        )
        assert r.status_code == 401

    def test_ops_reviewer_returns_403(self):
        r = _client("ops_reviewer").post("/v1/cts/scanner/register", json=_REG_PAYLOAD)
        assert r.status_code == 403

    def test_ops_manager_returns_403(self):
        r = _client("ops_manager").post("/v1/cts/scanner/register", json=_REG_PAYLOAD)
        assert r.status_code == 403

    def test_platform_admin_can_register(self):
        r = _client("platform_admin").post("/v1/cts/scanner/register", json=_REG_PAYLOAD)
        assert r.status_code == 201

    def test_duplicate_active_branch_returns_409(self):
        _seed_registration(branch_ifsc="SRCB0000001")
        r = _client().post("/v1/cts/scanner/register", json=_REG_PAYLOAD)
        assert r.status_code == 409


# ── POST /{id}/heartbeat ──────────────────────────────────────────────────────

class TestHeartbeat:
    def test_valid_token_returns_200(self):
        reg_id, token = _seed_registration()
        r = _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.2.0", "scans_queued": 0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "OK"
        assert "next_heartbeat_in" in r.json()

    def test_valid_token_sets_status_online(self):
        reg_id, token = _seed_registration()
        _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.2.0", "scans_queued": 0},
            headers={"Authorization": f"Bearer {token}"},
        )
        from apps.api.routers.scanner import _SCANNER_STORE
        assert _SCANNER_STORE[reg_id]["status"] == "ONLINE"
        assert _SCANNER_STORE[reg_id]["last_heartbeat_at"] is not None

    def test_valid_token_updates_sdk_version(self):
        reg_id, token = _seed_registration()
        _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "2.0.1", "scans_queued": 3},
            headers={"Authorization": f"Bearer {token}"},
        )
        from apps.api.routers.scanner import _SCANNER_STORE
        assert _SCANNER_STORE[reg_id]["sdk_version"] == "2.0.1"

    def test_wrong_token_returns_401(self):
        reg_id, _ = _seed_registration()
        r = _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.0", "scans_queued": 0},
            headers={"Authorization": "Bearer wrongtoken_xyz"},
        )
        assert r.status_code == 401

    def test_missing_auth_header_returns_401(self):
        reg_id, _ = _seed_registration()
        r = _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.0", "scans_queued": 0},
        )
        assert r.status_code == 401

    def test_unknown_registration_id_returns_404(self):
        r = _client().post(
            "/v1/cts/scanner/does-not-exist/heartbeat",
            json={"sdk_version": "1.0", "scans_queued": 0},
            headers={"Authorization": "Bearer sometoken"},
        )
        assert r.status_code == 404

    def test_deactivated_registration_returns_403(self):
        reg_id, token = _seed_registration(is_active=False)
        r = _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.0", "scans_queued": 0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_heartbeat_does_not_accept_jwt_as_token(self):
        """A user JWT string must not be accepted as a scanner token."""
        reg_id, _ = _seed_registration()
        fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYWRtaW4ifQ.fake"
        r = _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.0", "scans_queued": 0},
            headers={"Authorization": f"Bearer {fake_jwt}"},
        )
        assert r.status_code == 401

    def test_heartbeat_records_error_when_reported(self):
        reg_id, token = _seed_registration()
        _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.0", "scans_queued": 0, "last_error": "Paper jam on feeder"},
            headers={"Authorization": f"Bearer {token}"},
        )
        from apps.api.routers.scanner import _SCANNER_STORE
        assert _SCANNER_STORE[reg_id]["last_error"] == "Paper jam on feeder"


# ── GET /fleet ────────────────────────────────────────────────────────────────

class TestFleet:
    def test_returns_only_own_bank_registrations(self):
        _seed_registration(bank_id="test-bank", branch_ifsc="SRCB0000001")
        _seed_registration(bank_id="test-bank", branch_ifsc="SRCB0000002")
        _seed_registration(bank_id="other-bank", branch_ifsc="KARB0000001")
        r = _client("bank_it_admin").get("/v1/cts/scanner/fleet")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        ifscs = [reg["branch_ifsc"] for reg in body["registrations"]]
        assert "SRCB0000001" in ifscs
        assert "KARB0000001" not in ifscs

    def test_ops_manager_can_read_fleet(self):
        r = _client("ops_manager").get("/v1/cts/scanner/fleet")
        assert r.status_code == 200

    def test_ops_reviewer_cannot_read_fleet(self):
        r = _client("ops_reviewer").get("/v1/cts/scanner/fleet")
        assert r.status_code == 403

    def test_unauthenticated_returns_401(self):
        r = TestClient(_unauthed_app(), raise_server_exceptions=False).get(
            "/v1/cts/scanner/fleet"
        )
        assert r.status_code == 401

    def test_pending_registration_has_pending_health(self):
        _seed_registration(status="PENDING")
        r = _client().get("/v1/cts/scanner/fleet")
        reg = r.json()["registrations"][0]
        assert reg["health"] == "PENDING"

    def test_empty_fleet_returns_zero_total(self):
        r = _client().get("/v1/cts/scanner/fleet")
        assert r.status_code == 200
        assert r.json()["total"] == 0
        assert r.json()["registrations"] == []


# ── GET /{branch_ifsc}/status ─────────────────────────────────────────────────

class TestBranchStatus:
    def test_known_ifsc_returns_200(self):
        _seed_registration(bank_id="test-bank", branch_ifsc="SRCB0000001")
        r = _client().get("/v1/cts/scanner/SRCB0000001/status")
        assert r.status_code == 200
        assert r.json()["branch_ifsc"] == "SRCB0000001"

    def test_unknown_ifsc_returns_404(self):
        r = _client().get("/v1/cts/scanner/UNKN0000001/status")
        assert r.status_code == 404

    def test_cross_bank_ifsc_invisible(self):
        """Other bank's registered branch must not be visible."""
        _seed_registration(bank_id="other-bank", branch_ifsc="KARB0000001")
        r = _client().get("/v1/cts/scanner/KARB0000001/status")
        assert r.status_code == 404

    def test_ops_reviewer_cannot_read_status(self):
        _seed_registration(branch_ifsc="SRCB0000001")
        r = _client("ops_reviewer").get("/v1/cts/scanner/SRCB0000001/status")
        assert r.status_code == 403


# ── DELETE /{id} ──────────────────────────────────────────────────────────────

class TestDeactivate:
    def test_deactivate_sets_offline_and_inactive(self):
        reg_id, _ = _seed_registration()
        r = _client("bank_it_admin").delete(f"/v1/cts/scanner/{reg_id}")
        assert r.status_code == 200
        from apps.api.routers.scanner import _SCANNER_STORE
        reg = _SCANNER_STORE[reg_id]
        assert reg["status"] == "OFFLINE"
        assert reg["is_active"] is False

    def test_deactivated_sdk_cannot_heartbeat(self):
        reg_id, token = _seed_registration()
        _client("bank_it_admin").delete(f"/v1/cts/scanner/{reg_id}")
        r = _client().post(
            f"/v1/cts/scanner/{reg_id}/heartbeat",
            json={"sdk_version": "1.0", "scans_queued": 0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_ops_manager_cannot_deactivate(self):
        reg_id, _ = _seed_registration()
        r = _client("ops_manager").delete(f"/v1/cts/scanner/{reg_id}")
        assert r.status_code == 403

    def test_unknown_id_returns_404(self):
        r = _client("bank_it_admin").delete("/v1/cts/scanner/nonexistent-id")
        assert r.status_code == 404

    def test_cross_bank_registration_returns_404(self):
        reg_id, _ = _seed_registration(bank_id="other-bank")
        r = _client("bank_it_admin").delete(f"/v1/cts/scanner/{reg_id}")
        assert r.status_code == 404


# ── POST /agent/heartbeat ─────────────────────────────────────────────────────
# Go CGO edge agent on the teller PC calls this every 30 seconds.
# Auth: Bearer <machine token> — never a user JWT.
# Route must be declared BEFORE /{registration_id}/heartbeat to avoid FastAPI
# treating the literal "agent" as a registration_id path param.

class TestAgentHeartbeat:
    _PAYLOAD = {"bank_id": "test-bank", "branch_id": "br-001", "active_session_id": ""}

    def _post(self, token: str = "dev-machine-token-xyz", payload=None) -> object:
        app = FastAPI()
        from apps.api.routers.scanner import router_v1
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        return client.post(
            "/v1/cts/scanner/agent/heartbeat",
            json=payload or self._PAYLOAD,
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_any_bearer_token_accepted_in_dev_mode(self):
        """Dev/test: no DB, so any Bearer token auto-registers and returns OK."""
        r = self._post()
        assert r.status_code == 200
        assert r.json()["status"] == "OK"

    def test_route_not_captured_by_registration_id_param(self):
        """Critical: /agent/heartbeat must NOT match /{registration_id}/heartbeat.
        Before the fix, FastAPI treated 'agent' as a registration_id and returned 404."""
        r = self._post()
        # If routing is broken, the SDK heartbeat handler runs and returns 401/404
        # (no matching registration). The agent endpoint must return 200.
        assert r.status_code == 200

    def test_missing_authorization_header_returns_401(self):
        app = FastAPI()
        from apps.api.routers.scanner import router_v1
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/v1/cts/scanner/agent/heartbeat", json=self._PAYLOAD)
        assert r.status_code == 401

    def test_non_bearer_authorization_returns_401(self):
        app = FastAPI()
        from apps.api.routers.scanner import router_v1
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/v1/cts/scanner/agent/heartbeat",
            json=self._PAYLOAD,
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert r.status_code == 401

    def test_second_heartbeat_same_token_returns_ok(self):
        """Token already in _AGENT_STORE — second call still returns OK."""
        r1 = self._post("stable-token-abc")
        r2 = self._post("stable-token-abc")
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_heartbeat_stores_active_session_id(self):
        """When active_session_id is provided it is persisted in _AGENT_STORE."""
        token = "session-token-def"
        self._post(
            token,
            {"bank_id": "test-bank", "branch_id": "br-001", "active_session_id": "SES-123"},
        )
        from apps.api.routers.scanner import _AGENT_STORE
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        assert _AGENT_STORE[token_hash]["active_session_id"] == "SES-123"

    def test_heartbeat_updates_last_seen(self):
        token = "ts-token-ghi"
        self._post(token)
        from apps.api.routers.scanner import _AGENT_STORE
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        last_seen = _AGENT_STORE[token_hash]["last_seen"]
        assert last_seen is not None


# ── GET /agent/status ─────────────────────────────────────────────────────────
# Returns ACTIVE / IDLE / OFFLINE for a branch's scanner agent.
# Used by the Branch Dashboard's status pill.
# Auth: JWT (ops_manager, bank_it_admin).

class TestAgentStatus:
    def _seed_agent(
        self,
        token: str = "status-token",
        bank_id: str = "test-bank",
        branch_id: str = "br-001",
        last_seen_offset_seconds: int = 30,  # seconds ago (positive = in the past)
        active_session_id: str = "",
    ) -> str:
        from apps.api.routers.scanner import _AGENT_STORE
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        last_seen = datetime.now(timezone.utc) - timedelta(seconds=last_seen_offset_seconds)
        _AGENT_STORE[token_hash] = {
            "bank_id": bank_id,
            "branch_id": branch_id,
            "token_hash": token_hash,
            "last_seen": last_seen.isoformat(),
            "active_session_id": active_session_id,
        }
        return token_hash

    def _get_status(self, branch_id: str = "br-001", role: str = "ops_manager"):
        from apps.api.routers.scanner import router_v1, get_current_user
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "test-bank",
            "user_id": "user-001",
            "role": role,
        }
        client = TestClient(app, raise_server_exceptions=False)
        return client.get(f"/v1/cts/scanner/agent/status?branch_id={branch_id}")

    def test_active_session_returns_active(self):
        self._seed_agent(last_seen_offset_seconds=20, active_session_id="SES-001")
        r = self._get_status()
        assert r.status_code == 200
        assert r.json()["state"] == "ACTIVE"

    def test_recent_heartbeat_no_session_returns_idle(self):
        self._seed_agent(last_seen_offset_seconds=20, active_session_id="")
        r = self._get_status()
        assert r.status_code == 200
        assert r.json()["state"] == "IDLE"

    def test_stale_heartbeat_returns_offline(self):
        self._seed_agent(last_seen_offset_seconds=120, active_session_id="")
        r = self._get_status()
        assert r.status_code == 200
        assert r.json()["state"] == "OFFLINE"

    def test_no_heartbeat_ever_returns_offline(self):
        """Branch never connected — no entry in _AGENT_STORE."""
        r = self._get_status(branch_id="never-seen-branch")
        assert r.status_code == 200
        assert r.json()["state"] == "OFFLINE"

    def test_unauthenticated_returns_401(self):
        from apps.api.routers.scanner import router_v1
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/scanner/agent/status?branch_id=br-001")
        assert r.status_code == 401

    def test_ops_reviewer_returns_403(self):
        r = self._get_status(role="ops_reviewer")
        assert r.status_code == 403

    def test_response_includes_branch_id_and_last_seen(self):
        self._seed_agent(last_seen_offset_seconds=10, active_session_id="SES-002")
        r = self._get_status()
        assert r.status_code == 200
        body = r.json()
        assert body["branch_id"] == "br-001"
        assert "last_seen" in body
        assert body["last_seen"] is not None
