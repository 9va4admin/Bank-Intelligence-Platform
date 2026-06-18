"""
Tests for apps/api/routers/audit.py

Audit API endpoints:
  GET  /v1/audit/events                  — list audit events (bank-scoped, paginated)
  GET  /v1/audit/events/{event_id}       — fetch single audit event
  GET  /v1/audit/immudb/verify/{event_id} — verify event exists in Immudb
  GET  /v1/audit/compliance/summary      — compliance summary for a date range

Rules enforced:
  - All routes require JWT auth (unauthenticated → 401)
  - compliance_officer and ops_manager roles only (others → 403)
  - No SELECT * — explicit column responses via Pydantic models
  - Pagination: limit max 100, cursor-based
  - No PII in responses — amounts as range buckets, accounts masked
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(role="compliance_officer"):
    from apps.api.routers.audit import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _unauthed_app():
    from apps.api.routers.audit import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


class TestAuditEventsListRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        assert response.status_code == 401

    def test_wrong_role_returns_403(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        assert response.status_code == 403

    def test_compliance_officer_gets_200(self):
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        assert response.status_code == 200

    def test_ops_manager_gets_200(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        assert response.status_code == 200

    def test_response_has_events_list(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        data = response.json()
        assert "events" in data

    def test_response_has_pagination_cursor(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        data = response.json()
        assert "next_cursor" in data

    def test_limit_above_100_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events?limit=101")
        assert response.status_code == 422

    def test_default_limit_is_50(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        data = response.json()
        assert data["limit"] == 50

    def test_response_never_contains_raw_account_number(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events")
        assert "account_number" not in response.text


class TestAuditEventDetailRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events/evt-001")
        assert response.status_code == 401

    def test_authenticated_returns_200_or_404(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events/evt-001")
        assert response.status_code in (200, 404)

    def test_response_has_event_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events/evt-001")
        if response.status_code == 200:
            assert "event_id" in response.json()

    def test_response_has_event_type(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events/evt-001")
        if response.status_code == 200:
            assert "event_type" in response.json()

    def test_response_has_occurred_at(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/events/evt-001")
        if response.status_code == 200:
            assert "occurred_at" in response.json()


class TestImmudbVerifyRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/immudb/verify/evt-001")
        assert response.status_code == 401

    def test_authenticated_returns_200_or_404(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/immudb/verify/evt-001")
        assert response.status_code in (200, 404)

    def test_response_has_verified_field(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/immudb/verify/evt-001")
        if response.status_code == 200:
            data = response.json()
            assert "verified" in data
            assert isinstance(data["verified"], bool)

    def test_response_has_immudb_tx_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/immudb/verify/evt-001")
        if response.status_code == 200:
            assert "immudb_tx_id" in response.json()


class TestComplianceSummaryRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/compliance/summary?date_from=2026-06-01&date_to=2026-06-18")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_access(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/audit/compliance/summary?date_from=2026-06-01&date_to=2026-06-18")
        assert response.status_code == 403

    def test_compliance_officer_gets_200(self):
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.get("/v1/audit/compliance/summary?date_from=2026-06-01&date_to=2026-06-18")
        assert response.status_code == 200

    def test_missing_date_range_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/compliance/summary")
        assert response.status_code == 422

    def test_response_has_total_events(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/compliance/summary?date_from=2026-06-01&date_to=2026-06-18")
        assert "total_events" in response.json()

    def test_response_has_critical_count(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/compliance/summary?date_from=2026-06-01&date_to=2026-06-18")
        assert "critical_count" in response.json()

    def test_response_has_immudb_verification_status(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/audit/compliance/summary?date_from=2026-06-01&date_to=2026-06-18")
        assert "immudb_verified" in response.json()
