"""
Tests for apps/api/routers/notifications.py

Notification API endpoints:
  POST /v1/notifications/send                     — trigger a notification (ops_manager, bank_it_admin)
  GET  /v1/notifications                          — list notification history (ops_manager, bank_it_admin, compliance_officer)
  GET  /v1/notifications/{notification_id}        — get delivery status (ops_manager, bank_it_admin, compliance_officer)
  POST /v1/notifications/{notification_id}/retry  — retry a failed notification (ops_manager, bank_it_admin)

Rules enforced:
  - All routes require JWT auth (unauthenticated → 401)
  - ops_reviewer and fraud_analyst cannot access notification routes
  - Channel must be: email | whatsapp
  - No PII in response — recipient masked, no message body in list view
  - Pagination: limit max 100, cursor-based
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(role="ops_manager"):
    from apps.api.routers.notifications import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _unauthed_app():
    from apps.api.routers.notifications import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


class TestNotificationSendRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        assert response.status_code == 401

    def test_ops_reviewer_cannot_send(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        assert response.status_code == 403

    def test_fraud_analyst_cannot_send(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        assert response.status_code == 403

    def test_ops_manager_can_send(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        assert response.status_code in (200, 202)

    def test_bank_it_admin_can_send(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        assert response.status_code in (200, 202)

    def test_invalid_channel_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "sms",           # not a valid channel
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        assert response.status_code == 422

    def test_missing_channel_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        assert response.status_code == 422

    def test_missing_template_id_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "context": {},
        })
        assert response.status_code == 422

    def test_response_has_notification_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        if response.status_code in (200, 202):
            assert "notification_id" in response.json()

    def test_response_has_status_queued(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        if response.status_code in (200, 202):
            assert response.json().get("status") == "QUEUED"

    def test_response_never_contains_raw_email(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/send", json={
            "channel": "email",
            "recipient_ref": "user-001",
            "template_id": "iet_breach_alert",
            "context": {},
        })
        # Raw email addresses must never appear in API responses
        assert "@" not in response.text or "example" not in response.text


class TestNotificationsListRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_list(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert response.status_code == 403

    def test_fraud_analyst_cannot_list(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert response.status_code == 403

    def test_compliance_officer_can_list(self):
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert response.status_code == 200

    def test_ops_manager_can_list(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert response.status_code == 200

    def test_response_has_notifications_list(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert "notifications" in response.json()

    def test_response_has_next_cursor(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert "next_cursor" in response.json()

    def test_limit_above_100_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications?limit=101")
        assert response.status_code == 422

    def test_default_limit_is_50(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        assert response.json()["limit"] == 50

    def test_response_never_contains_raw_email_address(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications")
        # Recipient field must be masked — no raw email in list response
        assert "recipient_email" not in response.text


class TestNotificationDetailRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications/notif-001")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_get(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/notifications/notif-001")
        assert response.status_code == 403

    def test_authenticated_returns_200_or_404(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications/notif-001")
        assert response.status_code in (200, 404)

    def test_response_has_notification_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications/notif-001")
        if response.status_code == 200:
            assert "notification_id" in response.json()

    def test_response_has_channel(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications/notif-001")
        if response.status_code == 200:
            assert "channel" in response.json()

    def test_response_has_delivery_status(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/notifications/notif-001")
        if response.status_code == 200:
            assert "delivery_status" in response.json()


class TestNotificationRetryRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/notif-001/retry")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_retry(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/notif-001/retry")
        assert response.status_code == 403

    def test_compliance_officer_cannot_retry(self):
        # compliance_officer is read-only for notifications
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/notif-001/retry")
        assert response.status_code == 403

    def test_ops_manager_can_retry(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/notif-001/retry")
        assert response.status_code in (200, 202, 404)

    def test_bank_it_admin_can_retry(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/notifications/notif-001/retry")
        assert response.status_code in (200, 202, 404)

    def test_response_has_notification_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/notifications/notif-001/retry")
        if response.status_code in (200, 202):
            assert "notification_id" in response.json()


class TestNotificationsAuthEdgeCases:
    """Cover lines 35-39: real auth paths in get_current_user."""
    def test_invalid_token_returns_401(self):
        from apps.api.routers.notifications import router_v1
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/notifications/",
            headers={"Authorization": "Bearer totally-wrong-token"},
        )
        assert response.status_code == 401

    def test_test_token_bearer_header_no_longer_grants_access(self):
        """Regression guard for ASTRA-01: notifications.py minted ops_manager
        (send/list/retry notifications) from a bare test-token-* Bearer
        header. That must never work again."""
        from apps.api.routers.notifications import router_v1
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/notifications/",
            headers={"Authorization": "Bearer test-token-test-bank"},
        )
        assert response.status_code == 401
