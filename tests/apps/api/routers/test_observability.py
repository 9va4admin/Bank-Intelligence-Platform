"""
Tests for apps/api/routers/observability.py

ASTRA Ops Dashboard API — replaces Grafana dashboards with contextual React pages.

  GET /v1/ops/dashboard      — IET risk, human review queue, Kafka lag, Temporal queue
  GET /v1/ops/model-health   — OCR/fraud/signature model drift indicators
  GET /v1/ops/alerts         — recent CRITICAL/ERROR from audit trail (last 24h)
  GET /v1/ops/system         — Redis, YugabyteDB, Vault connectivity

Rules enforced:
  - ops_manager and bank_it_admin roles only (others → 403)
  - Unauthenticated → 401
  - No PII in any response (no instrument_id, account_number, payee_name)
  - Degraded mode (None deps) → 200 with degraded=True, zero values
  - limit query param max 50 on /alerts
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(role: str = "ops_manager", db_pool=None, redis_cts=None):
    from apps.api.routers.observability import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    app.state.db_pool_cts = db_pool
    app.state.redis_cts = redis_cts
    app.state.temporal_client = None
    return app


def _unauthed_app():
    from apps.api.routers.observability import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


# ── /v1/ops/dashboard ─────────────────────────────────────────────────────────

class TestDashboardEndpoint:

    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/dashboard").status_code == 401

    def test_ops_reviewer_returns_403(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        assert client.get("/v1/ops/dashboard").status_code == 403

    def test_fraud_analyst_returns_403(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        assert client.get("/v1/ops/dashboard").status_code == 403

    def test_ops_manager_gets_200(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        assert client.get("/v1/ops/dashboard").status_code == 200

    def test_bank_it_admin_gets_200(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        assert client.get("/v1/ops/dashboard").status_code == 200

    def test_response_top_level_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/dashboard").json()
        for field in ("bank_id", "as_of", "iet_risk", "human_review", "degraded"):
            assert field in data, f"Missing field: {field}"

    def test_iet_risk_panel_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        iet = client.get("/v1/ops/dashboard").json()["iet_risk"]
        assert "near_breach_count" in iet
        assert "in_processing_count" in iet
        assert "degraded" in iet
        assert isinstance(iet["near_breach_count"], int)

    def test_human_review_panel_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        hr = client.get("/v1/ops/dashboard").json()["human_review"]
        assert "queue_depth" in hr
        assert "avg_wait_minutes" in hr
        assert "degraded" in hr

    def test_degraded_when_db_pool_none(self):
        client = TestClient(_make_app(db_pool=None), raise_server_exceptions=False)
        data = client.get("/v1/ops/dashboard").json()
        assert data["degraded"] is True
        assert data["iet_risk"]["degraded"] is True
        assert data["human_review"]["degraded"] is True

    def test_bank_id_scoped_to_jwt_claim(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/dashboard").json()
        assert data["bank_id"] == "test-bank"

    def test_no_pii_in_dashboard(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        text = client.get("/v1/ops/dashboard").text
        for pii in ("account_number", "instrument_id", "payee_name", "drawer_name"):
            assert pii not in text, f"PII field '{pii}' found in dashboard response"

    def test_counts_are_non_negative_integers(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/dashboard").json()
        assert data["iet_risk"]["near_breach_count"] >= 0
        assert data["human_review"]["queue_depth"] >= 0


# ── /v1/ops/model-health ──────────────────────────────────────────────────────

class TestModelHealthEndpoint:

    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/model-health").status_code == 401

    def test_ops_reviewer_returns_403(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        assert client.get("/v1/ops/model-health").status_code == 403

    def test_ops_manager_gets_200(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        assert client.get("/v1/ops/model-health").status_code == 200

    def test_ml_engineer_gets_200(self):
        client = TestClient(_make_app(role="ml_engineer"), raise_server_exceptions=False)
        assert client.get("/v1/ops/model-health").status_code == 200

    def test_response_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/model-health").json()
        for field in ("bank_id", "as_of", "models", "degraded"):
            assert field in data, f"Missing field: {field}"
        assert isinstance(data["models"], list)

    def test_model_entry_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/model-health").json()
        for m in data["models"]:
            assert "model_name" in m
            assert "current_value" in m
            assert "drift_pct" in m
            assert "alert_status" in m
            assert m["alert_status"] in ("SAFE", "WARN", "CRITICAL", "UNKNOWN")

    def test_degraded_when_db_none(self):
        client = TestClient(_make_app(db_pool=None), raise_server_exceptions=False)
        data = client.get("/v1/ops/model-health").json()
        assert data["degraded"] is True

    def test_no_pii_in_model_health(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        text = client.get("/v1/ops/model-health").text
        for pii in ("account_number", "instrument_id", "payee_name"):
            assert pii not in text


# ── /v1/ops/alerts ────────────────────────────────────────────────────────────

class TestAlertsEndpoint:

    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts").status_code == 401

    def test_ops_reviewer_returns_403(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts").status_code == 403

    def test_ops_manager_gets_200(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts").status_code == 200

    def test_bank_it_admin_gets_200(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts").status_code == 200

    def test_response_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/alerts").json()
        for field in ("bank_id", "as_of", "total", "alerts", "degraded"):
            assert field in data, f"Missing field: {field}"
        assert isinstance(data["alerts"], list)

    def test_alert_entry_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/alerts").json()
        for a in data["alerts"]:
            assert "event_type" in a
            assert "severity" in a
            assert "occurred_at" in a
            assert "acknowledged" in a

    def test_no_pii_in_alerts(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        text = client.get("/v1/ops/alerts").text
        for pii in ("account_number", "instrument_id", "payee_name"):
            assert pii not in text

    def test_degraded_when_db_none(self):
        client = TestClient(_make_app(db_pool=None), raise_server_exceptions=False)
        data = client.get("/v1/ops/alerts").json()
        assert data["degraded"] is True
        assert data["total"] == 0

    def test_limit_default_accepted(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts").status_code == 200

    def test_limit_10_accepted(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts?limit=10").status_code == 200

    def test_limit_50_accepted(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts?limit=50").status_code == 200

    def test_limit_above_50_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/alerts?limit=51").status_code == 422


# ── /v1/ops/system ────────────────────────────────────────────────────────────

class TestSystemHealthEndpoint:

    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        assert client.get("/v1/ops/system").status_code == 401

    def test_fraud_analyst_returns_403(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        assert client.get("/v1/ops/system").status_code == 403

    def test_ops_reviewer_returns_403(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        assert client.get("/v1/ops/system").status_code == 403

    def test_bank_it_admin_gets_200(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        assert client.get("/v1/ops/system").status_code == 200

    def test_ops_manager_gets_200(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        assert client.get("/v1/ops/system").status_code == 200

    def test_response_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        data = client.get("/v1/ops/system").json()
        for field in ("bank_id", "as_of", "redis_cts", "yugabyte"):
            assert field in data, f"Missing field: {field}"

    def test_redis_panel_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        redis = client.get("/v1/ops/system").json()["redis_cts"]
        assert "connected" in redis
        assert "degraded" in redis

    def test_yugabyte_panel_schema(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        yb = client.get("/v1/ops/system").json()["yugabyte"]
        assert "connected" in yb
        assert "degraded" in yb

    def test_redis_degraded_when_none(self):
        client = TestClient(_make_app(redis_cts=None), raise_server_exceptions=False)
        redis = client.get("/v1/ops/system").json()["redis_cts"]
        assert redis["degraded"] is True
        assert redis["connected"] is False

    def test_yugabyte_degraded_when_db_none(self):
        client = TestClient(_make_app(db_pool=None), raise_server_exceptions=False)
        yb = client.get("/v1/ops/system").json()["yugabyte"]
        assert yb["degraded"] is True
        assert yb["connected"] is False

    def test_no_pii_in_system_health(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        text = client.get("/v1/ops/system").text
        for pii in ("account_number", "instrument_id", "payee_name"):
            assert pii not in text
