"""LocalAuthConnector — argon2-hashed accounts in platform.local_auth_accounts."""
from __future__ import annotations

import time
from typing import Any, Optional

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

# Pre-computed hash used to equalize timing between unknown-user and wrong-password paths.
# Both paths must spend ~200ms in argon2 so response time cannot reveal whether a username exists.
_TIMING_DUMMY_HASH = _ph.hash("__astra_timing_dummy__")


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
            # Timing equalisation: run a real argon2 verify against a dummy hash so that
            # both "unknown user" and "wrong password" paths take ~200ms. Without this,
            # an attacker can enumerate valid usernames via response-time difference.
            try:
                _ph.verify(_TIMING_DUMMY_HASH, credentials.password)
            except Exception:
                pass  # always fails — we only care about spending the time
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


class YugabyteDBLocalAuthConnector(LocalAuthConnector):
    """Real platform.local_auth_accounts implementation, backed by asyncpg.

    AuthConnectorFactory._build_local() previously constructed the bare
    LocalAuthConnector base class with no hooks overridden — every hook
    raises NotImplementedError, so the first real login attempt against a
    "local"-configured bank would have crashed outright. This is that
    missing implementation, matching apps/api/routers/mcp_connections.py's
    YugabyteDBConnectionStore pattern (asyncpg pool, explicit column list —
    never SELECT * on a PII table per database.md).

    Includes email/phone (20260716_add_local_auth_contact_info.py) so
    locally-authenticated entities carry the contact info a notification-
    recipient resolver would need — this connector doesn't do that
    resolution itself, it just stops the data from being unavailable.
    """

    _COLS = (
        "user_id, bank_id, entity_type, entity_id, username, display_name, "
        "password_hash, role, clearing_zones, is_active, failed_attempts, "
        "locked_until, email, phone"
    )

    def __init__(self, bank_id: str, db_pool: Any) -> None:
        super().__init__(bank_id=bank_id)
        self._pool = db_pool

    async def _fetch_account(self, username: str) -> Optional[dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {self._COLS} FROM platform.local_auth_accounts "
                "WHERE bank_id = $1 AND username = $2",
                self.bank_id, username,
            )
        return dict(row) if row is not None else None

    async def _update_on_success(self, user_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE platform.local_auth_accounts "
                "SET failed_attempts = 0, locked_until = NULL, last_login_at = now() "
                "WHERE user_id = $1",
                user_id,
            )

    async def _increment_failed_attempts(self, user_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE platform.local_auth_accounts "
                "SET failed_attempts = failed_attempts + 1 "
                "WHERE user_id = $1",
                user_id,
            )

    async def _lock_account(self, user_id: str) -> None:
        locked_until = time.time() + _LOCK_DURATION_SECONDS
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE platform.local_auth_accounts SET locked_until = $2 "
                "WHERE user_id = $1",
                user_id, locked_until,
            )

    async def _ping_db(self) -> bool:
        async with self._pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
