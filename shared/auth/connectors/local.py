"""LocalAuthConnector — argon2-hashed accounts in platform.local_auth_accounts."""
from __future__ import annotations

import time
from typing import Optional

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from pydantic import BaseModel, ConfigDict

from shared.auth.connectors.base import ASTRAIdentity, AuthConnector
from shared.auth.exceptions import AccountLockedError, AuthenticationError

log = structlog.get_logger()
_ph = PasswordHasher()

_MAX_ATTEMPTS = 5
_LOCK_DURATION_SECONDS = 1800   # 30 minutes


class LocalCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)
    username: str
    password: str


class LocalAuthConnector(AuthConnector):
    """Password auth backed by platform.local_auth_accounts (argon2id hashes).

    Intended only for SMBs/entities with no SAML IdP or AD directory.
    Passwords are never stored in plaintext — always argon2id.
    """

    def __init__(self, bank_id: str) -> None:
        self.bank_id = bank_id

    @property
    def connector_type(self) -> str:
        return "local"

    async def authenticate(self, credentials: LocalCredentials) -> ASTRAIdentity:
        account = await self._fetch_account(credentials.username)

        if account is None:
            # Constant-time-like: don't short-circuit immediately on unknown user
            log.warn("auth.local.unknown_user", bank_id=self.bank_id)
            raise AuthenticationError("invalid credentials")

        # Locked check — only if locked_until is set and still in the future
        locked_until: Optional[float] = account.get("locked_until")
        if locked_until and locked_until > time.time():
            raise AccountLockedError("account locked due to repeated failures")

        if not account.get("is_active", True):
            raise AuthenticationError("account inactive")

        try:
            _ph.verify(account["password_hash"], credentials.password)
        except VerifyMismatchError:
            new_failures = account.get("failed_attempts", 0) + 1
            if new_failures >= _MAX_ATTEMPTS:
                await self._lock_account(account["user_id"])
            else:
                await self._increment_failed_attempts(account["user_id"])
            log.warn("auth.local.wrong_password", bank_id=self.bank_id, attempts=new_failures)
            raise AuthenticationError("invalid credentials")

        await self._update_on_success(account["user_id"])
        log.info("auth.local.success", bank_id=self.bank_id, username=credentials.username)

        return ASTRAIdentity(
            user_id=account["user_id"],
            username=account["username"],
            display_name=account.get("display_name", account["username"]),
            entity_type=account["entity_type"],
            entity_id=account["entity_id"],
            bank_id=account["bank_id"],
            role=account["role"],
            clearing_zones=account.get("clearing_zones", []),
            connector_used="local",
        )

    async def health_check(self) -> bool:
        try:
            return await self._ping_db()
        except Exception:
            return False

    # --- DB hooks (replaced by AsyncMock in tests) ---

    async def _fetch_account(self, username: str) -> Optional[dict]:
        """Fetch account row from platform.local_auth_accounts. Returns None if not found."""
        raise NotImplementedError("inject real DB session via subclass or patch in tests")

    async def _update_on_success(self, user_id: str) -> None:
        """Reset failed_attempts=0, update last_login_at."""
        raise NotImplementedError

    async def _increment_failed_attempts(self, user_id: str) -> None:
        """Increment failed_attempts counter."""
        raise NotImplementedError

    async def _lock_account(self, user_id: str) -> None:
        """Set locked_until = now + _LOCK_DURATION_SECONDS."""
        raise NotImplementedError

    async def _ping_db(self) -> bool:
        """Return True if DB is reachable."""
        raise NotImplementedError
