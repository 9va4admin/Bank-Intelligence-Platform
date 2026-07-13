"""Central authentication middleware — the single session gate for the API.

Replaces the forgeable per-router `test-token` auth. It validates the httpOnly
session cookie once per request, sets request.state.user to the verified
SessionClaims (or None), and enforces CSRF (signed double-submit) on unsafe
methods. Routes read identity via apps.api.dependencies — never by parsing tokens.

Exempt from CSRF / auth gating:
  - Public: /health*, /docs, /openapi.json, /metrics, /redoc
  - Auth bootstrap: /v1/auth/login, /v1/auth/mfa/*, /v1/auth/logout
    (these run before a full session/CSRF exists; the auth router validates the
     interim cookie itself)
"""
import hmac

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.auth.exceptions import InvalidSessionError, SessionExpiredError

log = structlog.get_logger()

_COOKIE = "astra_session"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_PUBLIC_PREFIXES = ("/health", "/docs", "/openapi.json", "/metrics", "/redoc")
_CSRF_EXEMPT_PREFIXES = ("/v1/auth/login", "/v1/auth/mfa", "/v1/auth/logout")


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Resolve the session once — never raises (absent/invalid -> None).
        request.state.user = self._resolve(request)

        # CSRF on unsafe methods, once a session exists, outside bootstrap/public.
        if (
            request.method not in _SAFE_METHODS
            and not self._is_exempt(path)
            and request.state.user is not None
        ):
            presented = request.headers.get("X-CSRF-Token", "")
            expected = request.state.user.csrf_token
            if not presented or not hmac.compare_digest(str(expected), str(presented)):
                return JSONResponse(
                    status_code=403,
                    content={"error_code": "CSRF_INVALID", "message": "Missing or invalid CSRF token"},
                )

        return await call_next(request)

    def _resolve(self, request: Request):
        token = request.cookies.get(_COOKIE)
        if not token:
            return None
        session_service = getattr(request.app.state, "session_service", None)
        if session_service is None:
            return None
        try:
            return session_service.validate(token)
        except (SessionExpiredError, InvalidSessionError):
            return None

    @staticmethod
    def _is_exempt(path: str) -> bool:
        return path.startswith(_PUBLIC_PREFIXES) or path.startswith(_CSRF_EXEMPT_PREFIXES)
