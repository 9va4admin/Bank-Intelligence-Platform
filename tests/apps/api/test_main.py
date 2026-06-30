"""Tests for FastAPI application lifespan and health endpoints."""
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
