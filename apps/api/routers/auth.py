"""Local authentication router — password + mandatory TOTP MFA, httpOnly cookie.

Flow (mandatory MFA, no backup codes):
  POST /v1/auth/login                 password -> half-session cookie + outcome
  POST /v1/auth/mfa/verify            enrolled: TOTP code -> full-session cookie
  POST /v1/auth/mfa/enrol/begin       first login: QR secret + otpauth URI
  POST /v1/auth/mfa/enrol/confirm     first login: first TOTP code -> full session
  POST /v1/auth/logout                clear cookie
  POST /v1/auth/refresh               full session -> re-issued (sliding expiry)
  GET  /v1/auth/session               who am I (full session only)

The session token rides in a Secure, HttpOnly, SameSite=Strict cookie so an
injected script can never read it. The bound CSRF token is returned in the body;
the client echoes it as X-CSRF-Token on state-changing calls. CSRF *enforcement*
on the authenticated app surface is done by the auth middleware; the auth
bootstrap routes here are CSRF-exempt (they are protected by SameSite=Strict).

Business logic lives in shared.auth.auth_service (api.md: routers stay thin).
"""
from __future__ import annotations

import time
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from shared.auth.auth_service import AuthService, LoginOutcome
from shared.auth.exceptions import (
    AccountLockedError,
    AuthenticationError,
    InvalidSessionError,
    MFANotEnrolledError,
    SessionExpiredError,
)
from shared.auth.session_token import IssuedSession, SessionClaims, SessionTokenService

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/auth", tags=["Auth v1"])

_COOKIE = "astra_session"


# --------------------------------------------------------------------------- #
# Dependencies (overridden in tests; wired from app.state in production)
# --------------------------------------------------------------------------- #

def get_session_service(request: Request) -> SessionTokenService:
    svc = getattr(request.app.state, "session_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Authentication not configured")
    return svc


def get_auth_service(request: Request) -> AuthService:
    svc = getattr(request.app.state, "auth_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Authentication not configured")
    return svc


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class LoginRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    username: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                 # MFA_REQUIRED | MFA_ENROLLMENT_REQUIRED
    requires: str                # "mfa_code" | "mfa_enrollment"
    csrf_token: str


class CodeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str = Field(..., min_length=6, max_length=10)


class AuthOkResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    csrf_token: str


class EnrollBeginResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    secret: str
    otpauth_uri: str


class LogoutResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    username: str
    bank_id: str
    bank_type: str
    role: str
    permission_level: str
    clearing_zones: list[str]
    mfa_authenticated: bool


# --------------------------------------------------------------------------- #
# Cookie helpers
# --------------------------------------------------------------------------- #

def _set_session_cookie(response: Response, issued: IssuedSession) -> None:
    response.set_cookie(
        key=_COOKIE,
        value=issued.token,
        max_age=max(1, int(issued.expires_at - time.time())),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    # Match the attributes the cookie was set with so every browser clears it.
    response.delete_cookie(key=_COOKIE, path="/", secure=True, httponly=True, samesite="strict")


def _claims_from_cookie(
    request: Request,
    session_service: SessionTokenService,
    *,
    require_mfa: bool,
) -> SessionClaims:
    token = request.cookies.get(_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        claims = session_service.validate(token)
    except SessionExpiredError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    except InvalidSessionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    if require_mfa and not claims.mfa_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA required")
    return claims


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@router_v1.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    try:
        result = await auth_service.login(body.username, body.password)
    except AccountLockedError:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account locked due to repeated failed attempts. Contact your administrator.",
        )
    except AuthenticationError:
        # Uniform message — never reveal whether the username exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    _set_session_cookie(response, result.interim_session)
    requires = "mfa_code" if result.outcome == LoginOutcome.MFA_REQUIRED else "mfa_enrollment"
    return LoginResponse(
        outcome=result.outcome.value,
        requires=requires,
        csrf_token=result.interim_session.csrf_token,
    )


@router_v1.post("/mfa/verify", response_model=AuthOkResponse)
async def mfa_verify(
    body: CodeRequest,
    request: Request,
    response: Response,
    session_service: SessionTokenService = Depends(get_session_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthOkResponse:
    claims = _claims_from_cookie(request, session_service, require_mfa=False)
    try:
        full = await auth_service.verify_mfa(claims, body.code)
    except (AuthenticationError, MFANotEnrolledError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")
    except InvalidSessionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session state")
    _set_session_cookie(response, full)
    return AuthOkResponse(status="OK", csrf_token=full.csrf_token)


@router_v1.post("/mfa/enrol/begin", response_model=EnrollBeginResponse)
async def mfa_enrol_begin(
    request: Request,
    session_service: SessionTokenService = Depends(get_session_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> EnrollBeginResponse:
    claims = _claims_from_cookie(request, session_service, require_mfa=False)
    try:
        challenge = await auth_service.begin_enrollment(claims)
    except InvalidSessionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session state")
    return EnrollBeginResponse(secret=challenge.secret, otpauth_uri=challenge.otpauth_uri)


@router_v1.post("/mfa/enrol/confirm", response_model=AuthOkResponse)
async def mfa_enrol_confirm(
    body: CodeRequest,
    request: Request,
    response: Response,
    session_service: SessionTokenService = Depends(get_session_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthOkResponse:
    claims = _claims_from_cookie(request, session_service, require_mfa=False)
    try:
        full = await auth_service.confirm_enrollment(claims, body.code)
    except (AuthenticationError, MFANotEnrolledError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")
    except InvalidSessionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session state")
    _set_session_cookie(response, full)
    return AuthOkResponse(status="OK", csrf_token=full.csrf_token)


@router_v1.post("/refresh", response_model=AuthOkResponse)
async def refresh(
    request: Request,
    response: Response,
    session_service: SessionTokenService = Depends(get_session_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthOkResponse:
    claims = _claims_from_cookie(request, session_service, require_mfa=True)
    try:
        new = await auth_service.refresh(claims)
    except InvalidSessionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session state")
    _set_session_cookie(response, new)
    return AuthOkResponse(status="OK", csrf_token=new.csrf_token)


@router_v1.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response) -> LogoutResponse:
    # Clearing your own cookie is idempotent and low-risk — no CSRF gate needed.
    _clear_session_cookie(response)
    return LogoutResponse(status="OK")


@router_v1.get("/session", response_model=SessionResponse)
async def whoami(
    request: Request,
    session_service: SessionTokenService = Depends(get_session_service),
) -> SessionResponse:
    claims = _claims_from_cookie(request, session_service, require_mfa=True)
    return SessionResponse(
        user_id=claims.user_id,
        username=claims.username,
        bank_id=claims.bank_id,
        bank_type=claims.bank_type,
        role=claims.role,
        permission_level=claims.permission_level,
        clearing_zones=claims.clearing_zones,
        mfa_authenticated=claims.mfa_authenticated,
    )
