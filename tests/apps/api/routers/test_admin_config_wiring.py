"""
Tests for admin.py config change wiring:
  - Immudb audit_stream_writer called on submit, approve, reject
  - Kafka platform.config.changed published on approve only
  - Notification sent to bank_it_admin on submit
  - Notification sent to ops_manager on approve and reject
  - Layer 2 change request endpoint exists and writes DB + audit + notification
  - list_thresholds returns real schema keys (not empty list)

These tests should FAIL before the wiring is added.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── App factory ───────────────────────────────────────────────────────────────

def _make_wired_app(role="ops_manager"):
    from apps.api.routers.admin import (
        router_v1, get_current_user,
        get_event_publisher, get_audit_stream_writer,
    )
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _make_wired_app_with_captures(role="ops_manager"):
    """Returns (app, kafka_events, audit_events, notification_events)."""
    from apps.api.routers.admin import (
        router_v1, get_current_user,
        get_event_publisher, get_audit_stream_writer,
        get_notification_publisher,
    )
    kafka_events = []
    audit_events = []
    notification_events = []

    async def _capture_kafka(topic: str, payload: dict):
        kafka_events.append({"topic": topic, "payload": payload})

    async def _capture_audit(**kwargs):
        audit_events.append(kwargs)

    async def _capture_notification(topic: str, payload: dict):
        notification_events.append({"topic": topic, "payload": payload})

    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    app.dependency_overrides[get_event_publisher] = lambda: _capture_kafka
    app.dependency_overrides[get_audit_stream_writer] = lambda: _capture_audit
    app.dependency_overrides[get_notification_publisher] = lambda: _capture_notification

    return app, kafka_events, audit_events, notification_events


# ── list_thresholds returns real schema keys ──────────────────────────────────

class TestListThresholdsReturnsSchema:
    def test_returns_known_cts_config_keys(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        assert response.status_code == 200
        data = response.json()
        keys = [t["config_key"] for t in data.get("thresholds", [])]
        assert "iet_minutes" in keys

    def test_returns_stp_mode_key(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        data = response.json()
        keys = [t["config_key"] for t in data.get("thresholds", [])]
        assert "stp_mode" in keys

    def test_returns_allocation_mode_key(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        data = response.json()
        keys = [t["config_key"] for t in data.get("thresholds", [])]
        assert "allocation_mode" in keys

    def test_returns_queue_tier_keys(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        data = response.json()
        keys = [t["config_key"] for t in data.get("thresholds", [])]
        assert "queue_tier_high_value_threshold" in keys
        assert "queue_tier_very_high_threshold" in keys

    def test_total_matches_thresholds_length(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/admin/config/thresholds")
        data = response.json()
        assert data["total"] == len(data["thresholds"])
        assert data["total"] > 0


# ── submit writes Immudb + sends notification ─────────────────────────────────

class TestSubmitThresholdWritesAudit:
    def test_audit_stream_written_on_submit(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="ops_manager")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/admin/config/thresholds", json={
            "config_key": "stp_mode",
            "new_value": "SELECTIVE",
            "reason": "Piloting selective STP for low-risk instruments",
        })
        assert response.status_code in (200, 202)
        assert len(audits) >= 1
        assert any(a.get("event_type") == "CONFIG_CHANGE" for a in audits)

    def test_audit_payload_contains_config_key(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="ops_manager")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds", json={
            "config_key": "allocation_mode",
            "new_value": "AUTO",
            "reason": "Shifting to auto-allocation for high-volume periods",
        })
        assert any("allocation_mode" in str(a) for a in audits)

    def test_notification_sent_to_checker_on_submit(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="ops_manager")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds", json={
            "config_key": "stp_mode",
            "new_value": "SELECTIVE",
            "reason": "Piloting selective STP for low-risk instruments",
        })
        assert len(notifs) >= 1

    def test_no_kafka_config_changed_on_submit(self):
        """platform.config.changed must NOT fire on submit — only on approve."""
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="ops_manager")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds", json={
            "config_key": "stp_mode",
            "new_value": "SELECTIVE",
            "reason": "Piloting selective STP for low-risk instruments",
        })
        config_changed = [e for e in kafka if e["topic"] == "platform.config.changed"]
        assert len(config_changed) == 0


# ── approve publishes Kafka platform.config.changed + Immudb + notification ──

class TestApproveThresholdPublishesKafka:
    def test_kafka_config_changed_published_on_approve(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        # 404 is expected (no DB in test) — but Kafka must still fire
        client.post("/v1/admin/config/thresholds/chg-test-001/approve")
        config_changed = [e for e in kafka if e["topic"] == "platform.config.changed"]
        assert len(config_changed) >= 1

    def test_kafka_payload_contains_bank_id(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds/chg-test-001/approve")
        config_changed = [e for e in kafka if e["topic"] == "platform.config.changed"]
        assert len(config_changed) >= 1
        assert config_changed[0]["payload"].get("bank_id") == "test-bank"

    def test_audit_written_on_approve(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds/chg-test-001/approve")
        assert len(audits) >= 1

    def test_notification_sent_on_approve(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds/chg-test-001/approve")
        assert len(notifs) >= 1


# ── reject writes Immudb + notification ──────────────────────────────────────

class TestRejectThresholdWritesAudit:
    def test_audit_written_on_reject(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds/chg-test-001/reject")
        assert len(audits) >= 1

    def test_notification_sent_on_reject(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds/chg-test-001/reject")
        assert len(notifs) >= 1

    def test_no_kafka_config_changed_on_reject(self):
        """Config hot-reload must NOT fire on reject."""
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/thresholds/chg-test-001/reject")
        config_changed = [e for e in kafka if e["topic"] == "platform.config.changed"]
        assert len(config_changed) == 0


# ── Layer 2 change request endpoint ──────────────────────────────────────────

class TestLayer2ChangeRequestEndpoint:
    def test_endpoint_exists(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/admin/config/platform/change-request", json={
            "config_key": "cts.workers.max_replicas",
            "current_value": "200",
            "requested_value": "500",
            "reason": "Peak batch volume requires 500 parallel workers",
            "cab_ticket": "CAB-2026-0921",
        })
        assert response.status_code != 404

    def test_ops_manager_cannot_raise_layer2(self):
        """Layer 2 is bank_it_admin territory — ops_manager cannot raise it."""
        app = _make_wired_app(role="ops_manager")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/admin/config/platform/change-request", json={
            "config_key": "cts.workers.max_replicas",
            "current_value": "200",
            "requested_value": "500",
            "reason": "Peak batch volume requires 500 parallel workers",
            "cab_ticket": "CAB-2026-0921",
        })
        assert response.status_code == 403

    def test_bank_it_admin_gets_202(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/admin/config/platform/change-request", json={
            "config_key": "cts.workers.max_replicas",
            "current_value": "200",
            "requested_value": "500",
            "reason": "Peak batch volume requires 500 parallel workers",
            "cab_ticket": "CAB-2026-0921",
        })
        assert response.status_code in (200, 202)

    def test_missing_reason_returns_422(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/admin/config/platform/change-request", json={
            "config_key": "cts.workers.max_replicas",
            "current_value": "200",
            "requested_value": "500",
        })
        assert response.status_code == 422

    def test_response_has_request_id(self):
        app = _make_wired_app(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/v1/admin/config/platform/change-request", json={
            "config_key": "cts.workers.max_replicas",
            "current_value": "200",
            "requested_value": "500",
            "reason": "Peak batch volume requires 500 parallel workers",
            "cab_ticket": "CAB-2026-0921",
        })
        if response.status_code in (200, 202):
            assert "request_id" in response.json()

    def test_audit_written_on_layer2_request(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/platform/change-request", json={
            "config_key": "cts.workers.max_replicas",
            "current_value": "200",
            "requested_value": "500",
            "reason": "Peak batch volume requires 500 parallel workers",
            "cab_ticket": "CAB-2026-0921",
        })
        assert len(audits) >= 1

    def test_notification_sent_on_layer2_request(self):
        app, kafka, audits, notifs = _make_wired_app_with_captures(role="bank_it_admin")
        client = TestClient(app, raise_server_exceptions=False)
        client.post("/v1/admin/config/platform/change-request", json={
            "config_key": "cts.workers.max_replicas",
            "current_value": "200",
            "requested_value": "500",
            "reason": "Peak batch volume requires 500 parallel workers",
            "cab_ticket": "CAB-2026-0921",
        })
        assert len(notifs) >= 1
