"""
Tests for ConfigService — covers all 5 layers, cache behaviour,
error paths, and the vault-miss-never-defaults rule.
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from shared.config.config_service import ConfigService
from shared.config.exceptions import (
    ConfigKeyNotFoundError,
    OPAUnavailableError,
    VaultUnavailableError,
)


@pytest.fixture
def svc() -> ConfigService:
    """Return a ConfigService instance wired with mocks, bypassing initialise()."""
    service = ConfigService()
    service._bank_id = "test-bank"
    service._opa_url = "http://opa:8181"
    service._ready = True

    # Mock Vault
    vault_mock = MagicMock()
    vault_mock.is_authenticated.return_value = True
    service._vault = vault_mock

    # Mock Redis
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.setex = AsyncMock()
    service._redis = redis_mock

    # Mock DB pool
    conn_mock = AsyncMock()
    conn_mock.fetchrow = AsyncMock(return_value=None)
    pool_mock = MagicMock()
    pool_mock.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn_mock), __aexit__=AsyncMock()))
    service._db_pool = pool_mock

    return service


# ------------------------------------------------------------------
# Layer 5 — Vault
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_secret_calls_vault(svc: ConfigService):
    svc._vault.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "super-secret-password"}}
    }

    result = await svc.get_secret("db.cts.password")

    assert result == "super-secret-password"
    svc._vault.secrets.kv.v2.read_secret_version.assert_called_once_with(
        path="secret/astra/test-bank/db/cts/password",
        raise_on_deleted_version=True,
    )


@pytest.mark.asyncio
async def test_get_secret_uses_cache_within_ttl(svc: ConfigService):
    svc._vault.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "cached-value"}}
    }

    await svc.get_secret("db.cts.password")
    await svc.get_secret("db.cts.password")

    # Vault called only once — second call served from in-process cache
    assert svc._vault.secrets.kv.v2.read_secret_version.call_count == 1


@pytest.mark.asyncio
async def test_get_secret_re_fetches_after_ttl(svc: ConfigService):
    svc._vault.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "v1"}}
    }
    await svc.get_secret("some.key")

    # Artificially expire the cache entry
    svc._vault_cache["some.key"] = ("v1", time.monotonic() - 35)

    svc._vault.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "v2"}}
    }
    result = await svc.get_secret("some.key")

    assert result == "v2"
    assert svc._vault.secrets.kv.v2.read_secret_version.call_count == 2


@pytest.mark.asyncio
async def test_get_secret_raises_on_vault_error(svc: ConfigService):
    svc._vault.secrets.kv.v2.read_secret_version.side_effect = Exception("connection refused")

    with pytest.raises(VaultUnavailableError, match="db.cts.password"):
        await svc.get_secret("db.cts.password")


@pytest.mark.asyncio
async def test_get_secret_never_returns_default_on_failure(svc: ConfigService):
    """Critical: vault miss must raise, never silently return a fallback."""
    svc._vault.secrets.kv.v2.read_secret_version.side_effect = Exception("timeout")

    with pytest.raises(VaultUnavailableError):
        await svc.get_secret("ngch.api_key")
    # If this reaches here without raising, the test fails as expected


# ------------------------------------------------------------------
# Layer 3 — YugabyteDB config (Redis-cached)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_returns_redis_cached_value(svc: ConfigService):
    svc._redis.get = AsyncMock(return_value=json.dumps(0.72))

    result = await svc.get("cts.human_review_fraud_threshold")

    assert result == 0.72
    # DB pool never touched — served from Redis
    svc._db_pool.acquire().__aenter__.assert_not_called()


@pytest.mark.asyncio
async def test_get_fetches_from_db_on_cache_miss(svc: ConfigService):
    svc._redis.get = AsyncMock(return_value=None)

    conn = svc._db_pool.acquire().__aenter__.return_value
    conn.fetchrow = AsyncMock(return_value={"value": "0.92", "value_type": "float"})

    result = await svc.get("cts.stp_auto_confirm_threshold")

    assert result == 0.92
    svc._redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_get_raises_for_missing_key(svc: ConfigService):
    svc._redis.get = AsyncMock(return_value=None)
    conn = svc._db_pool.acquire().__aenter__.return_value
    conn.fetchrow = AsyncMock(return_value=None)

    with pytest.raises(ConfigKeyNotFoundError, match="cts.nonexistent"):
        await svc.get("cts.nonexistent")


@pytest.mark.asyncio
async def test_get_deserialises_int(svc: ConfigService):
    svc._redis.get = AsyncMock(return_value=None)
    conn = svc._db_pool.acquire().__aenter__.return_value
    conn.fetchrow = AsyncMock(return_value={"value": "180", "value_type": "int"})

    result = await svc.get("cts.iet_minutes")
    assert result == 180
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_get_deserialises_bool(svc: ConfigService):
    svc._redis.get = AsyncMock(return_value=None)
    conn = svc._db_pool.acquire().__aenter__.return_value
    conn.fetchrow = AsyncMock(return_value={"value": "true", "value_type": "bool"})

    result = await svc.get("feature.dual_approval_enabled")
    assert result is True


# ------------------------------------------------------------------
# Layer 1+2 — Helm env vars
# ------------------------------------------------------------------

def test_get_platform_reads_env(svc: ConfigService):
    with patch.dict("os.environ", {"PLATFORM_VERSION": "1.3.2"}):
        result = svc.get_platform("platform.version")
    assert result == "1.3.2"


def test_get_platform_raises_if_env_missing(svc: ConfigService):
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ConfigKeyNotFoundError, match="MODULE_CTS_ENABLED"):
            svc.get_platform("module.cts.enabled")


# ------------------------------------------------------------------
# Layer 4 — OPA
# ------------------------------------------------------------------

def _opa_patch(return_value=None, side_effect=None):
    """Context manager: patches httpx.AsyncClient inside config_service module."""
    mock_response = MagicMock()
    mock_client = AsyncMock()
    if side_effect:
        mock_client.post = AsyncMock(side_effect=side_effect)
    else:
        mock_response.json.return_value = return_value
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)

    return patch("httpx.AsyncClient", return_value=cm), mock_client


@pytest.mark.asyncio
async def test_evaluate_policy_calls_opa(svc: ConfigService):
    svc._opa_cache.clear()
    patcher, mock_client = _opa_patch(
        return_value={"result": {"requires_human_review": True, "reason": "VAULT_MISS"}}
    )
    with patcher:
        result = await svc.evaluate_policy("astra/cts/routing", {"bank_id": "test-bank"})

    assert result["requires_human_review"] is True
    assert result["reason"] == "VAULT_MISS"


@pytest.mark.asyncio
async def test_evaluate_policy_raises_on_opa_unreachable(svc: ConfigService):
    svc._opa_cache.clear()
    patcher, _ = _opa_patch(side_effect=Exception("connection refused"))
    with patcher:
        with pytest.raises(OPAUnavailableError):
            await svc.evaluate_policy("astra/cts/routing", {"bank_id": "test-bank-x"})


@pytest.mark.asyncio
async def test_evaluate_policy_uses_cache(svc: ConfigService):
    svc._opa_cache.clear()
    patcher, mock_client = _opa_patch(return_value={"result": {"decision": "STP"}})
    with patcher:
        input_data = {"bank_id": "test-bank", "score": 0.95}
        await svc.evaluate_policy("astra/cts/routing", input_data)
        await svc.evaluate_policy("astra/cts/routing", input_data)

    # OPA called only once — second call from 1-second cache
    assert mock_client.post.call_count == 1


# ------------------------------------------------------------------
# Layer 5 — User preferences
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_preference_returns_none_if_not_set(svc: ConfigService):
    conn = svc._db_pool.acquire().__aenter__.return_value
    conn.fetchrow = AsyncMock(return_value=None)

    result = await svc.get_user_preference("user-123", "dashboard_layout")
    assert result is None


@pytest.mark.asyncio
async def test_get_user_preference_returns_deserialised_json(svc: ConfigService):
    conn = svc._db_pool.acquire().__aenter__.return_value
    conn.fetchrow = AsyncMock(return_value={"value": '{"panels": ["queue", "metrics"]}'})

    result = await svc.get_user_preference("user-123", "dashboard_layout")
    assert result == {"panels": ["queue", "metrics"]}


# ------------------------------------------------------------------
# Guard: assert_ready
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_raises_if_not_initialised():
    uninitialised = ConfigService()
    with pytest.raises(RuntimeError, match="initialise()"):
        await uninitialised.get_secret("any.key")
