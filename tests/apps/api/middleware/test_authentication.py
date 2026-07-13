"""TDD for apps.api.middleware.authentication — the central session gate.

Replaces the forgeable per-router test-token auth. The middleware validates the
httpOnly session cookie, sets request.state.user, and enforces CSRF on unsafe
methods. The require_session dependency 401s unless there is a full (MFA-complete)
session. Auth bootstrap paths (/v1/auth/login, /v1/auth/mfa/*) and health are
exempt. TestClient uses base_url=https so the Secure cookie is stored/resent.
"""
import pyotp  # noqa: F401  (kept parallel with other auth tests; not required here)
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from apps.api.dependencies import require_session
from apps.api.middleware.authentication import AuthenticationMiddleware
from shared.auth.session_token import SessionTokenService

_COOKIE = "astra_session"


def _keys():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode(),
        k.public_key().public_bytes(serialization.Encoding.PEM,
                                     serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
    )


def _build():
    priv, pub = _keys()
    session_service = SessionTokenService(priv, pub, "astra-auth", 900)

    app = FastAPI()
    app.state.session_service = session_service
    app.add_middleware(AuthenticationMiddleware)

    @app.get("/v1/protected")
    async def protected(claims=Depends(require_session)):
        return {"user": claims.user_id}

    @app.post("/v1/protected/act")
    async def act(claims=Depends(require_session)):
        return {"ok": True}

    @app.get("/v1/protected/state-bank-id")
    async def state_bank_id(request: Request):
        return {"bank_id": getattr(request.state, "bank_id", "UNSET")}

    @app.post("/v1/auth/login")
    async def login():
        return {"ok": "login"}

    @app.get("/health/live")
    async def health():
        return {"status": "ok"}

    client = TestClient(app, base_url="https://testserver")
    return client, session_service


def _full(session_service, **over):
    params = dict(
        user_id="usr-001", username="ops1", bank_id="saraswat-coop", bank_type="SB",
        permission_level="EDIT", role="ops_reviewer", entity_type="sb",
        entity_id="saraswat-coop", clearing_zones=["MUMBAI"], mfa_authenticated=True,
    )
    params.update(over)
    return session_service.issue(**params)


def _set_cookie(client, token):
    client.cookies.set(_COOKIE, token)


# --------------------------------------------------------------------------- #

def test_protected_without_cookie_is_401():
    client, _ = _build()
    assert client.get("/v1/protected").status_code == 401


def test_protected_with_valid_full_session_is_200():
    client, ss = _build()
    _set_cookie(client, _full(ss).token)
    r = client.get("/v1/protected")
    assert r.status_code == 200
    assert r.json()["user"] == "usr-001"


def test_garbage_cookie_is_401():
    client, _ = _build()
    _set_cookie(client, "not-a-jwt")
    assert client.get("/v1/protected").status_code == 401


def test_half_session_cannot_reach_protected_routes():
    client, ss = _build()
    _set_cookie(client, _full(ss, mfa_authenticated=False).token)
    assert client.get("/v1/protected").status_code == 401


def test_unsafe_method_without_csrf_is_403():
    client, ss = _build()
    _set_cookie(client, _full(ss).token)
    assert client.post("/v1/protected/act").status_code == 403


def test_unsafe_method_with_wrong_csrf_is_403():
    client, ss = _build()
    _set_cookie(client, _full(ss).token)
    r = client.post("/v1/protected/act", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403


def test_unsafe_method_with_correct_csrf_is_200():
    client, ss = _build()
    issued = _full(ss)
    _set_cookie(client, issued.token)
    r = client.post("/v1/protected/act", headers={"X-CSRF-Token": issued.csrf_token})
    assert r.status_code == 200


def test_auth_bootstrap_login_is_csrf_exempt():
    client, _ = _build()
    # No cookie, no CSRF — login must still be reachable
    assert client.post("/v1/auth/login").status_code == 200


def test_health_is_public():
    client, _ = _build()
    assert client.get("/health/live").status_code == 200


def test_valid_session_sets_state_bank_id():
    """RateLimitMiddleware keys per-bank limits off request.state.bank_id
    (falls back to per-IP otherwise) — the auth middleware must set it."""
    client, ss = _build()
    _set_cookie(client, _full(ss, bank_id="saraswat-coop").token)
    r = client.get("/v1/protected/state-bank-id")
    assert r.status_code == 200
    assert r.json()["bank_id"] == "saraswat-coop"


def test_no_session_leaves_state_bank_id_none():
    client, _ = _build()
    r = client.get("/v1/protected/state-bank-id")
    assert r.status_code == 200
    assert r.json()["bank_id"] is None
