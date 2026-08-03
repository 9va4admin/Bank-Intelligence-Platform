"""
Real YugabyteDB integration tests for YugabyteDBLocalAuthConnector
(shared/auth/connectors/local.py) — against astra-it-yugabyte
(infra/docker-compose.integration.yml) with the real Alembic-migrated
platform.local_auth_accounts table, not a mock pool.

Directly answers the user's explicit request this session: "we should have
this information in table and it should read real table" — this is that
verification. Requires infra/migrations/platform/versions/20260705_add_local_auth_accounts.py
and .../20260716_add_local_auth_contact_info.py to have been run first:

    PLATFORM_DB_URL="postgresql+asyncpg://yugabyte:yugabyte@localhost:5443/astra" \\
        python -m alembic -c infra/migrations/platform/alembic.ini upgrade head

Both migrations were themselves orphaned/broken before this session (never
in alembic's version_locations path, and alembic.ini's %(DB_USER)s template
crashed ConfigParser's own interpolation before a connection was ever
attempted) — fixed alongside writing this test.
"""
import time
import uuid

import pytest
import pytest_asyncio
from argon2 import PasswordHasher

from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.connectors.local import LocalCredentials, YugabyteDBLocalAuthConnector
from shared.auth.exceptions import AccountLockedError, AuthenticationError

pytestmark = pytest.mark.integration

_ph = PasswordHasher()


@pytest.fixture
def bank_id() -> str:
    return f"it-bank-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def seeded_account(yugabyte_pool, bank_id):
    """Insert one real, active local_auth_accounts row with a known password."""
    user_id = f"it-user-{uuid.uuid4().hex[:8]}"
    plaintext_password = "CorrectHorseBatteryStaple!"
    password_hash = _ph.hash(plaintext_password)

    async with yugabyte_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO platform.local_auth_accounts
                (user_id, bank_id, entity_type, entity_id, username, display_name,
                 password_hash, role, clearing_zones, is_active, failed_attempts,
                 locked_until, email, phone)
            VALUES ($1, $2, 'smb', 'smb-pune-ucb', $3, 'IT Test User',
                    $4, 'smb_admin', ARRAY['MUMBAI']::text[], true, 0,
                    NULL, $5, '+919800000000')
            """,
            user_id, bank_id, "it.testuser", password_hash, "ituser@example-bank.test",
        )
    yield {"user_id": user_id, "username": "it.testuser", "password": plaintext_password, "bank_id": bank_id}

    async with yugabyte_pool.acquire() as conn:
        await conn.execute("DELETE FROM platform.local_auth_accounts WHERE user_id = $1", user_id)


@pytest.fixture
def connector(yugabyte_pool, bank_id) -> YugabyteDBLocalAuthConnector:
    return YugabyteDBLocalAuthConnector(bank_id=bank_id, db_pool=yugabyte_pool)


class TestAuthenticateAgainstRealTable:
    @pytest.mark.asyncio
    async def test_correct_password_returns_astra_identity(self, connector, seeded_account):
        identity = await connector.authenticate(
            LocalCredentials(username=seeded_account["username"], password=seeded_account["password"])
        )
        assert isinstance(identity, ASTRAIdentity)
        assert identity.user_id == seeded_account["user_id"]
        assert identity.entity_type == "smb"
        assert identity.entity_id == "smb-pune-ucb"
        assert identity.role == "smb_admin"
        assert identity.clearing_zones == ["MUMBAI"]
        assert identity.connector_used == "local"

    @pytest.mark.asyncio
    async def test_wrong_password_raises_and_increments_failed_attempts(self, connector, seeded_account, yugabyte_pool):
        with pytest.raises(AuthenticationError):
            await connector.authenticate(
                LocalCredentials(username=seeded_account["username"], password="wrong-password")
            )

        async with yugabyte_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT failed_attempts FROM platform.local_auth_accounts WHERE user_id = $1",
                seeded_account["user_id"],
            )
        assert row["failed_attempts"] == 1

    @pytest.mark.asyncio
    async def test_unknown_username_raises_authentication_error(self, connector, bank_id):
        with pytest.raises(AuthenticationError):
            await connector.authenticate(
                LocalCredentials(username="no-such-user", password="anything")
            )

    @pytest.mark.asyncio
    async def test_successful_login_resets_failed_attempts(self, connector, seeded_account, yugabyte_pool):
        # Fail twice, then succeed -- failed_attempts must reset to 0.
        for _ in range(2):
            with pytest.raises(AuthenticationError):
                await connector.authenticate(
                    LocalCredentials(username=seeded_account["username"], password="wrong")
                )

        await connector.authenticate(
            LocalCredentials(username=seeded_account["username"], password=seeded_account["password"])
        )

        async with yugabyte_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT failed_attempts, last_login_at FROM platform.local_auth_accounts WHERE user_id = $1",
                seeded_account["user_id"],
            )
        assert row["failed_attempts"] == 0
        assert row["last_login_at"] is not None

    @pytest.mark.asyncio
    async def test_fifth_consecutive_failure_locks_the_account(self, connector, seeded_account, yugabyte_pool):
        for _ in range(5):
            with pytest.raises((AuthenticationError, AccountLockedError)):
                await connector.authenticate(
                    LocalCredentials(username=seeded_account["username"], password="wrong")
                )

        async with yugabyte_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT failed_attempts, locked_until FROM platform.local_auth_accounts WHERE user_id = $1",
                seeded_account["user_id"],
            )
        assert row["locked_until"] is not None
        assert row["locked_until"] > time.time()

        # Correct password no longer works while locked.
        with pytest.raises(AccountLockedError):
            await connector.authenticate(
                LocalCredentials(username=seeded_account["username"], password=seeded_account["password"])
            )

    @pytest.mark.asyncio
    async def test_inactive_account_rejected_even_with_correct_password(self, connector, seeded_account, yugabyte_pool):
        async with yugabyte_pool.acquire() as conn:
            await conn.execute(
                "UPDATE platform.local_auth_accounts SET is_active = false WHERE user_id = $1",
                seeded_account["user_id"],
            )

        with pytest.raises(AuthenticationError):
            await connector.authenticate(
                LocalCredentials(username=seeded_account["username"], password=seeded_account["password"])
            )

    @pytest.mark.asyncio
    async def test_bank_id_scopes_username_lookup(self, connector, seeded_account, yugabyte_pool):
        """A username that exists for a different bank_id must not authenticate here --
        username uniqueness is per-bank (uq_local_auth_accounts_bank_username), and
        _fetch_account's WHERE clause must filter on both."""
        other_bank_connector = YugabyteDBLocalAuthConnector(bank_id="a-totally-different-bank", db_pool=yugabyte_pool)
        with pytest.raises(AuthenticationError):
            await other_bank_connector.authenticate(
                LocalCredentials(username=seeded_account["username"], password=seeded_account["password"])
            )

    @pytest.mark.asyncio
    async def test_email_and_phone_are_readable_from_real_table(self, yugabyte_pool, seeded_account):
        """Regression guard for the 20260716 migration -- email/phone columns must
        actually exist and round-trip, not just be present in the connector's SELECT list."""
        async with yugabyte_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, phone FROM platform.local_auth_accounts WHERE user_id = $1",
                seeded_account["user_id"],
            )
        assert row["email"] == "ituser@example-bank.test"
        assert row["phone"] == "+919800000000"


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_true_when_db_reachable(self, connector):
        assert await connector.health_check() is True
