"""TDD for apps.api.routers.auth — httpOnly-cookie login + TOTP MFA flow.

TestClient uses base_url=https so the Secure session cookie is stored and resent
across the multi-step flow. Fakes stand in for the connector + enrolment store;
real SessionTokenService + TOTPMFAService are used.
"""
import pyotp
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.auth_service import AuthService
from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.exceptions import AccountLockedError, AuthenticationError
from shared.auth.mfa import TOTPMFAService
from shared.auth.session_token import SessionTokenService


def _keys():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode(),
        k.public_key().public_bytes(serialization.Encoding.PEM,
                                     serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
    )


KEYS = _keys()


class _FakeConnector:
    def __init__(self, identity=None, exc=None):
        self._identity, self._exc = identity, exc

    @property
    def connector_type(self):
        return "local"

    async def authenticate(self, credentials):
        if self._exc:
            raise self._exc
        return self._identity

    async def health_check(self):
        return True


class _FakeAccounts:
    def __init__(self, enrolled=()):
        self.enrolled = set(enrolled)

    async def is_totp_enrolled(self, uid):
        return uid in self.enrolled

    async def set_totp_enrolled(self, uid, val):
        self.enrolled.add(uid) if val else self.enrolled.discard(uid)


class _MfaStore:
    def __init__(self):
        self.d = {}

    async def put(self, uid, s):
        self.d[uid] = s

    async def get(self, uid):
        return self.d.get(uid)

    async def delete(self, uid):
        self.d.pop(uid, None)


def _identity(**over):
    d = dict(user_id="usr-001", username="ops1", display_name="Ops One",
             entity_type="sb", entity_id="saraswat-coop", bank_id="saraswat-coop",
             role="ops_reviewer", clearing_zones=["MUMBAI"], connector_used="local",
             bank_type="SB", permission_level="EDIT")
    d.update(over)
    return ASTRAIdentity(**d)


def _client(enrolled=(), exc=None, pre_secret=None):
    from apps.api.routers import auth

    priv, pub = KEYS
    session_service = SessionTokenService(priv, pub, "astra-auth", 900)
    mfa_store = _MfaStore()
    mfa = TOTPMFAService(mfa_store, "ASTRA")
    if pre_secret:
        import asyncio
        asyncio.run(mfa_store.put("usr-001", pre_secret))
    connector = _FakeConnector(identity=_identity(), exc=exc)
    accounts = _FakeAccounts(enrolled)
    svc = AuthService(connector=connector, mfa=mfa, session_service=session_service,
                      account_store=accounts)

    app = FastAPI()
    app.include_router(auth.router_v1)
    app.dependency_overrides[auth.get_auth_service] = lambda: svc
    app.dependency_overrides[auth.get_session_service] = lambda: session_service
    return TestClient(app, base_url="https://testserver")


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #

def test_login_enrolled_returns_mfa_required():
    c = _client(enrolled=["usr-001"], pre_secret=pyotp.random_base32())
    r = c.post("/v1/auth/login", json={"username": "ops1", "password": "pw"})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "MFA_REQUIRED"
    assert body["csrf_token"]


def test_login_sets_httponly_secure_samesite_cookie():
    c = _client(enrolled=["usr-001"], pre_secret=pyotp.random_base32())
    r = c.post("/v1/auth/login", json={"username": "ops1", "password": "pw"})
    setc = r.headers.get("set-cookie", "")
    assert "astra_session=" in setc
    assert "HttpOnly" in setc
    assert "Secure" in setc
    assert "SameSite=Strict" in setc.replace(" ", "").replace("samesite", "SameSite") or "SameSite=strict" in setc


def test_login_wrong_password_401():
    c = _client(exc=AuthenticationError("bad"))
    r = c.post("/v1/auth/login", json={"username": "ops1", "password": "x"})
    assert r.status_code == 401


def test_login_locked_account_423():
    c = _client(exc=AccountLockedError("locked"))
    r = c.post("/v1/auth/login", json={"username": "ops1", "password": "x"})
    assert r.status_code == 423


# --------------------------------------------------------------------------- #
# full flow: login -> mfa verify -> session
# --------------------------------------------------------------------------- #

def test_full_login_mfa_verify_then_session():
    secret = pyotp.random_base32()
    c = _client(enrolled=["usr-001"], pre_secret=secret)
    assert c.post("/v1/auth/login", json={"username": "ops1", "password": "pw"}).status_code == 200
    code = pyotp.TOTP(secret).now()
    r = c.post("/v1/auth/mfa/verify", json={"code": code})
    assert r.status_code == 200
    assert r.json()["status"] == "OK"
    # now the full session works
    s = c.get("/v1/auth/session")
    assert s.status_code == 200
    body = s.json()
    assert body["user_id"] == "usr-001"
    assert body["mfa_authenticated"] is True
    assert body["bank_type"] == "SB"


def test_mfa_verify_wrong_code_401():
    c = _client(enrolled=["usr-001"], pre_secret=pyotp.random_base32())
    c.post("/v1/auth/login", json={"username": "ops1", "password": "pw"})
    r = c.post("/v1/auth/mfa/verify", json={"code": "000000"})
    assert r.status_code == 401


def test_mfa_verify_without_session_cookie_401():
    c = _client(enrolled=["usr-001"], pre_secret=pyotp.random_base32())
    r = c.post("/v1/auth/mfa/verify", json={"code": "123456"})
    assert r.status_code == 401


def test_session_endpoint_rejects_half_session():
    c = _client(enrolled=["usr-001"], pre_secret=pyotp.random_base32())
    c.post("/v1/auth/login", json={"username": "ops1", "password": "pw"})
    # only a half-session cookie is set — /session needs a full one
    assert c.get("/v1/auth/session").status_code == 401


# --------------------------------------------------------------------------- #
# enrolment flow (first login)
# --------------------------------------------------------------------------- #

def test_enrollment_flow_new_user():
    c = _client(enrolled=[])
    assert c.post("/v1/auth/login", json={"username": "ops1", "password": "pw"}).json()["outcome"] == "MFA_ENROLLMENT_REQUIRED"
    begin = c.post("/v1/auth/mfa/enrol/begin")
    assert begin.status_code == 200
    secret = begin.json()["secret"]
    assert begin.json()["otpauth_uri"].startswith("otpauth://totp/")
    code = pyotp.TOTP(secret).now()
    confirm = c.post("/v1/auth/mfa/enrol/confirm", json={"code": code})
    assert confirm.status_code == 200
    assert c.get("/v1/auth/session").json()["mfa_authenticated"] is True


# --------------------------------------------------------------------------- #
# logout
# --------------------------------------------------------------------------- #

def test_logout_clears_cookie():
    secret = pyotp.random_base32()
    c = _client(enrolled=["usr-001"], pre_secret=secret)
    c.post("/v1/auth/login", json={"username": "ops1", "password": "pw"})
    c.post("/v1/auth/mfa/verify", json={"code": pyotp.TOTP(secret).now()})
    r = c.post("/v1/auth/logout")
    assert r.status_code == 200
    # cookie cleared -> session endpoint now unauthorized
    assert c.get("/v1/auth/session").status_code == 401
