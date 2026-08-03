"""
Tests for apps/api/routers/cts_outward_queue.py

POST /v1/cts/outward/queue/decisions — records a Human Review / STP Rejected
decision from the Outward Q page and emits it to platform.audit.events (Immudb
audit trail via audit-service), the same fire-and-forget pattern already proven
in mcp_connections.py.

Coverage:
  - 201 + event_id on valid CONFIRMED (reason_category=confirm)
  - 201 + event_id on valid REJECTED (reason_category=reject)
  - 422 when action/reason_category are mismatched (server-side enforcement,
    not just a disabled frontend button)
  - Audit event actually published to platform.audit.events with correct payload
  - 401 when unauthenticated
  - Still 201 (never blocks the UI) when no Kafka publisher is configured
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(with_publisher=True):
    from apps.api.routers.cts_outward_queue import router_v1, get_event_publisher
    from apps.api.routers.cts import get_current_user_context
    from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext

    app = FastAPI()
    app.include_router(router_v1)

    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id="ops-1",
        role=Role.OPS_MANAGER,
        bank_id="saraswat-coop",
        bank_type=BankType.SB,
        permission_level=PermissionLevel.EDIT,
    )

    events_published: list = []
    if with_publisher:
        async def _mock_publisher(topic: str, payload: dict):
            events_published.append({"topic": topic, "payload": payload})
        app.dependency_overrides[get_event_publisher] = lambda: _mock_publisher

    return app, events_published


def _valid_body(**over):
    body = {
        "instrument_id": "CHQ-OUT-00512",
        "tab": "review",
        "action": "CONFIRMED",
        "reason": "Manual Verification Passed",
        "reason_category": "confirm",
    }
    body.update(over)
    return body


def test_confirmed_decision_returns_201_with_event_id():
    app, events = _make_app()
    client = TestClient(app)
    r = client.post("/v1/cts/outward/queue/decisions", json=_valid_body())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "RECORDED"
    assert body["event_id"]


def test_rejected_decision_valid_category_201():
    app, events = _make_app()
    client = TestClient(app)
    body = _valid_body(action="REJECTED", reason="Date invalid or stale cheque", reason_category="reject")
    r = client.post("/v1/cts/outward/queue/decisions", json=body)
    assert r.status_code == 201


def test_mismatched_action_and_category_rejected_with_confirm_category_422():
    app, events = _make_app()
    client = TestClient(app)
    body = _valid_body(action="REJECTED", reason_category="confirm")
    r = client.post("/v1/cts/outward/queue/decisions", json=body)
    assert r.status_code == 422


def test_mismatched_confirmed_with_reject_category_422():
    app, events = _make_app()
    client = TestClient(app)
    body = _valid_body(action="CONFIRMED", reason_category="reject")
    r = client.post("/v1/cts/outward/queue/decisions", json=body)
    assert r.status_code == 422


def test_empty_reason_rejected_422():
    app, events = _make_app()
    client = TestClient(app)
    body = _valid_body(reason="")
    r = client.post("/v1/cts/outward/queue/decisions", json=body)
    assert r.status_code == 422


def test_audit_event_published_to_platform_audit_events_topic():
    app, events = _make_app()
    client = TestClient(app)
    body = _valid_body(instrument_id="CHQ-OUT-00777", tab="stp_rejected",
                        action="CONFIRMED", reason="Manager Override Approved", reason_category="confirm")
    r = client.post("/v1/cts/outward/queue/decisions", json=body)
    assert r.status_code == 201
    assert len(events) == 1
    ev = events[0]
    assert ev["topic"] == "platform.audit.events"
    assert ev["payload"]["event_type"] == "CTS_OUTWARD_QUEUE_DECISION"
    assert ev["payload"]["bank_id"] == "saraswat-coop"
    assert ev["payload"]["instrument_id"] == "CHQ-OUT-00777"
    assert ev["payload"]["tab"] == "stp_rejected"
    assert ev["payload"]["action"] == "CONFIRMED"
    assert ev["payload"]["reason"] == "Manager Override Approved"
    assert ev["payload"]["reason_category"] == "confirm"
    assert ev["payload"]["decided_by"] == "ops-1"


def test_unauthenticated_returns_401():
    from apps.api.routers.cts_outward_queue import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    client = TestClient(app)
    r = client.post("/v1/cts/outward/queue/decisions", json=_valid_body())
    assert r.status_code == 401


def test_no_publisher_configured_still_returns_201():
    """Audit emission is fire-and-forget — a missing/broken publisher must never
    block the reviewer's decision from being recorded and the UI from proceeding."""
    app, events = _make_app(with_publisher=False)
    client = TestClient(app)
    r = client.post("/v1/cts/outward/queue/decisions", json=_valid_body())
    assert r.status_code == 201
