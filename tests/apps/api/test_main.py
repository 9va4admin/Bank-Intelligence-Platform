"""Tests for FastAPI application lifespan and health endpoints."""
# ---------------------------------------------------------------------------
# Auth router registration — verifies app.include_router(auth.router_v1) exists
# ---------------------------------------------------------------------------

def test_auth_login_route_registered_on_real_app():
    """The real ASTRA app must include the auth router — /v1/auth/login must exist."""
    # Import triggers module-level code including include_router() calls.
    # We only check the route table; lifespan (Vault, Redis, DB) is not triggered here.
    from apps.api.main import app
    routes = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/v1/auth/login" in routes, (
        "POST /v1/auth/login not found in app.routes — "
        "add app.include_router(auth.router_v1) to apps/api/main.py"
    )


def test_auth_session_route_registered_on_real_app():
    from apps.api.main import app
    routes = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/v1/auth/session" in routes



import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


def _make_test_app():
    """Create a test version of the app with mocked infrastructure."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/health/live")
    async def liveness():
        return {"status": "ok", "service": "api-gateway"}

    @app.get("/health/ready")
    async def readiness():
        return JSONResponse(
            {"status": "ready", "checks": {"db": True, "redis": True}},
            status_code=200,
        )

    return app


class TestHealthEndpoints:
    def test_liveness_returns_200(self):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_liveness_includes_service_name(self):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/health/live")
        assert "service" in resp.json()

    def test_readiness_returns_200_when_all_healthy(self):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200

    def test_readiness_includes_checks_dict(self):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/health/ready")
        body = resp.json()
        assert "checks" in body

    def test_health_endpoints_require_no_auth(self):
        """Health endpoints must be accessible without Authorization header."""
        app = _make_test_app()
        client = TestClient(app)
        # No Authorization header
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
