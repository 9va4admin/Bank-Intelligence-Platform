"""
Tests for apps/ej_ingestion/main.py

EJ Ingestion Gateway — receives raw EJ files from branch-ej-agent MCP,
validates, hashes, and publishes to Kafka ej.raw.ingested.{bank_id}.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from apps.ej_ingestion.main import app
    return TestClient(app)


class TestHealthEndpoints:
    def test_liveness(self, client):
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_readiness(self, client):
        resp = client.get("/health/ready")
        assert resp.status_code in (200, 503)
        assert "status" in resp.json()


class TestIngestEndpoint:
    def test_unauthenticated_returns_401(self, client):
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            json={"raw_log": "SOME LOG", "atm_id": "ATM001", "source": "mcp", "oem_fingerprint": "NCR"},
        )
        assert resp.status_code == 401

    def test_accepted_returns_202(self, client):
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-token-test-bank"},
            json={
                "raw_log": "20261001 10:30:00 DISP 5000\n",
                "atm_id": "ATM001",
                "source": "mcp",
                "oem_fingerprint": "NCR_S2",
            },
        )
        assert resp.status_code == 202

    def test_response_contains_workflow_id(self, client):
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-token-test-bank"},
            json={
                "raw_log": "LOG LINE",
                "atm_id": "ATM001",
                "source": "mcp",
                "oem_fingerprint": "NCR_S2",
            },
        )
        data = resp.json()
        assert "workflow_id" in data
        assert data["workflow_id"].startswith("ej-normalise-")

    def test_response_contains_raw_log_hash(self, client):
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-token-test-bank"},
            json={
                "raw_log": "LOG LINE",
                "atm_id": "ATM001",
                "source": "mcp",
                "oem_fingerprint": "NCR_S2",
            },
        )
        data = resp.json()
        assert "raw_log_hash" in data
        assert len(data["raw_log_hash"]) == 64  # SHA-256 hex

    def test_response_status_is_accepted(self, client):
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-token-test-bank"},
            json={
                "raw_log": "LOG LINE",
                "atm_id": "ATM001",
                "source": "mcp",
                "oem_fingerprint": "NCR_S2",
            },
        )
        assert resp.json()["status"] == "ACCEPTED"

    def test_missing_atm_id_returns_422(self, client):
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-token-test-bank"},
            json={"raw_log": "LOG LINE", "source": "mcp", "oem_fingerprint": "NCR_S2"},
        )
        assert resp.status_code == 422

    def test_missing_raw_log_returns_422(self, client):
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-token-test-bank"},
            json={"atm_id": "ATM001", "source": "mcp", "oem_fingerprint": "NCR_S2"},
        )
        assert resp.status_code == 422

    def test_same_log_twice_idempotent(self, client):
        payload = {
            "raw_log": "IDEMPOTENT LOG LINE",
            "atm_id": "ATM001",
            "source": "mcp",
            "oem_fingerprint": "NCR_S2",
        }
        headers = {"Authorization": "Bearer test-token-test-bank"}
        r1 = client.post("/v1/ej-ingest/raw-log", headers=headers, json=payload)
        r2 = client.post("/v1/ej-ingest/raw-log", headers=headers, json=payload)
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["workflow_id"] == r2.json()["workflow_id"]
        assert r1.json()["raw_log_hash"] == r2.json()["raw_log_hash"]


class TestKafkaPublish:
    def test_kafka_event_published_on_ingest(self, client):
        """Verify a Kafka event is published — inspected via app.state.published_events."""
        resp = client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-bank-kafka"},
            json={
                "raw_log": "KAFKA TEST LOG",
                "atm_id": "ATM099",
                "source": "mcp",
                "oem_fingerprint": "Wincor_ProCash",
            },
        )
        assert resp.status_code == 202
        # In test mode, published_events is populated by the mock producer
        published = client.app.state.published_events
        assert len(published) >= 1
        last = published[-1]
        assert last["topic"].startswith("ej.raw.ingested.")
        assert last["payload"]["atm_id"] == "ATM099"

    def test_kafka_event_contains_raw_log_hash(self, client):
        client.post(
            "/v1/ej-ingest/raw-log",
            headers={"Authorization": "Bearer test-bank-kafka"},
            json={
                "raw_log": "HASH CHECK LOG",
                "atm_id": "ATM001",
                "source": "mcp",
                "oem_fingerprint": "NCR_S2",
            },
        )
        published = client.app.state.published_events
        last = published[-1]
        assert "raw_log_hash" in last["payload"]
        assert len(last["payload"]["raw_log_hash"]) == 64
