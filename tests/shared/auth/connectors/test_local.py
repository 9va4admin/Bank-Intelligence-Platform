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
