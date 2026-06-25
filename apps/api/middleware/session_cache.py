"""
Redis-backed JWT session cache middleware for ASTRA.

On first request with a JWT token:
  1. Validate JWT signature (expensive — crypto verify)
  2. Extract bank_id, user_id, roles claims
  3. Cache validated claims in Redis: session:{bank_id}:{sha256(token)} → JSON, TTL 15min
  4. Set request.state.bank_id, request.state.user_id, request.state.roles

On subsequent requests with the same token:
  1. SHA-256 the token (fast, no crypto)
  2. GET session:{bank_id}:{token_hash} from Redis (< 1ms)
  3. If hit: skip JWT verify, read claims from cache
  4. If miss: full JWT verify, re-cache

On logout (DELETE /v1/auth/session):
  - DEL session:{bank_id}:{token_hash} from Redis (immediate invalidation)

Security: token is never stored raw — only SHA-256 hash used as key.
The cached value stores the validated claims, not the token itself.

Key: session:{bank_id}:{sha256(token)}
TTL: 900 seconds (15 minutes), refreshed on each request
"""
import hashlib
import json
import time
from typing import Optional

import structlog
from fastapi import Request
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

log = structlog.get_logger()
tracer = trace.get_tracer("astra.session_cache")

_SESSION_TTL_SECONDS = 900  # 15 minutes

SKIP_PATHS = {"/health/live", "/health/ready", "/metrics", "/docs", "/openapi.json"}


def _session_key(bank_id: str, token: str) -> str:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return f"session:{bank_id}:{token_hash}"


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _extract_bank_id_from_token(token: str) -> str:
    """
    Extract bank_id from token without full verification.
    Test tokens: 'test-token-{bank_id}'
    Production: parse JWT claims (base64 decode middle segment, no verify — we just need bank_id for cache key)
    """
    if token.startswith("test-token-"):
        return token.removeprefix("test-token-")
    # Production: decode JWT payload (middle segment) without verifying signature
    # We need bank_id to build the cache key — the signature verify happens below
    try:
        import base64
        parts = token.split(".")
        if len(parts) == 3:
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
            return claims.get("bank_id", "unknown")
    except Exception:
        pass
    return "unknown"


async def get_cached_session(redis, token: str) -> Optional[dict]:
    """
    Attempt to load validated session claims from Redis cache.
    Returns claims dict on hit, None on miss or Redis error.
    """
    if redis is None:
        return None
    bank_id = _extract_bank_id_from_token(token)
    key = _session_key(bank_id, token)
    try:
        raw = await redis.get(key)
        if raw:
            claims = json.loads(raw)
            # Refresh TTL on each active request (sliding expiry)
            await redis.expire(key, _SESSION_TTL_SECONDS)
            return claims
    except Exception as exc:
        log.warning("session_cache.read_failed", error=str(exc))
    return None


async def cache_session(redis, token: str, claims: dict) -> None:
    """
    Store validated claims in Redis session cache.
    Called by auth middleware after successful JWT verification.
    """
    if redis is None:
        return
    bank_id = claims.get("bank_id", "unknown")
    key = _session_key(bank_id, token)
    try:
        await redis.setex(key, _SESSION_TTL_SECONDS, json.dumps(claims))
    except Exception as exc:
        log.warning("session_cache.write_failed", error=str(exc))


async def invalidate_session(redis, token: str) -> None:
    """
    Immediately invalidate a session (logout).
    DEL session:{bank_id}:{token_hash} from Redis.
    """
    if redis is None:
        return
    bank_id = _extract_bank_id_from_token(token)
    key = _session_key(bank_id, token)
    try:
        await redis.delete(key)
        log.info("session_cache.invalidated", bank_id=bank_id)
    except Exception as exc:
        log.warning("session_cache.invalidate_failed", error=str(exc))
