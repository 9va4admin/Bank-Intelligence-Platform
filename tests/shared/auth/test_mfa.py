"""TDD for shared.auth.mfa — mandatory TOTP (RFC 6238), no backup codes.

Correctness is cross-checked against pyotp as a reference oracle, proving the
hand-rolled (dependency-free) implementation is standards-compliant. Secrets are
held by an injected store (Vault in production); tests use an in-memory fake.
Async methods are driven with asyncio.run() so this suite doesn't depend on the
project's pytest-asyncio configuration.
"""
import asyncio
import base64
import time
from urllib.parse import parse_qs, unquote, urlparse

import pyotp
import pytest

from shared.auth.exceptions import MFANotEnrolledError
from shared.auth.mfa import EnrollmentChallenge, TOTPMFAService


class _FakeStore:
    """In-memory stand-in for the Vault-backed TOTP secret store."""

    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    async def put(self, user_id: str, secret: str) -> None:
        self.d[user_id] = secret

    async def get(self, user_id: str):
        return self.d.get(user_id)

    async def delete(self, user_id: str) -> None:
        self.d.pop(user_id, None)


def _svc() -> TOTPMFAService:
    return TOTPMFAService(store=_FakeStore(), issuer="ASTRA")


# --------------------------------------------------------------------------- #
# Pure TOTP correctness (oracle: pyotp)
# --------------------------------------------------------------------------- #

def test_generate_secret_is_base32_and_unique():
    a = TOTPMFAService.generate_secret()
    b = TOTPMFAService.generate_secret()
    assert a != b
    # decodable as base32 (pad defensively)
    base64.b32decode(a + "=" * (-len(a) % 8))
    assert len(a) >= 16


def test_verify_code_accepts_pyotp_generated_code():
    secret = TOTPMFAService.generate_secret()
    now = int(time.time())
    code = pyotp.TOTP(secret).at(now)
    assert TOTPMFAService.verify_code(secret, code, at_time=now) is True


def test_verify_code_rejects_wrong_code():
    secret = TOTPMFAService.generate_secret()
    assert TOTPMFAService.verify_code(secret, "000000", at_time=int(time.time())) is False


def test_verify_code_accepts_previous_step_within_window():
    secret = TOTPMFAService.generate_secret()
    now = int(time.time())
    prev = pyotp.TOTP(secret).at(now - 30)
    assert TOTPMFAService.verify_code(secret, prev, window=1, at_time=now) is True


def test_verify_code_rejects_step_outside_window():
    secret = TOTPMFAService.generate_secret()
    now = int(time.time())
    far = pyotp.TOTP(secret).at(now - 120)
    assert TOTPMFAService.verify_code(secret, far, window=1, at_time=now) is False


def test_verify_code_handles_garbage_secret():
    assert TOTPMFAService.verify_code("!!!not-base32!!!", "123456", at_time=int(time.time())) is False


def test_provisioning_uri_contains_issuer_account_and_secret():
    svc = _svc()
    secret = "JBSWY3DPEHPK3PXP"
    uri = svc.provisioning_uri(secret, "ops1@saraswat")
    parsed = urlparse(uri)
    assert parsed.scheme == "otpauth"
    assert parsed.netloc == "totp"
    qs = parse_qs(parsed.query)
    assert qs["secret"] == [secret]
    assert qs["issuer"] == ["ASTRA"]
    decoded_path = unquote(parsed.path)
    assert "ASTRA" in decoded_path and "ops1@saraswat" in decoded_path


# --------------------------------------------------------------------------- #
# Enrolment + verification lifecycle (store-backed)
# --------------------------------------------------------------------------- #

def test_begin_enrollment_stores_secret_and_returns_challenge():
    store = _FakeStore()
    svc = TOTPMFAService(store=store, issuer="ASTRA")
    challenge = asyncio.run(svc.begin_enrollment("usr-001", "ops1@saraswat"))
    assert isinstance(challenge, EnrollmentChallenge)
    assert challenge.secret == store.d["usr-001"]
    assert challenge.otpauth_uri.startswith("otpauth://totp/")


def test_confirm_enrollment_accepts_valid_code():
    store = _FakeStore()
    svc = TOTPMFAService(store=store, issuer="ASTRA")
    challenge = asyncio.run(svc.begin_enrollment("usr-001", "ops1@saraswat"))
    code = pyotp.TOTP(challenge.secret).now()
    assert asyncio.run(svc.confirm_enrollment("usr-001", code)) is True


def test_confirm_enrollment_rejects_invalid_code():
    svc = _svc()
    asyncio.run(svc.begin_enrollment("usr-001", "ops1@saraswat"))
    assert asyncio.run(svc.confirm_enrollment("usr-001", "000000")) is False


def test_verify_accepts_valid_code_after_enrollment():
    store = _FakeStore()
    svc = TOTPMFAService(store=store, issuer="ASTRA")
    challenge = asyncio.run(svc.begin_enrollment("usr-001", "ops1@saraswat"))
    code = pyotp.TOTP(challenge.secret).now()
    assert asyncio.run(svc.verify("usr-001", code)) is True


def test_verify_rejects_invalid_code():
    svc = _svc()
    asyncio.run(svc.begin_enrollment("usr-001", "ops1@saraswat"))
    assert asyncio.run(svc.verify("usr-001", "000000")) is False


def test_verify_without_enrollment_raises():
    svc = _svc()
    with pytest.raises(MFANotEnrolledError):
        asyncio.run(svc.verify("nobody", "123456"))


def test_confirm_without_enrollment_raises():
    svc = _svc()
    with pytest.raises(MFANotEnrolledError):
        asyncio.run(svc.confirm_enrollment("nobody", "123456"))


def test_reset_removes_secret_then_verify_raises():
    svc = _svc()
    asyncio.run(svc.begin_enrollment("usr-001", "ops1@saraswat"))
    asyncio.run(svc.reset("usr-001"))
    with pytest.raises(MFANotEnrolledError):
        asyncio.run(svc.verify("usr-001", "123456"))
