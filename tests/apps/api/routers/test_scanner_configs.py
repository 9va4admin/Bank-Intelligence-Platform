"""
Tests for apps/api/routers/scanner_configs.py — Scanner OEM Config CRUD.

Routes under test:
  GET    /v1/cts/scanner-configs                — list all for bank
  POST   /v1/cts/scanner-configs                — create
  GET    /v1/cts/scanner-configs/{config_id}    — get by ID
  PUT    /v1/cts/scanner-configs/{config_id}    — update (any field, including drop_folder_path)
  DELETE /v1/cts/scanner-configs/{config_id}    — soft-delete (is_active=false)

RBAC:
  bank_it_admin, ops_manager, platform_admin — full read + write
  ops_reviewer, fraud_analyst               — 403
  unauthenticated                           — 401

Audit:
  Every write (create/update/delete) emits an AuditEvent.
  Captured via a mock immudb_client on app.state.
  path changes specifically must appear in the audit payload.

Ops Dashboard flash:
  Create/update/delete emit platform.config.changed to Kafka producer if available.
  Captured via a mock kafka_producer on app.state.
"""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_store():
    from apps.api.routers.scanner_configs import _CONFIG_STORE
    _CONFIG_STORE.clear()
    yield
    _CONFIG_STORE.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app(role: str = "bank_it_admin", with_audit: bool = False, with_kafka: bool = False):
    from apps.api.routers.scanner_configs import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    if with_audit:
        class _FakeImmudb:
            def __init__(self):
                self.events = []
            def write_event(self, payload):
                self.events.append(payload)
        app.state.immudb_client = _FakeImmudb()
    if with_kafka:
        class _FakeKafka:
            def __init__(self):
                self.published = []
            def publish(self, topic, payload):
                self.published.append((topic, payload))
        app.state.kafka_producer = _FakeKafka()
    return app


def _unauthed_app():
    from apps.api.routers.scanner_configs import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _client(role: str = "bank_it_admin", **kw) -> TestClient:
    return TestClient(_make_app(role=role, **kw), raise_server_exceptions=False)


_SAMPLE_PAYLOAD = {
    "branch_id": "br-srcb0000001",
    "branch_ifsc": "SRCB0000001",
    "scanner_oem": "PANINI",
    "scanner_model": "My Vision X",
    "output_format": "CSV_COMMA",
    "date_format": "%d%m%Y",
    "amount_format": "DECIMAL_DOT",
    "field_mapping": {"MicrLine": "micr_line", "Amount": "amount_figures"},
    "image_naming_pattern": "{batch_id}_{seq}_{side}.tif",
    "image_side_mapping": {"F": "color_front", "G": "grey_front", "R": "rear"},
    "drop_folder_path": "/mnt/scanner/SRCB0000001",
}


def _seed(bank_id: str = "test-bank", branch_ifsc: str = "SRCB0000001") -> str:
    from apps.api.routers.scanner_configs import _CONFIG_STORE
    config_id = str(uuid.uuid4())
    _CONFIG_STORE[config_id] = {
        "scanner_config_id": config_id,
        "bank_id": bank_id,
        "branch_id": f"br-{branch_ifsc.lower()}",
        "branch_ifsc": branch_ifsc,
        "scanner_oem": "PANINI",
        "scanner_model": "My Vision X",
        "output_format": "CSV_COMMA",
        "date_format": "%d%m%Y",
        "amount_format": "DECIMAL_DOT",
        "field_mapping": {"MicrLine": "micr_line"},
        "image_naming_pattern": "{batch_id}_{seq}_{side}.tif",
        "image_side_mapping": {"F": "color_front", "G": "grey_front", "R": "rear"},
        "drop_folder_path": "/mnt/scanner/SRCB0000001",
        "is_active": True,
        "created_at": "2026-08-11T00:00:00+00:00",
        "updated_at": None,
        "created_by": "user-001",
    }
    return config_id


# ── GET /v1/cts/scanner-configs ───────────────────────────────────────────────

class TestList:
    def test_empty_returns_zero(self):
        r = _client().get("/v1/cts/scanner-configs")
        assert r.status_code == 200
        assert r.json()["total"] == 0
        assert r.json()["configs"] == []

    def test_returns_only_own_bank(self):
        _seed(bank_id="test-bank", branch_ifsc="SRCB0000001")
        _seed(bank_id="other-bank", branch_ifsc="KARB0000001")
        r = _client().get("/v1/cts/scanner-configs")
        assert r.status_code == 200
        assert r.json()["total"] == 1
        assert r.json()["configs"][0]["branch_ifsc"] == "SRCB0000001"

    def test_ops_manager_can_list(self):
        r = _client("ops_manager").get("/v1/cts/scanner-configs")
        assert r.status_code == 200

    def test_ops_reviewer_cannot_list(self):
        r = _client("ops_reviewer").get("/v1/cts/scanner-configs")
        assert r.status_code == 403

    def test_unauthenticated_returns_401(self):
        r = TestClient(_unauthed_app(), raise_server_exceptions=False).get(
            "/v1/cts/scanner-configs"
        )
        assert r.status_code == 401


# ── POST /v1/cts/scanner-configs ──────────────────────────────────────────────

class TestCreate:
    def test_creates_successfully(self):
        r = _client().post("/v1/cts/scanner-configs", json=_SAMPLE_PAYLOAD)
        assert r.status_code == 201
        body = r.json()
        assert "scanner_config_id" in body
        assert body["drop_folder_path"] == "/mnt/scanner/SRCB0000001"
        assert body["is_active"] is True

    def test_ops_manager_can_create(self):
        r = _client("ops_manager").post("/v1/cts/scanner-configs", json=_SAMPLE_PAYLOAD)
        assert r.status_code == 201

    def test_ops_reviewer_cannot_create(self):
        r = _client("ops_reviewer").post("/v1/cts/scanner-configs", json=_SAMPLE_PAYLOAD)
        assert r.status_code == 403

    def test_unauthenticated_returns_401(self):
        r = TestClient(_unauthed_app(), raise_server_exceptions=False).post(
            "/v1/cts/scanner-configs", json=_SAMPLE_PAYLOAD
        )
        assert r.status_code == 401

    def test_duplicate_active_branch_returns_409(self):
        _seed(branch_ifsc="SRCB0000001")
        r = _client().post("/v1/cts/scanner-configs", json=_SAMPLE_PAYLOAD)
        assert r.status_code == 409

    def test_audit_event_emitted_on_create(self):
        app = _make_app(with_audit=True)
        r = TestClient(app, raise_server_exceptions=False).post(
            "/v1/cts/scanner-configs", json=_SAMPLE_PAYLOAD
        )
        assert r.status_code == 201
        events = app.state.immudb_client.events
        assert len(events) == 1
        assert "SCANNER_CONFIG_CREATED" in events[0]

    def test_kafka_event_emitted_on_create(self):
        app = _make_app(with_kafka=True)
        r = TestClient(app, raise_server_exceptions=False).post(
            "/v1/cts/scanner-configs", json=_SAMPLE_PAYLOAD
        )
        assert r.status_code == 201
        published = app.state.kafka_producer.published
        assert len(published) == 1
        topic, payload = published[0]
        assert "config.changed" in topic


# ── GET /v1/cts/scanner-configs/{config_id} ──────────────────────────────────

class TestGet:
    def test_known_id_returns_200(self):
        config_id = _seed()
        r = _client().get(f"/v1/cts/scanner-configs/{config_id}")
        assert r.status_code == 200
        assert r.json()["scanner_config_id"] == config_id

    def test_unknown_id_returns_404(self):
        r = _client().get("/v1/cts/scanner-configs/nonexistent")
        assert r.status_code == 404

    def test_cross_bank_invisible(self):
        config_id = _seed(bank_id="other-bank")
        r = _client().get(f"/v1/cts/scanner-configs/{config_id}")
        assert r.status_code == 404

    def test_ops_reviewer_cannot_get(self):
        config_id = _seed()
        r = _client("ops_reviewer").get(f"/v1/cts/scanner-configs/{config_id}")
        assert r.status_code == 403


# ── PUT /v1/cts/scanner-configs/{config_id} ──────────────────────────────────

class TestUpdate:
    def test_update_drop_folder_path(self):
        config_id = _seed()
        r = _client().put(
            f"/v1/cts/scanner-configs/{config_id}",
            json={"drop_folder_path": "/mnt/scanner-new/SRCB0000001"},
        )
        assert r.status_code == 200
        assert r.json()["drop_folder_path"] == "/mnt/scanner-new/SRCB0000001"

    def test_update_records_old_and_new_path_in_audit(self):
        config_id = _seed()
        app = _make_app(with_audit=True)
        TestClient(app, raise_server_exceptions=False).put(
            f"/v1/cts/scanner-configs/{config_id}",
            json={"drop_folder_path": "/mnt/new/path"},
        )
        events = app.state.immudb_client.events
        assert len(events) == 1
        assert "/mnt/scanner/SRCB0000001" in events[0]  # old path
        assert "/mnt/new/path" in events[0]             # new path

    def test_update_emits_kafka_event(self):
        config_id = _seed()
        app = _make_app(with_kafka=True)
        TestClient(app, raise_server_exceptions=False).put(
            f"/v1/cts/scanner-configs/{config_id}",
            json={"drop_folder_path": "/mnt/new/path"},
        )
        assert len(app.state.kafka_producer.published) == 1

    def test_ops_manager_can_update(self):
        config_id = _seed()
        r = _client("ops_manager").put(
            f"/v1/cts/scanner-configs/{config_id}",
            json={"scanner_model": "DC TS240"},
        )
        assert r.status_code == 200

    def test_ops_reviewer_cannot_update(self):
        config_id = _seed()
        r = _client("ops_reviewer").put(
            f"/v1/cts/scanner-configs/{config_id}",
            json={"drop_folder_path": "/mnt/x"},
        )
        assert r.status_code == 403

    def test_unknown_id_returns_404(self):
        r = _client().put(
            "/v1/cts/scanner-configs/nonexistent",
            json={"drop_folder_path": "/mnt/x"},
        )
        assert r.status_code == 404

    def test_cross_bank_returns_404(self):
        config_id = _seed(bank_id="other-bank")
        r = _client().put(
            f"/v1/cts/scanner-configs/{config_id}",
            json={"drop_folder_path": "/mnt/x"},
        )
        assert r.status_code == 404

    def test_audit_event_type_is_updated(self):
        config_id = _seed()
        app = _make_app(with_audit=True)
        TestClient(app, raise_server_exceptions=False).put(
            f"/v1/cts/scanner-configs/{config_id}",
            json={"scanner_model": "DC TS240"},
        )
        assert "SCANNER_CONFIG_UPDATED" in app.state.immudb_client.events[0]


# ── DELETE /v1/cts/scanner-configs/{config_id} ───────────────────────────────

class TestDelete:
    def test_delete_sets_inactive(self):
        config_id = _seed()
        r = _client().delete(f"/v1/cts/scanner-configs/{config_id}")
        assert r.status_code == 200
        assert r.json()["is_active"] is False

    def test_delete_emits_audit(self):
        config_id = _seed()
        app = _make_app(with_audit=True)
        TestClient(app, raise_server_exceptions=False).delete(
            f"/v1/cts/scanner-configs/{config_id}"
        )
        events = app.state.immudb_client.events
        assert len(events) == 1
        assert "SCANNER_CONFIG_DELETED" in events[0]

    def test_delete_emits_kafka(self):
        config_id = _seed()
        app = _make_app(with_kafka=True)
        TestClient(app, raise_server_exceptions=False).delete(
            f"/v1/cts/scanner-configs/{config_id}"
        )
        assert len(app.state.kafka_producer.published) == 1

    def test_ops_manager_can_delete(self):
        config_id = _seed()
        r = _client("ops_manager").delete(f"/v1/cts/scanner-configs/{config_id}")
        assert r.status_code == 200

    def test_ops_reviewer_cannot_delete(self):
        config_id = _seed()
        r = _client("ops_reviewer").delete(f"/v1/cts/scanner-configs/{config_id}")
        assert r.status_code == 403

    def test_unknown_id_returns_404(self):
        r = _client().delete("/v1/cts/scanner-configs/nonexistent")
        assert r.status_code == 404

    def test_cross_bank_returns_404(self):
        config_id = _seed(bank_id="other-bank")
        r = _client().delete(f"/v1/cts/scanner-configs/{config_id}")
        assert r.status_code == 404
