"""
Tests for EnvSecretBackend — reads secrets from ASTRA_SECRET_* env vars.

RED: run before the implementation exists to confirm failures.
"""
import pytest
from unittest.mock import patch

from shared.config.exceptions import VaultUnavailableError


class TestEnvBackendGet:
    @pytest.mark.asyncio
    async def test_get_reads_env_var(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {"ASTRA_SECRET_IMMUDB_USERNAME": "immudb"}):
            result = await backend.get("immudb.username")
        assert result == "immudb"

    @pytest.mark.asyncio
    async def test_get_maps_dots_to_underscores(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {"ASTRA_SECRET_REDIS_CTS_URL": "redis://localhost:6379"}):
            result = await backend.get("redis.cts.url")
        assert result == "redis://localhost:6379"

    @pytest.mark.asyncio
    async def test_get_raises_when_env_var_missing(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(VaultUnavailableError, match="ASTRA_SECRET_NGCH_API_KEY"):
                await backend.get("ngch.api_key")

    @pytest.mark.asyncio
    async def test_get_never_returns_default_on_missing(self):
        """Critical: same contract as VaultSecretBackend — no silent default."""
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(VaultUnavailableError):
                await backend.get("any.key")

    @pytest.mark.asyncio
    async def test_get_key_uppercased(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        # Key with mixed dots → uppercase env var
        with patch.dict("os.environ", {"ASTRA_SECRET_DB_CTS_PASSWORD": "s3cret"}):
            result = await backend.get("db.cts.password")
        assert result == "s3cret"


class TestEnvBackendInitialise:
    @pytest.mark.asyncio
    async def test_initialise_succeeds_in_development(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {"ASTRA_ENV": "development"}):
            await backend.initialise("test-bank")  # must not raise

    @pytest.mark.asyncio
    async def test_initialise_succeeds_when_astra_env_not_set(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {}, clear=True):
            await backend.initialise("test-bank")  # must not raise

    @pytest.mark.asyncio
    async def test_initialise_raises_in_production_by_default(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {"ASTRA_ENV": "production"}, clear=True):
            with pytest.raises(RuntimeError, match="ASTRA_SECRETS_BACKEND=env"):
                await backend.initialise("prod-bank")

    @pytest.mark.asyncio
    async def test_initialise_succeeds_in_production_with_explicit_override(self):
        from shared.config.secret_backends.env_backend import EnvSecretBackend
        backend = EnvSecretBackend()
        with patch.dict("os.environ", {
            "ASTRA_ENV": "production",
            "ASTRA_ALLOW_ENV_SECRETS": "true",
        }):
            await backend.initialise("prod-bank")  # override accepted
