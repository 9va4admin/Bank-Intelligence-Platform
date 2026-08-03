"""ASTRA session token — RS256 JWT issued after successful authentication.

Delivered to the browser as an httpOnly + Secure + SameSite=Strict cookie, so an
injected script cannot read it (XSS cannot steal the session). A bound CSRF token
(signed double-submit) is returned in the response body and must be echoed in the
X-CSRF-Token header on every state-changing request; the middleware compares it to
the `csrf` claim inside the verified token.

Asymmetric RS256: the auth service holds the private key (signs); every service
validates with the public key. Both come from Vault via config_service in
production and are injected here, so this module stays pure crypto + claims —
no Redis, no DB — and unit-tests cleanly. Session revocation (force-logout) is
layered on top in the auth middleware via a Redis record keyed by session_id.

The algorithm is pinned to RS256 on decode. This is deliberate and load-bearing:
it blocks the classic JWT algorithm-confusion downgrade (an attacker signing an
HS256 token with the public key as the shared secret).
"""
from __future__ import annotations

import hmac
import secrets
import time
from typing import Optional

import jwt
from pydantic import BaseModel, ConfigDict, Field

from shared.auth.exceptions import (
    CSRFValidationError,
    InvalidSessionError,
    SessionExpiredError,
)

_ALGORITHM = "RS256"
_CSRF_BYTES = 32
_SESSION_ID_BYTES = 18
_DEFAULT_TTL_SECONDS = 900  # 15 minutes


class SessionClaims(BaseModel):
    """Verified identity extracted from a session token — mirrors UserContext."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    username: str
    bank_id: str
    bank_type: str            # "SB" | "SMB"
    permission_level: str     # "ADMIN" | "EDIT" | "READ_ONLY"
    role: str
    entity_type: str          # "sb" | "smb" | "branch" | "pu"
    entity_id: str
    clearing_zones: list[str] = Field(default_factory=list)
    session_id: str           # JWT jti — Redis revocation key
    mfa_authenticated: bool
    issued_at: float
    expires_at: float
    csrf_token: str


class IssuedSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    token: str                # goes into the httpOnly cookie
    csrf_token: str           # goes into the response body -> X-CSRF-Token header
    session_id: str
    expires_at: float
    claims: SessionClaims


class SessionTokenService:
    """Issues and validates RS256 ASTRA session tokens."""

    def __init__(
        self,
        private_key_pem: Optional[str],
        public_key_pem: str,
        issuer: str = "astra-auth",
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        # private_key_pem may be None on validation-only services (they only verify)
        self._priv = private_key_pem
        self._pub = public_key_pem
        self._issuer = issuer
        self._ttl = int(ttl_seconds)

    def issue(
        self,
        *,
        user_id: str,
        username: str,
        bank_id: str,
        bank_type: str,
        permission_level: str,
        role: str,
        entity_type: str,
        entity_id: str,
        mfa_authenticated: bool,
        clearing_zones: Optional[list[str]] = None,
    ) -> IssuedSession:
        if self._priv is None:
            raise RuntimeError("SessionTokenService has no private key — cannot issue")

        now = int(time.time())
        exp = now + self._ttl
        session_id = secrets.token_urlsafe(_SESSION_ID_BYTES)
        csrf = secrets.token_urlsafe(_CSRF_BYTES)
        zones = list(clearing_zones or [])

        payload = {
            "sub": user_id,
            "iss": self._issuer,
            "jti": session_id,
            "iat": now,
            "exp": exp,
            "username": username,
            "bank_id": bank_id,
            "bank_type": bank_type,
            "permission_level": permission_level,
            "role": role,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "clearing_zones": zones,
            "mfa_authenticated": bool(mfa_authenticated),
            "csrf": csrf,
        }
        token = jwt.encode(payload, self._priv, algorithm=_ALGORITHM)

        claims = SessionClaims(
            user_id=user_id,
            username=username,
            bank_id=bank_id,
            bank_type=bank_type,
            permission_level=permission_level,
            role=role,
            entity_type=entity_type,
            entity_id=entity_id,
            clearing_zones=zones,
            session_id=session_id,
            mfa_authenticated=bool(mfa_authenticated),
            issued_at=float(now),
            expires_at=float(exp),
            csrf_token=csrf,
        )
        return IssuedSession(
            token=token,
            csrf_token=csrf,
            session_id=session_id,
            expires_at=claims.expires_at,
            claims=claims,
        )

    def validate(self, token: str) -> SessionClaims:
        """Verify signature, algorithm, issuer, expiry and required claims.

        Raises SessionExpiredError on expiry, InvalidSessionError on anything else.
        """
        try:
            decoded = jwt.decode(
                token,
                self._pub,
                algorithms=[_ALGORITHM],          # pinned — blocks alg confusion
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "jti", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise SessionExpiredError("session token expired") from exc
        except jwt.PyJWTError as exc:
            raise InvalidSessionError(f"invalid session token: {exc}") from exc

        try:
            return SessionClaims(
                user_id=decoded["sub"],
                username=decoded["username"],
                bank_id=decoded["bank_id"],
                bank_type=decoded["bank_type"],
                permission_level=decoded["permission_level"],
                role=decoded["role"],
                entity_type=decoded["entity_type"],
                entity_id=decoded["entity_id"],
                clearing_zones=list(decoded.get("clearing_zones", [])),
                session_id=decoded["jti"],
                mfa_authenticated=bool(decoded["mfa_authenticated"]),
                issued_at=float(decoded["iat"]),
                expires_at=float(decoded["exp"]),
                csrf_token=decoded["csrf"],
            )
        except KeyError as exc:
            raise InvalidSessionError(f"session token missing claim: {exc}") from exc

    def validate_csrf(self, claims: SessionClaims, presented: Optional[str]) -> None:
        """Constant-time compare the presented CSRF token to the bound claim."""
        if not presented or not hmac.compare_digest(str(claims.csrf_token), str(presented)):
            raise CSRFValidationError("CSRF token mismatch")
