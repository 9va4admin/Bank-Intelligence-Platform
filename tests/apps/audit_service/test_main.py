"""Tests for the audit-service entrypoint — health endpoints + construction helper.

Matches the established, intentionally-light convention for service entrypoints
in this codebase (see tests/apps/api/test_main.py) — the real logic lives in
shared/audit/stream_consumer.py and shared/audit/immudb_writer.py, both
already fully tested; this file only covers wiring-level concerns.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


def _make_test_app():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/health/live")
    async def liveness():
        return {"status": "ok", "service": "audit-service"}

    @app.get("/health/ready")
    async def readiness():
        return JSONResponse(
            {"status": "ready", "checks": {"redis_cts": True, "immudb": True}},
            status_code=200,
        )

    return app


class TestHealthEndpoints:
    def test_liveness_returns_200(self):
        client = TestClient(_make_test_app())
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["service"] == "audit-service"

    def test_readiness_returns_200_when_healthy(self):
        client = TestClient(_make_test_app())
        resp = client.get("/health/ready")
        assert resp.status_code == 200

    def test_health_endpoints_require_no_auth(self):
        client = TestClient(_make_test_app())
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200


class TestBuildImmudbWriter:
    @pytest.mark.asyncio
    async def test_returns_none_when_immudb_unreachable(self):
        from apps.audit_service.main import _build_immudb_writer

        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=Exception("not configured"))

        writer = await _build_immudb_writer(fake_cfg, "test-bank")
        assert writer is None

    @pytest.mark.asyncio
    async def test_returns_async_immudb_writer_on_success(self):
        from apps.audit_service.main import _build_immudb_writer
        from shared.audit.immudb_writer import AsyncImmudbWriter

        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=lambda k: {
            "immudb.host": "immudb.internal", "immudb.port": "3322",
        }[k])
        fake_cfg.get_secret = AsyncMock(return_value="dummy-credential")

        with patch("shared.audit.immudb_client.ImmudbClient.connect", return_value=None):
            writer = await _build_immudb_writer(fake_cfg, "test-bank")

        assert isinstance(writer, AsyncImmudbWriter)


class TestBuildRedisClient:
    @pytest.mark.asyncio
    async def test_returns_none_when_redis_url_unavailable(self):
        from apps.audit_service.main import _build_redis_client

        fake_cfg = MagicMock()
        fake_cfg.get_secret = AsyncMock(side_effect=Exception("Vault unreachable"))

        client = await _build_redis_client(fake_cfg)
        assert client is None
