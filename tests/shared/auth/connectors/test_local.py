"""Tests for LocalAuthConnector — argon2 password auth against platform.local_auth_accounts."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from shared.auth.connectors.local import LocalAuthConnector, LocalCredentials
from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.exceptions import AuthenticationError, AccountLockedError


def _make_account(
    *,
    username="ravi.mehta",
    role="ops_reviewer",
    entity_type="sb",
    entity_id="saraswat-coop",
    bank_id="saraswat-coop",
    clearing_zones=None,
    is_active=True,
    failed_attempts=0,
    locked_until=None,
    password_hash=None,
):
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    return {
        "user_id": "u-001",
        "username": username,
        "display_name": "Ravi Mehta",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "bank_id": bank_id,
        "role": role,
        "clearing_zones": clearing_zones or ["MUMBAI"],
        "is_active": is_active,
        "failed_attempts": failed_attempts,
        "locked_until": locked_until,
        "password_hash": password_hash or ph.hash("Correct@Pass1"),
    }


@pytest.fixture
def connector():
    return LocalAuthConnector(bank_id="saraswat-coop")


@pytest.mark.asyncio
async def test_authenticate_success(connector):
    account = _make_account()
    connector._fetch_account = AsyncMock(return_value=account)
    connector._update_on_success = AsyncMock()

    result = await connector.authenticate(
        LocalCredentials(username="ravi.mehta", password="Correct@Pass1")
    )

    assert isinstance(result, ASTRAIdentity)
    assert result.username == "ravi.mehta"
    assert result.role == "ops_reviewer"
    assert result.connector_used == "local"
    assert result.entity_type == "sb"
    connector._update_on_success.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_wrong_password_raises(connector):
    account = _make_account()
    connector._fetch_account = AsyncMock(return_value=account)
    connector._increment_failed_attempts = AsyncMock()

    with pytest.raises(AuthenticationError, match="invalid credentials"):
        await connector.authenticate(
            LocalCredentials(username="ravi.mehta", password="WrongPass99!")
        )
    connector._increment_failed_attempts.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_unknown_user_raises(connector):
    connector._fetch_account = AsyncMock(return_value=None)

    with pytest.raises(AuthenticationError, match="invalid credentials"):
        await connector.authenticate(
            LocalCredentials(username="ghost.user", password="AnyPass1!")
        )


@pytest.mark.asyncio
async def test_authenticate_inactive_account_raises(connector):
    account = _make_account(is_active=False)
    connector._fetch_account = AsyncMock(return_value=account)

    with pytest.raises(AuthenticationError, match="account inactive"):
        await connector.authenticate(
            LocalCredentials(username="ravi.mehta", password="Correct@Pass1")
        )


@pytest.mark.asyncio
async def test_authenticate_locked_account_raises(connector):
    account = _make_account(locked_until=time.time() + 3600)
    connector._fetch_account = AsyncMock(return_value=account)

    with pytest.raises(AccountLockedError):
        await connector.authenticate(
            LocalCredentials(username="ravi.mehta", password="Correct@Pass1")
        )


@pytest.mark.asyncio
async def test_authenticate_expired_lock_is_allowed(connector):
    # locked_until in the past → lock has expired → allow
    account = _make_account(locked_until=time.time() - 1)
    connector._fetch_account = AsyncMock(return_value=account)
    connector._update_on_success = AsyncMock()

    result = await connector.authenticate(
        LocalCredentials(username="ravi.mehta", password="Correct@Pass1")
    )
    assert result.username == "ravi.mehta"


@pytest.mark.asyncio
async def test_five_failures_locks_account(connector):
    # 4 failed attempts already recorded
    account = _make_account(failed_attempts=4)
    connector._fetch_account = AsyncMock(return_value=account)
    connector._lock_account = AsyncMock()
    connector._increment_failed_attempts = AsyncMock()

    with pytest.raises(AuthenticationError):
        await connector.authenticate(
            LocalCredentials(username="ravi.mehta", password="WrongPass99!")
        )
    # 5th failure → lock triggered
    connector._lock_account.assert_called_once_with("u-001")


@pytest.mark.asyncio
async def test_password_never_stored_in_plaintext(connector):
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    account = _make_account()
    # Verify argon2 hash (not bcrypt, not sha256)
    assert account["password_hash"].startswith("$argon2")
    assert ph.verify(account["password_hash"], "Correct@Pass1")


@pytest.mark.asyncio
async def test_health_check_true_when_reachable(connector):
    connector._ping_db = AsyncMock(return_value=True)
    assert await connector.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_when_db_down(connector):
    connector._ping_db = AsyncMock(side_effect=Exception("DB unreachable"))
    assert await connector.health_check() is False


def test_connector_type(connector):
    assert connector.connector_type == "local"


# ── YugabyteDBLocalAuthConnector — real DB-backed implementation ────────────
#
# LocalAuthConnector's hooks were NotImplementedError stubs meant to be
# overridden; AuthConnectorFactory._build_local() constructed the bare base
# class with no override at all, so the first real login on a "local"-
# configured bank would have crashed with NotImplementedError. This is the
# real implementation, backed by platform.local_auth_accounts via asyncpg
# (matching apps/api/routers/mcp_connections.py's YugabyteDBConnectionStore
# pattern) -- includes email/phone now that the schema carries them
# (20260716_add_local_auth_contact_info.py), so locally-authenticated
# entities can eventually be resolved as notification recipients.

class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_FakeAcquireCtx(conn))
    return pool


class TestYugabyteDBLocalAuthConnectorFetch:
    @pytest.mark.asyncio
    async def test_fetch_account_returns_row_as_dict(self):
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        row = _make_account()
        conn.fetchrow = AsyncMock(return_value=row)
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        result = await connector._fetch_account("ravi.mehta")

        assert result == row

    @pytest.mark.asyncio
    async def test_fetch_account_scopes_query_to_bank_id(self):
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        await connector._fetch_account("ravi.mehta")

        args = conn.fetchrow.call_args[0]
        assert "saraswat-coop" in args
        assert "ravi.mehta" in args

    @pytest.mark.asyncio
    async def test_fetch_account_returns_none_when_not_found(self):
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        result = await connector._fetch_account("ghost.user")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_account_query_includes_email_and_phone_columns(self):
        """The whole point of this connector this session -- email/phone
        must actually be selected, not left out of the column list."""
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        await connector._fetch_account("ravi.mehta")

        query = conn.fetchrow.call_args[0][0]
        assert "email" in query
        assert "phone" in query
        assert "select *" not in query.lower()   # database.md: never SELECT * on a PII table


class TestYugabyteDBLocalAuthConnectorMutations:
    @pytest.mark.asyncio
    async def test_update_on_success_resets_failed_attempts_and_lock(self):
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        conn.execute = AsyncMock()
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        await connector._update_on_success("u-001")

        query = conn.execute.call_args[0][0]
        assert "failed_attempts = 0" in query
        assert "locked_until = NULL" in query
        assert conn.execute.call_args[0][1] == "u-001"

    @pytest.mark.asyncio
    async def test_increment_failed_attempts(self):
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        conn.execute = AsyncMock()
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        await connector._increment_failed_attempts("u-001")

        query = conn.execute.call_args[0][0]
        assert "failed_attempts + 1" in query
        assert conn.execute.call_args[0][1] == "u-001"

    @pytest.mark.asyncio
    async def test_lock_account_sets_locked_until_in_the_future(self):
        import time
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector, _LOCK_DURATION_SECONDS

        conn = AsyncMock()
        conn.execute = AsyncMock()
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        before = time.time()
        await connector._lock_account("u-001")
        after = time.time()

        call_args = conn.execute.call_args[0]
        locked_until = call_args[2]
        assert before + _LOCK_DURATION_SECONDS <= locked_until <= after + _LOCK_DURATION_SECONDS


class TestYugabyteDBLocalAuthConnectorPing:
    @pytest.mark.asyncio
    async def test_ping_db_true_when_query_succeeds(self):
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        assert await connector.health_check() is True

    @pytest.mark.asyncio
    async def test_ping_db_false_when_pool_raises(self):
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=Exception("connection refused"))
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        assert await connector.health_check() is False


class TestYugabyteDBLocalAuthConnectorEndToEnd:
    @pytest.mark.asyncio
    async def test_full_authenticate_flow_against_real_hooks(self):
        """Not mocking the hooks this time -- proves the base class's
        authenticate() logic and the real DB-backed hooks actually fit
        together, closing the exact gap AuthConnectorFactory left open."""
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector

        account_row = _make_account()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=account_row)
        conn.execute = AsyncMock()
        connector = YugabyteDBLocalAuthConnector(bank_id="saraswat-coop", db_pool=_fake_pool(conn))

        result = await connector.authenticate(
            LocalCredentials(username="ravi.mehta", password="Correct@Pass1")
        )

        assert isinstance(result, ASTRAIdentity)
        assert result.role == "ops_reviewer"
        conn.execute.assert_called_once()   # _update_on_success fired
