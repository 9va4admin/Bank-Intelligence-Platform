"""Shared FastAPI auth dependencies — the single identity chokepoint.

AuthenticationMiddleware validates the httpOnly session cookie once per request
and sets request.state.user (SessionClaims or None). These dependencies read that
state; routers must never parse tokens themselves. A pre-MFA (half) session is
treated as unauthenticated for the app surface — only the /v1/auth/mfa/* bootstrap
accepts it.
"""
from fastapi import HTTPException, Request, status

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext
from shared.auth.session_token import SessionClaims


def require_session(request: Request) -> SessionClaims:
    """Return the verified full session, or raise 401."""
    claims = getattr(request.state, "user", None)
    if claims is None or not getattr(claims, "mfa_authenticated", False):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return claims


def require_user_context(request: Request) -> UserContext:
    """Map the verified session to the RBAC UserContext used by route handlers."""
    claims = require_session(request)
    try:
        return UserContext(
            user_id=claims.user_id,
            role=Role(claims.role),
            bank_id=claims.bank_id,
            bank_type=BankType(claims.bank_type),
            permission_level=PermissionLevel(claims.permission_level),
            clearing_zones=claims.clearing_zones,
        )
    except ValueError as exc:  # unknown role/type/level in a (signed) token — fail closed
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session claims"
        ) from exc
