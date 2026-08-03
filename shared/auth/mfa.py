"""TOTP MFA service (RFC 6238) — mandatory second factor for local accounts.

Policy (bank decision): TOTP is mandatory for every local account and there are
no backup codes. A lost authenticator is recovered by a bank_it_admin MFA reset
(see users.py), never by self-service codes.

TOTP secrets are held by an injected store — HashiCorp Vault in production
(secret/astra/{bank_id}/mfa/{user_id}), an in-memory fake in tests. The secret
never touches YugabyteDB; only a `totp_enrolled` flag lives in the account row.

The TOTP maths is hand-rolled (HMAC-SHA1, no runtime dependency) and is unit-
tested for byte-parity against pyotp. Codes are compared in constant time.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from typing import Optional, Protocol
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from shared.auth.exceptions import MFANotEnrolledError

_INTERVAL = 30
_DIGITS = 6
_SECRET_BYTES = 20  # 160 bits -> 32 base32 chars, no padding


class TOTPSecretStore(Protocol):
    """Async storage for per-user TOTP secrets (Vault-backed in production)."""

    async def put(self, user_id: str, secret: str) -> None: ...
    async def get(self, user_id: str) -> Optional[str]: ...
    async def delete(self, user_id: str) -> None: ...


class EnrollmentChallenge(BaseModel):
    model_config = ConfigDict(frozen=True)
    secret: str          # base32 — shown once, as QR + manual key
    otpauth_uri: str     # otpauth://totp/... for the authenticator app QR


def _b32_decode(secret_b32: str) -> bytes:
    padded = secret_b32.strip().upper()
    padded += "=" * (-len(padded) % 8)
    return base64.b32decode(padded)


class TOTPMFAService:
    def __init__(self, store: TOTPSecretStore, issuer: str = "ASTRA") -> None:
        self._store = store
        self._issuer = issuer

    # -- pure helpers ------------------------------------------------------- #

    @staticmethod
    def generate_secret() -> str:
        return base64.b32encode(os.urandom(_SECRET_BYTES)).decode("ascii").rstrip("=")

    @staticmethod
    def verify_code(
        secret_b32: str,
        code: str,
        window: int = 1,
        at_time: Optional[float] = None,
    ) -> bool:
        """Verify a TOTP code with +/- `window` step tolerance (clock skew).

        Returns False for any malformed input rather than raising — callers treat
        a bad code and a bad secret identically at the boundary.
        """
        if not code or not code.isdigit():
            return False
        try:
            secret_bytes = _b32_decode(secret_b32)
        except Exception:
            return False
        now = int(at_time if at_time is not None else time.time())
        step = now // _INTERVAL
        for delta in range(-window, window + 1):
            counter = struct.pack(">Q", step + delta)
            mac = hmac.new(secret_bytes, counter, hashlib.sha1).digest()
            offset = mac[-1] & 0x0F
            truncated = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
            expected = str(truncated % (10 ** _DIGITS)).zfill(_DIGITS)
            if hmac.compare_digest(expected, code):
                return True
        return False

    def provisioning_uri(self, secret: str, account_name: str) -> str:
        """Build the otpauth:// URI encoded into the enrolment QR code."""
        label = quote(f"{self._issuer}:{account_name}")
        params = f"secret={quote(secret)}&issuer={quote(self._issuer)}&digits={_DIGITS}&period={_INTERVAL}"
        return f"otpauth://totp/{label}?{params}"

    # -- store-backed lifecycle -------------------------------------------- #

    async def begin_enrollment(self, user_id: str, account_name: str) -> EnrollmentChallenge:
        """Generate + persist a new secret and return the QR challenge.

        The account's totp_enrolled flag stays False until confirm_enrollment
        succeeds — the router owns that flag in local_auth_accounts.
        """
        secret = self.generate_secret()
        await self._store.put(user_id, secret)
        return EnrollmentChallenge(
            secret=secret,
            otpauth_uri=self.provisioning_uri(secret, account_name),
        )

    async def confirm_enrollment(self, user_id: str, code: str) -> bool:
        secret = await self._store.get(user_id)
        if secret is None:
            raise MFANotEnrolledError(f"no pending TOTP secret for user '{user_id}'")
        return self.verify_code(secret, code)

    async def verify(self, user_id: str, code: str) -> bool:
        secret = await self._store.get(user_id)
        if secret is None:
            raise MFANotEnrolledError(f"user '{user_id}' has no TOTP enrolled")
        return self.verify_code(secret, code)

    async def reset(self, user_id: str) -> None:
        """Admin MFA reset — remove the secret so the user must re-enrol."""
        await self._store.delete(user_id)
