"""TDD for shared.auth.session_token — RS256 ASTRA session JWT.

Security contract pinned here:
  - RS256 issue/validate round-trip preserves all identity claims
  - short TTL; expired tokens rejected
  - tampered / wrong-key / malformed tokens rejected
  - ALGORITHM CONFUSION rejected: an HS256 token signed with the RSA public key
    (the classic PyJWT downgrade attack) must NOT validate
  - CSRF token bound to the session; mismatch rejected (constant-time)
  - pre-MFA "half sessions" distinguishable via mfa_authenticated=False
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from shared.auth.exceptions import (
    CSRFValidationError,
    InvalidSessionError,
    SessionExpiredError,
)
from shared.auth.session_token import (
    IssuedSession,
    SessionClaims,
    SessionTokenService,
)

_ISSUER = "astra-auth"


def _rsa_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


@pytest.fixture(scope="module")
def keys() -> tuple[str, str]:
    return _rsa_keypair()


@pytest.fixture()
def svc(keys) -> SessionTokenService:
    priv, pub = keys
    return SessionTokenService(
        private_key_pem=priv, public_key_pem=pub, issuer=_ISSUER, ttl_seconds=900
    )


def _issue_sample(svc: SessionTokenService, **overrides) -> IssuedSession:
    params = dict(
        user_id="usr-001",
        username="ops1",
        bank_id="saraswat-coop",
        bank_type="SB",
        permission_level="EDIT",
        role="ops_reviewer",
        entity_type="sb",
        entity_id="saraswat-coop",
        clearing_zones=["MUMBAI"],
        mfa_authenticated=True,
    )
    params.update(overrides)
    return svc.issue(**params)


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #

def test_issue_returns_issued_session_with_token_and_csrf(svc):
    issued = _issue_sample(svc)
    assert isinstance(issued, IssuedSession)
    assert issued.token and isinstance(issued.token, str)
    assert issued.csrf_token and isinstance(issued.csrf_token, str)
    assert issued.session_id
    assert issued.expires_at > time.time()


def test_validate_roundtrips_all_identity_claims(svc):
    issued = _issue_sample(svc)
    claims = svc.validate(issued.token)
    assert isinstance(claims, SessionClaims)
    assert claims.user_id == "usr-001"
    assert claims.username == "ops1"
    assert claims.bank_id == "saraswat-coop"
    assert claims.bank_type == "SB"
    assert claims.permission_level == "EDIT"
    assert claims.role == "ops_reviewer"
    assert claims.entity_type == "sb"
    assert claims.clearing_zones == ["MUMBAI"]
    assert claims.mfa_authenticated is True
    assert claims.session_id == issued.session_id
    assert claims.csrf_token == issued.csrf_token


def test_exp_equals_iat_plus_ttl(svc):
    issued = _issue_sample(svc)
    claims = svc.validate(issued.token)
    assert round(claims.expires_at - claims.issued_at) == 900


def test_each_issue_has_unique_session_id_and_csrf(svc):
    a = _issue_sample(svc)
    b = _issue_sample(svc)
    assert a.session_id != b.session_id
    assert a.csrf_token != b.csrf_token


def test_half_session_mfa_not_authenticated_roundtrips(svc):
    issued = _issue_sample(svc, mfa_authenticated=False)
    claims = svc.validate(issued.token)
    assert claims.mfa_authenticated is False


# --------------------------------------------------------------------------- #
# Rejection paths
# --------------------------------------------------------------------------- #

def test_expired_token_raises_session_expired(svc, keys):
    priv, _ = keys
    past = time.time() - 10
    token = jwt.encode(
        {
            "sub": "usr-001", "iss": _ISSUER, "jti": "s1",
            "iat": past - 900, "exp": past,
            "username": "ops1", "bank_id": "saraswat-coop", "bank_type": "SB",
            "permission_level": "EDIT", "role": "ops_reviewer",
            "entity_type": "sb", "entity_id": "saraswat-coop",
            "clearing_zones": ["MUMBAI"], "mfa_authenticated": True, "csrf": "x",
        },
        priv, algorithm="RS256",
    )
    with pytest.raises(SessionExpiredError):
        svc.validate(token)


def test_tampered_token_raises_invalid(svc):
    issued = _issue_sample(svc)
    tampered = issued.token[:-3] + ("aaa" if not issued.token.endswith("aaa") else "bbb")
    with pytest.raises(InvalidSessionError):
        svc.validate(tampered)


def test_token_signed_with_other_key_raises_invalid(svc):
    other_priv, _ = _rsa_keypair()
    forged = jwt.encode(
        {"sub": "attacker", "iss": _ISSUER, "jti": "s1",
         "iat": time.time(), "exp": time.time() + 900, "csrf": "x"},
        other_priv, algorithm="RS256",
    )
    with pytest.raises(InvalidSessionError):
        svc.validate(forged)


def _forge(header: dict, payload: dict, secret: bytes = b"") -> str:
    """Hand-craft a JWT at the wire level (bypassing PyJWT's encode guards),
    the way a real attacker would."""
    import base64
    import hashlib
    import hmac as _hmac
    import json

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    h = b64(json.dumps(header).encode())
    p = b64(json.dumps(payload).encode())
    signing_input = h + b"." + p
    if header.get("alg") == "HS256":
        sig = b64(_hmac.new(secret, signing_input, hashlib.sha256).digest())
    else:  # "none"
        sig = b""
    return (signing_input + b"." + sig).decode()


def test_algorithm_confusion_hs256_with_public_key_rejected(svc, keys):
    """Classic downgrade: attacker forges an HS256 token using the RSA public key
    bytes as the HMAC secret. PyJWT's own encode() blocks this, so we forge at the
    wire level to prove validate() rejects it purely because it pins RS256."""
    _, pub = keys
    now = int(time.time())
    forged = _forge(
        {"alg": "HS256", "typ": "JWT"},
        {"sub": "attacker", "iss": _ISSUER, "jti": "s1", "iat": now, "exp": now + 900, "csrf": "x"},
        secret=pub.encode(),
    )
    with pytest.raises(InvalidSessionError):
        svc.validate(forged)


def test_alg_none_unsigned_token_rejected(svc):
    """An unsigned 'alg: none' token must never validate."""
    now = int(time.time())
    forged = _forge(
        {"alg": "none", "typ": "JWT"},
        {"sub": "attacker", "iss": _ISSUER, "jti": "s1", "iat": now, "exp": now + 900, "csrf": "x"},
    )
    with pytest.raises(InvalidSessionError):
        svc.validate(forged)


def test_wrong_issuer_rejected(svc, keys):
    priv, _ = keys
    forged = jwt.encode(
        {"sub": "usr-001", "iss": "evil-issuer", "jti": "s1",
         "iat": time.time(), "exp": time.time() + 900, "csrf": "x"},
        priv, algorithm="RS256",
    )
    with pytest.raises(InvalidSessionError):
        svc.validate(forged)


def test_malformed_token_rejected(svc):
    with pytest.raises(InvalidSessionError):
        svc.validate("not-a-jwt")


# --------------------------------------------------------------------------- #
# CSRF binding
# --------------------------------------------------------------------------- #

def test_validate_csrf_accepts_matching(svc):
    issued = _issue_sample(svc)
    claims = svc.validate(issued.token)
    # does not raise
    svc.validate_csrf(claims, issued.csrf_token)


def test_validate_csrf_rejects_mismatch(svc):
    issued = _issue_sample(svc)
    claims = svc.validate(issued.token)
    with pytest.raises(CSRFValidationError):
        svc.validate_csrf(claims, "wrong-csrf-token")


def test_validate_csrf_rejects_empty(svc):
    issued = _issue_sample(svc)
    claims = svc.validate(issued.token)
    with pytest.raises(CSRFValidationError):
        svc.validate_csrf(claims, "")
