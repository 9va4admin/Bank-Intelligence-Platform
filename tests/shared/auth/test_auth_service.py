"""TDD for shared.auth.auth_service — the login -> MFA -> session state machine.

Invariants pinned here (mandatory MFA, no backup codes):
  - password alone NEVER yields a full session; the interim session is always
    mfa_authenticated=False
  - an enrolled user goes password -> MFA_REQUIRED -> verify -> full session
  - a first-time user goes password -> MFA_ENROLLMENT_REQUIRED -> enrol+confirm -> full session
  - wrong password / locked account / wrong code all fail closed
  - bank_type/permission_level derive fail-closed (unknown level -> READ_ONLY)

Real SessionTokenService + real TOTPMFAService are used; only the connector and
the enrolment-flag store are faked. Async is driven with asyncio.run().
"""
import asyncio

import pyotp
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from shared.auth.auth_service import AuthService, LoginOutcome, LoginResult
from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.exceptions import (
    AccountLockedError,
    AuthenticationError,
    InvalidSessionError,
)
from shared.auth.mfa import TOTPMFAService
from shared.auth.session_token import IssuedSession, SessionTokenService


def _keys():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = k.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = k.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


KEYS = _keys()


class _FakeConnector:
    def __init__(self, identity=None, exc=None):
        self._identity = identity
        self._exc = exc

    @property
    def connector_type(self):
        return "local"

    async def authenticate(self, credentials):
        if self._exc is not None:
            raise self._exc
        return self._identity

    async def health_check(self):
        return True


class _FakeAccounts:
    def __init__(self, enrolled=()):
        self.enrolled = set(enrolled)

    async def is_totp_enrolled(self, user_id):
        return user_id in self.enrolled

    async def set_totp_enrolled(self, user_id, enrolled):
        if enrolled:
            self.enrolled.add(user_id)
        else:
            self.enrolled.discard(user_id)


class _MfaStore:
    def __init__(self):
        self.d = {}

    async def put(self, uid, secret):
        self.d[uid] = secret

    async def get(self, uid):
        return self.d.get(uid)

    async def delete(self, uid):
        self.d.pop(uid, None)


def _identity(**over):
    d = dict(
        user_id="usr-001", username="ops1", display_name="Ops One",
        entity_type="sb", entity_id="saraswat-coop", bank_id="saraswat-coop",
        role="ops_reviewer", clearing_zones=["MUMBAI"], connector_used="local",
        bank_type="SB", permission_level="EDIT",
    )
    d.update(over)
    return ASTRAIdentity(**d)


def _service(identity=None, exc=None, enrolled=(), mfa=None):
    priv, pub = KEYS
    sess = SessionTokenService(priv, pub, "astra-auth", 900)
    mfa = mfa or TOTPMFAService(_MfaStore(), "ASTRA")
    conn = _FakeConnector(identity=identity if identity is not None else _identity(), exc=exc)
    accts = _FakeAccounts(enrolled)
    svc = AuthService(connector=conn, mfa=mfa, session_service=sess, account_store=accts)
    return svc, mfa, accts, sess


# --------------------------------------------------------------------------- #
# login stage
# --------------------------------------------------------------------------- #

def test_login_enrolled_user_requires_mfa():
    svc, _, _, sess = _service(enrolled=["usr-001"])
    result = asyncio.run(svc.login("ops1", "pw"))
    assert isinstance(result, LoginResult)
    assert result.outcome == LoginOutcome.MFA_REQUIRED
    claims = sess.validate(result.interim_session.token)
    assert claims.mfa_authenticated is False
    assert claims.user_id == "usr-001"


def test_login_new_user_requires_enrollment():
    svc, _, _, _ = _service(enrolled=[])
    result = asyncio.run(svc.login("ops1", "pw"))
    assert result.outcome == LoginOutcome.MFA_ENROLLMENT_REQUIRED
    assert result.interim_session.claims.mfa_authenticated is False


def test_login_interim_session_never_mfa_authenticated():
    for enrolled in ([], ["usr-001"]):
        svc, _, _, _ = _service(enrolled=enrolled)
        result = asyncio.run(svc.login("ops1", "pw"))
        assert result.interim_session.claims.mfa_authenticated is False


def test_login_wrong_password_propagates():
    svc, _, _, _ = _service(exc=AuthenticationError("invalid credentials"))
    with pytest.raises(AuthenticationError):
        asyncio.run(svc.login("ops1", "wrong"))


def test_login_locked_account_propagates():
    svc, _, _, _ = _service(exc=AccountLockedError("locked"))
    with pytest.raises(AccountLockedError):
        asyncio.run(svc.login("ops1", "pw"))


def test_login_derives_bank_type_smb_from_entity_type():
    ident = _identity(entity_type="smb", bank_type=None, role="smb_editor")
    svc, _, _, sess = _service(identity=ident, enrolled=["usr-001"])
    result = asyncio.run(svc.login("smbuser", "pw"))
    claims = sess.validate(result.interim_session.token)
    assert claims.bank_type == "SMB"


def test_login_permission_level_fails_closed_to_read_only():
    ident = _identity(permission_level=None)
    svc, _, _, sess = _service(identity=ident, enrolled=["usr-001"])
    result = asyncio.run(svc.login("ops1", "pw"))
    claims = sess.validate(result.interim_session.token)
    assert claims.permission_level == "READ_ONLY"


# --------------------------------------------------------------------------- #
# MFA verify stage (already-enrolled user)
# --------------------------------------------------------------------------- #

def _enrolled_service():
    """Build a service whose usr-001 already has a TOTP secret + enrolled flag."""
    mfa_store = _MfaStore()
    mfa = TOTPMFAService(mfa_store, "ASTRA")
    secret = TOTPMFAService.generate_secret()
    asyncio.run(mfa_store.put("usr-001", secret))
    svc, _, accts, sess = _service(enrolled=["usr-001"], mfa=mfa)
    return svc, sess, secret


def test_verify_mfa_correct_code_issues_full_session():
    svc, sess, secret = _enrolled_service()
    interim = asyncio.run(svc.login("ops1", "pw")).interim_session
    interim_claims = sess.validate(interim.token)
    code = pyotp.TOTP(secret).now()
    full = asyncio.run(svc.verify_mfa(interim_claims, code))
    assert isinstance(full, IssuedSession)
    full_claims = sess.validate(full.token)
    assert full_claims.mfa_authenticated is True
    assert full_claims.user_id == "usr-001"
    assert full_claims.bank_id == "saraswat-coop"


def test_verify_mfa_wrong_code_fails_closed():
    svc, sess, _ = _enrolled_service()
    interim = asyncio.run(svc.login("ops1", "pw")).interim_session
    interim_claims = sess.validate(interim.token)
    with pytest.raises(AuthenticationError):
        asyncio.run(svc.verify_mfa(interim_claims, "000000"))


def test_verify_mfa_rejects_already_full_session():
    svc, sess, secret = _enrolled_service()
    interim = asyncio.run(svc.login("ops1", "pw")).interim_session
    interim_claims = sess.validate(interim.token)
    code = pyotp.TOTP(secret).now()
    full = asyncio.run(svc.verify_mfa(interim_claims, code))
    full_claims = sess.validate(full.token)
    with pytest.raises(InvalidSessionError):
        asyncio.run(svc.verify_mfa(full_claims, pyotp.TOTP(secret).now()))


# --------------------------------------------------------------------------- #
# Enrolment stage (first-time user)
# --------------------------------------------------------------------------- #

def test_enrollment_flow_confirms_and_marks_enrolled():
    svc, mfa, accts, sess = _service(enrolled=[])
    interim = asyncio.run(svc.login("ops1", "pw")).interim_session
    interim_claims = sess.validate(interim.token)

    challenge = asyncio.run(svc.begin_enrollment(interim_claims))
    assert challenge.otpauth_uri.startswith("otpauth://totp/")

    code = pyotp.TOTP(challenge.secret).now()
    full = asyncio.run(svc.confirm_enrollment(interim_claims, code))
    full_claims = sess.validate(full.token)
    assert full_claims.mfa_authenticated is True
    assert asyncio.run(accts.is_totp_enrolled("usr-001")) is True


def test_confirm_enrollment_wrong_code_stays_unenrolled():
    svc, mfa, accts, sess = _service(enrolled=[])
    interim = asyncio.run(svc.login("ops1", "pw")).interim_session
    interim_claims = sess.validate(interim.token)
    asyncio.run(svc.begin_enrollment(interim_claims))
    with pytest.raises(AuthenticationError):
        asyncio.run(svc.confirm_enrollment(interim_claims, "000000"))
    assert asyncio.run(accts.is_totp_enrolled("usr-001")) is False
