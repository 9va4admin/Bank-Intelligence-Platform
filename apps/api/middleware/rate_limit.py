"""
Redis-backed sliding window rate limiter for ASTRA API gateway.

Limits enforced per-bank per-endpoint using atomic Redis INCR + EXPIRE.
On Redis unavailability: fail-open (request passes) with a warning log —
rate limit is a DoS protection layer, not a safety invariant.

Limits (from CLAUDE.md):
  CTS submission endpoints: 600 req/min per bank_id
  EJ ingestion:             100 req/min per branch
  Admin endpoints:           30 req/min per user

Key pattern: ratelimit:{bank_id}:{endpoint_slug}:{window_start_epoch_minute}
"""
import time
from typing import Optional

import structlog
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger()
tracer = trace.get_tracer("astra.rate_limit")

# endpoint_slug → (limit_per_minute, bank_scope)
# bank_scope: True = limit per bank_id, False = limit per user_id
_ENDPOINT_LIMITS: dict[str, tuple[int, bool]] = {
    # CTS
    "cts_inward_submit": (600, True),
    "cts_review_decide": (120, True),
    "cts_decisions_get": (300, True),
    "cts_queue_get": (60, True),
    # EJ
    "ej_inward_log": (100, True),
    "ej_canonical_get": (200, True),
    "ej_atm_health": (300, True),
    "ej_disputes_resolve": (60, True),
    # Admin
    "admin_config": (30, False),
    "admin_bank": (20, False),
    "audit_query": (30, False),
}

# Maps URL path prefixes to endpoint slugs
_PATH_TO_SLUG: dict[str, str] = {
    "/v1/cts/inward": "cts_inward_submit",
    "/v1/cts/review": "cts_review_decide",
    "/v1/cts/decisions": "cts_decisions_get",
    "/v1/cts/queue": "cts_queue_get",
    "/v1/ej/inward": "ej_inward_log",
    "/v1/ej/canonical": "ej_canonical_get",
    "/v1/ej/atm": "ej_atm_health",
    "/v1/ej/disputes": "ej_disputes_resolve",
    "/v1/admin/config": "admin_config",
    "/v1/admin/bank": "admin_bank",
    "/v1/audit": "audit_query",
}


def _resolve_slug(path: str) -> Optional[str]:
    for prefix, slug in _PATH_TO_SLUG.items():
        if path.startswith(prefix):
            return slug
    return None


def _window_key(bank_id: str, slug: str) -> str:
    """60-second fixed window key. Changes every minute."""
    minute = int(time.time()) // 60
    return f"ratelimit:{bank_id}:{slug}:{minute}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window (fixed 60s window) rate limiter using Redis atomic INCR.

    Installed in FastAPI lifespan. Reads redis_cts from app.state.
    Skips health and metrics endpoints.
    """

    SKIP_PATHS = {"/health/live", "/health/ready", "/metrics", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in self.SKIP_PATHS:
            return await call_next(request)

        slug = _resolve_slug(path)
        if slug is None:
            return await call_next(request)

        limit, by_bank = _ENDPOINT_LIMITS[slug]

        # Determine the scope identifier
        if by_bank:
            scope_id = getattr(request.state, "bank_id", None)
            if scope_id is None:
                # bank_id not yet set (auth middleware runs after) — use IP as fallback
                scope_id = request.client.host if request.client else "unknown"
        else:
            scope_id = getattr(request.state, "user_id", request.client.host if request.client else "unknown")

        redis = getattr(request.app.state, "redis_cts", None)

        if redis is None:
            # No Redis available — fail open, log warning
            log.warning("rate_limit.redis_unavailable", path=path, slug=slug)
            return await call_next(request)

        with tracer.start_as_current_span("rate_limit.check") as span:
            span.set_attribute("endpoint_slug", slug)
            span.set_attribute("limit", limit)

            try:
                key = _window_key(scope_id, slug)
                pipe = redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, 61)  # 1 extra second to avoid edge-case expiry
                results = await pipe.execute()
                current_count = results[0]

                span.set_attribute("current_count", current_count)
                span.set_attribute("rate_limited", current_count > limit)

                if current_count > limit:
                    log.warning(
                        "rate_limit.exceeded",
                        slug=slug,
                        scope_id=scope_id,
                        count=current_count,
                        limit=limit,
                    )
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={
                            "error_code": "RATE_LIMIT_EXCEEDED",
                            "message": f"Too many requests. Limit: {limit}/min for {slug}.",
                            "limit": limit,
                            "window": "60s",
                        },
                        headers={
                            "X-RateLimit-Limit": str(limit),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str((int(time.time()) // 60 + 1) * 60),
                            "Retry-After": "60",
                        },
                    )

                response = await call_next(request)
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current_count))
                response.headers["X-RateLimit-Reset"] = str((int(time.time()) // 60 + 1) * 60)
                return response

            except Exception as exc:
                log.warning("rate_limit.error", slug=slug, error=str(exc))
                return await call_next(request)
