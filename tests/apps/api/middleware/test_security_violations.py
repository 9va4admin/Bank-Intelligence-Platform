"""
Tests for SecurityViolationMiddleware.

Covers:
  - TenantIsolationError / BankIsolationError → 403 + account suspended
  - AccessDeniedError → 403 (no suspension)
  - _publish_violation_alert: Kafka publish + DB persist (graceful degradation)
  - Suspended user short-circuit before route handler
  - ViolationStore and SuspensionStore helpers
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from apps.api.middleware.security_violations import (
    SecurityViolationMiddleware,
    SuspensionStore,
    ViolationStore,
    suspension_store,
    violation_store,
)
from shared.auth.exceptions import (
    AccessDeniedError,
    BankIsolationError,
    TenantIsolationError,
)
from shared.auth.rbac import BankType, Role, UserContext


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_user_ctx(
    *,
    user_id: str = "user-001",
    bank_id: str = "test-bank",
    role: Role = Role.OPS_MANAGER,
    bank_type: BankType = BankType.SB,
) -> UserContext:
    return UserContext(
        user_id=user_id,
        bank_id=bank_id,
        role=role,
        bank_type=bank_type,
        clearing_zones=["MUMBAI"],
    )


def _make_app(exc_to_raise=None):
    """Build a minimal FastAPI app with the middleware installed."""
    app = FastAPI()
    app.add_middleware(SecurityViolationMiddleware)

    @app.get("/test")
    async def route(request: Request):
        if exc_to_raise is not None:
            raise exc_to_raise
        return PlainTextResponse("ok")

    return app


# ── ViolationStore ────────────────────────────────────────────────────────────

class TestViolationStore:
    def test_record_and_get_all(self):
        store = ViolationStore(maxlen=10)
        store.record({"id": "v1", "sb_bank_id": "bank-a"})
        store.record({"id": "v2", "sb_bank_id": "bank-b"})
        assert len(store.get_all()) == 2

    def test_maxlen_respected(self):
        store = ViolationStore(maxlen=2)
        for i in range(5):
            store.record({"id": str(i), "sb_bank_id": "b"})
        assert len(store.get_all()) == 2

    def test_get_for_bank_filters(self):
        store = ViolationStore()
        store.record({"id": "1", "sb_bank_id": "alpha"})
        store.record({"id": "2", "sb_bank_id": "beta"})
        store.record({"id": "3", "sb_bank_id": "alpha"})
        assert len(store.get_for_bank("alpha")) == 2
        assert len(store.get_for_bank("beta")) == 1


# ── SuspensionStore ───────────────────────────────────────────────────────────

class TestSuspensionStore:
    def test_suspend_and_is_suspended(self):
        store = SuspensionStore()
        store.suspend("u-1")
        assert store.is_suspended("u-1") is True

    def test_reinstate(self):
        store = SuspensionStore()
        store.suspend("u-2")
        store.reinstate("u-2")
        assert store.is_suspended("u-2") is False

    def test_reinstate_nonexistent_does_not_raise(self):
        store = SuspensionStore()
        store.reinstate("nonexistent")  # must not raise

    def test_all_suspended(self):
        store = SuspensionStore()
        store.suspend("a")
        store.suspend("b")
        assert set(store.all_suspended()) == {"a", "b"}


# ── Middleware response codes ─────────────────────────────────────────────────

class TestMiddlewareResponses:
    def test_tenant_isolation_returns_403(self):
        app = _make_app(TenantIsolationError("cross-tenant"))
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 403

    def test_bank_isolation_returns_403(self):
        app = _make_app(BankIsolationError("cross-bank"))
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 403

    def test_access_denied_returns_403(self):
        app = _make_app(AccessDeniedError("no permission"))
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 403

    def test_normal_request_passes_through(self):
        app = _make_app(None)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 200

    def test_tenant_isolation_error_code_is_security_violation(self):
        app = _make_app(TenantIsolationError("x"))
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get("/test").json()
        assert body["error_code"] == "SECURITY_VIOLATION"

    def test_access_denied_error_code_is_access_denied(self):
        app = _make_app(AccessDeniedError("x"))
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get("/test").json()
        assert body["error_code"] == "ACCESS_DENIED"

    def test_response_has_incident_id_on_suspension_events(self):
        app = _make_app(BankIsolationError("x"))
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get("/test").json()
        assert "incident_id" in body

    def test_response_has_request_id(self):
        app = _make_app(TenantIsolationError("x"))
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get("/test").json()
        assert "request_id" in body

    def test_other_exceptions_propagate(self):
        app = _make_app(ValueError("not a security error"))
        client = TestClient(app, raise_server_exceptions=False)
        # ValueError should propagate to FastAPI's default 500 handler
        resp = client.get("/test")
        assert resp.status_code == 500


# ── _publish_violation_alert: graceful degradation ───────────────────────────

@pytest.mark.asyncio
async def test_publish_alert_kafka_published():
    middleware = SecurityViolationMiddleware(MagicMock())
    producer = AsyncMock()
    producer.send_and_wait = AsyncMock()

    request = MagicMock(spec=Request)
    request.app.state.kafka_producer = producer
    request.app.state.db_pool_platform = None

    event = {
        "id": "ev-001",
        "bank_id": "b1",
        "sb_bank_id": "b1",
        "user_id": "u1",
        "role": "ops_manager",
        "bank_type": "SB",
        "violation_type": "TenantIsolationError",
        "suspended": True,
        "endpoint": "/v1/cts/something",
        "method": "GET",
        "client_ip": "10.0.0.1",
        "detail": "cross-tenant",
        "request_id": "req-abc",
    }
    await middleware._publish_violation_alert(request, event, is_suspension=True)
    producer.send_and_wait.assert_awaited_once()
    call_kwargs = producer.send_and_wait.await_args
    topic = call_kwargs.args[0]
    assert "notifications" in topic


@pytest.mark.asyncio
async def test_publish_alert_no_producer_does_not_raise():
    middleware = SecurityViolationMiddleware(MagicMock())
    request = MagicMock(spec=Request)
    request.app.state.kafka_producer = None
    request.app.state.db_pool_platform = None

    event = {
        "id": "ev-002", "bank_id": "b1", "sb_bank_id": "b1",
        "user_id": "u1", "role": "ops_manager", "bank_type": "SB",
        "violation_type": "BankIsolationError", "suspended": True,
        "endpoint": "/test", "method": "GET", "client_ip": "127.0.0.1",
        "detail": "x", "request_id": "r1",
    }
    # Must not raise even when no producer or DB pool
    await middleware._publish_violation_alert(request, event, is_suspension=True)


@pytest.mark.asyncio
async def test_publish_alert_kafka_failure_does_not_raise():
    middleware = SecurityViolationMiddleware(MagicMock())
    producer = AsyncMock()
    producer.send_and_wait = AsyncMock(side_effect=RuntimeError("kafka down"))

    request = MagicMock(spec=Request)
    request.app.state.kafka_producer = producer
    request.app.state.db_pool_platform = None

    event = {
        "id": "ev-003", "bank_id": "b1", "sb_bank_id": "b1",
        "user_id": "u1", "role": "ops_manager", "bank_type": "SB",
        "violation_type": "TenantIsolationError", "suspended": True,
        "endpoint": "/test", "method": "GET", "client_ip": "127.0.0.1",
        "detail": "x", "request_id": "r1",
    }
    # Kafka failure must not propagate — violation handling must never fail
    await middleware._publish_violation_alert(request, event, is_suspension=True)


@pytest.mark.asyncio
async def test_publish_alert_db_persist_called():
    middleware = SecurityViolationMiddleware(MagicMock())

    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    request = MagicMock(spec=Request)
    request.app.state.kafka_producer = None
    request.app.state.db_pool_platform = pool

    event = {
        "id": "ev-004", "bank_id": "b1", "sb_bank_id": "b1",
        "user_id": "u1", "role": "ops_manager", "bank_type": "SB",
        "violation_type": "BankIsolationError", "suspended": True,
        "endpoint": "/test", "method": "GET", "client_ip": "127.0.0.1",
        "detail": "x" * 600,   # over 512 chars — must be truncated
        "request_id": "r1",
    }
    await middleware._publish_violation_alert(request, event, is_suspension=True)
    conn.execute.assert_awaited_once()
    # Verify detail is truncated to 512 chars in the DB call
    call_args = conn.execute.await_args.args
    detail_arg = call_args[12]   # 13th positional arg (0-indexed: 12)
    assert len(detail_arg) == 512
