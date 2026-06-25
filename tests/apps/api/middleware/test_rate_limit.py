"""
Tests for Redis-backed rate limiting middleware.

TDD: tests written first, then implementation.
Coverage target: 80%+ (API routers tier)
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from apps.api.middleware.rate_limit import (
    RateLimitMiddleware,
    _resolve_slug,
    _window_key,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestResolveSlug:
    def test_cts_inward_submit_resolves(self):
        assert _resolve_slug("/v1/cts/inward/INS-001/submit") == "cts_inward_submit"

    def test_cts_decisions_resolves(self):
        assert _resolve_slug("/v1/cts/decisions/INS-001") == "cts_decisions_get"

    def test_cts_queue_resolves(self):
        assert _resolve_slug("/v1/cts/queue") == "cts_queue_get"

    def test_ej_inward_log_resolves(self):
        assert _resolve_slug("/v1/ej/inward/ATM-001/log") == "ej_inward_log"

    def test_ej_atm_health_resolves(self):
        assert _resolve_slug("/v1/ej/atm/ATM-001/health") == "ej_atm_health"

    def test_admin_config_resolves(self):
        assert _resolve_slug("/v1/admin/config/cts.iet_minutes") == "admin_config"

    def test_health_endpoint_returns_none(self):
        assert _resolve_slug("/health/live") is None

    def test_metrics_returns_none(self):
        assert _resolve_slug("/metrics") is None

    def test_unknown_path_returns_none(self):
        assert _resolve_slug("/v1/unknown/path") is None


class TestWindowKey:
    def test_key_includes_bank_id_and_slug(self):
        key = _window_key("hdfc-bank", "cts_inward_submit")
        assert "hdfc-bank" in key
        assert "cts_inward_submit" in key

    def test_key_includes_minute_window(self):
        minute = int(time.time()) // 60
        key = _window_key("hdfc-bank", "cts_inward_submit")
        assert str(minute) in key

    def test_same_minute_same_key(self):
        key1 = _window_key("hdfc-bank", "cts_inward_submit")
        key2 = _window_key("hdfc-bank", "cts_inward_submit")
        assert key1 == key2

    def test_different_bank_different_key(self):
        key1 = _window_key("hdfc-bank", "cts_inward_submit")
        key2 = _window_key("axis-bank", "cts_inward_submit")
        assert key1 != key2


# ---------------------------------------------------------------------------
# Integration tests for the middleware
# ---------------------------------------------------------------------------

def _make_app(redis_mock=None):
    """Create a minimal FastAPI app with rate limit middleware."""
    test_app = FastAPI()
    test_app.state.redis_cts = redis_mock

    @test_app.get("/v1/cts/decisions/test-id")
    async def test_route():
        return PlainTextResponse("ok")

    test_app.add_middleware(RateLimitMiddleware)
    return test_app


class TestRateLimitMiddleware:
    def test_skips_health_endpoint(self):
        """Health endpoints must never be rate-limited."""
        app = _make_app(redis_mock=None)

        @app.get("/health/live")
        async def health():
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/live")
        assert resp.status_code == 200

    def test_allows_request_under_limit(self):
        """Request with count=1 should pass through."""
        redis_mock = AsyncMock()
        # pipeline() is synchronous in aioredis; execute() is async
        pipe_mock = MagicMock()
        pipe_mock.incr = MagicMock()
        pipe_mock.expire = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True])
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        app = _make_app(redis_mock=redis_mock)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/cts/decisions/test-id", headers={"Authorization": "Bearer test-token-hdfc"})

        # Should not be rate limited
        assert resp.status_code != 429
        assert "X-RateLimit-Limit" in resp.headers

    def test_blocks_request_over_limit(self):
        """Request with count > limit should return 429."""
        redis_mock = AsyncMock()
        pipe_mock = MagicMock()
        pipe_mock.incr = MagicMock()
        pipe_mock.expire = MagicMock()
        # count=10000 >> 300 (cts_decisions_get limit)
        pipe_mock.execute = AsyncMock(return_value=[10000, True])
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        app = _make_app(redis_mock=redis_mock)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/cts/decisions/test-id", headers={"Authorization": "Bearer test-token-hdfc"})

        assert resp.status_code == 429
        body = resp.json()
        assert body["error_code"] == "RATE_LIMIT_EXCEEDED"
        assert "Retry-After" in resp.headers

    def test_fail_open_on_redis_unavailable(self):
        """When Redis is None, request passes through — rate limit is DoS protection, not safety gate."""
        app = _make_app(redis_mock=None)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/cts/decisions/test-id", headers={"Authorization": "Bearer test-token-hdfc"})
        # Should NOT be rate-limited (fail-open)
        assert resp.status_code != 429

    def test_fail_open_on_redis_error(self):
        """When Redis raises an exception, request passes through."""
        redis_mock = AsyncMock()
        pipe_mock = MagicMock()
        pipe_mock.execute = AsyncMock(side_effect=ConnectionError("Redis down"))
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        app = _make_app(redis_mock=redis_mock)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/cts/decisions/test-id", headers={"Authorization": "Bearer test-token-hdfc"})
        assert resp.status_code != 429

    def test_response_includes_rate_limit_headers(self):
        """Successful response must include X-RateLimit-* headers."""
        redis_mock = AsyncMock()
        pipe_mock = MagicMock()
        pipe_mock.incr = MagicMock()
        pipe_mock.expire = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[5, True])
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        app = _make_app(redis_mock=redis_mock)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/cts/decisions/test-id", headers={"Authorization": "Bearer test-token-hdfc"})

        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers

    def test_skips_unknown_path_no_redis_call(self):
        """Unknown paths should not be rate-limited (no Redis call)."""
        redis_mock = AsyncMock()
        app = _make_app(redis_mock=redis_mock)

        @app.get("/v1/unknown/path")
        async def unknown_route():
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/v1/unknown/path")
        assert resp.status_code != 429
        # Redis should not have been called for unknown paths
        redis_mock.pipeline.assert_not_called()
