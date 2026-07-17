"""
Tests for VaultSecretBackend — extracts and unit-tests the Vault logic
that previously lived directly in ConfigService.

RED: run before the implementation exists to confirm failures.
"""
from unittest.mock import MagicMock, patch

import pytest

from shared.config.exceptions import VaultUnavailableError


class TestVaultBackendGet:
    @pytest.fixture
    def vault_backend(self):
        from shared.config.secret_backends.vault_backend import VaultSecretBackend
        backend = VaultSecretBackend()
        backend._bank_id = "test-bank"
        mock_vault = MagicMock()
        backend._vault = mock_vault
        return backend

    @pytest.mark.asyncio
    async def test_get_calls_kv_with_correct_path(self, vault_backend):
        vault_backend._vault.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"value": "super-secret"}}
        }
        result = await vault_backend.get("db.cts.password")
        assert result == "super-secret"
        vault_backend._vault.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="secret/astra/test-bank/db/cts/password",
            raise_on_deleted_version=True,
        )

    @pytest.mark.asyncio
    async def test_get_maps_key_to_vault_path(self, vault_backend):
        """Dots in key become slashes in vault path."""
        vault_backend._vault.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"value": "redis://secret:6379"}}
        }
        await vault_backend.get("redis.config.url")
        call_path = vault_backend._vault.secrets.kv.v2.read_secret_version.call_args[1]["path"]
        assert call_path == "secret/astra/test-bank/redis/config/url"

    @pytest.mark.asyncio
    async def test_get_raises_vault_unavailable_on_exception(self, vault_backend):
        vault_backend._vault.secrets.kv.v2.read_secret_version.side_effect = Exception("connection refused")
        with pytest.raises(VaultUnavailableError, match="db.cts.password"):
            await vault_backend.get("db.cts.password")

    @pytest.mark.asyncio
    async def test_get_never_returns_default_on_failure(self, vault_backend):
        """Critical: Vault error must raise, never silently default."""
        vault_backend._vault.secrets.kv.v2.read_secret_version.side_effect = Exception("timeout")
        with pytest.raises(VaultUnavailableError):
            await vault_backend.get("ngch.api_key")


class TestVaultBackendInitialise:
    @pytest.mark.asyncio
    async def test_initialise_raises_when_vault_addr_missing(self):
        from shared.config.secret_backends.vault_backend import VaultSecretBackend
        backend = VaultSecretBackend()
        with patch.dict("os.environ", {"BANK_ID": "test-bank"}, clear=True):
            with pytest.raises(RuntimeError, match="VAULT_ADDR"):
                await backend.initialise("test-bank")

    @pytest.mark.asyncio
    async def test_initialise_raises_when_vault_token_missing(self):
        from shared.config.secret_backends.vault_backend import VaultSecretBackend
        backend = VaultSecretBackend()
        with patch.dict("os.environ", {"VAULT_ADDR": "http://vault:8200"}, clear=True):
            with pytest.raises(RuntimeError, match="VAULT_ADDR"):
                await backend.initialise("test-bank")

    @pytest.mark.asyncio
    async def test_initialise_raises_when_not_authenticated(self):
        from shared.config.secret_backends.vault_backend import VaultSecretBackend
        backend = VaultSecretBackend()
        mock_vault = MagicMock()
        mock_vault.is_authenticated.return_value = False
        with patch.dict("os.environ", {
            "VAULT_ADDR": "http://vault:8200",
            "VAULT_TOKEN": "hvs.bad",
        }):
            with patch("shared.config.secret_backends.vault_backend.hvac.Client", return_value=mock_vault):
                with pytest.raises(VaultUnavailableError):
                    await backend.initialise("test-bank")

    @pytest.mark.asyncio
    async def test_initialise_succeeds_when_authenticated(self):
        from shared.config.secret_backends.vault_backend import VaultSecretBackend
        backend = VaultSecretBackend()
        mock_vault = MagicMock()
        mock_vault.is_authenticated.return_value = True
        with patch.dict("os.environ", {
            "VAULT_ADDR": "http://vault:8200",
            "VAULT_TOKEN": "hvs.good",
        }):
            with patch("shared.config.secret_backends.vault_backend.hvac.Client", return_value=mock_vault):
                await backend.initialise("test-bank")
        assert backend._bank_id == "test-bank"
        assert backend._vault is mock_vault
