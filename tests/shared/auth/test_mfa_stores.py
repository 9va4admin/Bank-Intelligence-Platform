"""TDD for shared.auth.mfa_stores — InMemoryTOTPSecretStore and VaultTOTPSecretStore."""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# InMemoryTOTPSecretStore
# ---------------------------------------------------------------------------

class TestInMemoryTOTPSecretStore:
    @pytest.mark.asyncio
    async def test_put_then_get_returns_secret(self):
        from shared.auth.mfa_stores import InMemoryTOTPSecretStore
        store = InMemoryTOTPSecretStore()
        await store.put("user-1", "SECRETBASE32")
        assert await store.get("user-1") == "SECRETBASE32"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        from shared.auth.mfa_stores import InMemoryTOTPSecretStore
        store = InMemoryTOTPSecretStore()
        assert await store.get("nobody") is None

    @pytest.mark.asyncio
    async def test_delete_removes_secret(self):
        from shared.auth.mfa_stores import InMemoryTOTPSecretStore
        store = InMemoryTOTPSecretStore()
        await store.put("user-1", "SECRET")
        await store.delete("user-1")
        assert await store.get("user-1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_raise(self):
        from shared.auth.mfa_stores import InMemoryTOTPSecretStore
        store = InMemoryTOTPSecretStore()
        await store.delete("never-existed")  # must not raise

    @pytest.mark.asyncio
    async def test_put_overwrites_existing(self):
        from shared.auth.mfa_stores import InMemoryTOTPSecretStore
        store = InMemoryTOTPSecretStore()
        await store.put("user-1", "OLD")
        await store.put("user-1", "NEW")
        assert await store.get("user-1") == "NEW"

    @pytest.mark.asyncio
    async def test_stores_multiple_users_independently(self):
        from shared.auth.mfa_stores import InMemoryTOTPSecretStore
        store = InMemoryTOTPSecretStore()
        await store.put("a", "SA")
        await store.put("b", "SB")
        assert await store.get("a") == "SA"
        assert await store.get("b") == "SB"


# ---------------------------------------------------------------------------
# VaultTOTPSecretStore
# ---------------------------------------------------------------------------

def _make_vault_client(get_response=None, raise_on_get=None):
    """Return a mock hvac.Client with KV v2 wired."""
    kv = MagicMock()
    if raise_on_get:
        kv.read_secret_version.side_effect = raise_on_get
    else:
        kv.read_secret_version.return_value = {
            "data": {"data": {"value": get_response or "SECRET"}}
        }
    client = MagicMock()
    client.secrets.kv.v2 = kv
    return client


class TestVaultTOTPSecretStore:
    @pytest.mark.asyncio
    async def test_get_returns_vault_value(self):
        from shared.auth.mfa_stores import VaultTOTPSecretStore
        store = VaultTOTPSecretStore.__new__(VaultTOTPSecretStore)
        store._bank_id = "test-bank"
        store._vault = _make_vault_client(get_response="TOTP_SECRET")
        result = await store.get("user-1")
        assert result == "TOTP_SECRET"

    @pytest.mark.asyncio
    async def test_get_returns_none_on_vault_error(self):
        from shared.auth.mfa_stores import VaultTOTPSecretStore
        store = VaultTOTPSecretStore.__new__(VaultTOTPSecretStore)
        store._bank_id = "test-bank"
        store._vault = _make_vault_client(raise_on_get=Exception("not found"))
        result = await store.get("user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_put_calls_vault_create_or_update(self):
        from shared.auth.mfa_stores import VaultTOTPSecretStore
        store = VaultTOTPSecretStore.__new__(VaultTOTPSecretStore)
        store._bank_id = "test-bank"
        vault_client = _make_vault_client()
        store._vault = vault_client
        await store.put("user-1", "MY_SECRET")
        vault_client.secrets.kv.v2.create_or_update_secret.assert_called_once()
        call_kwargs = vault_client.secrets.kv.v2.create_or_update_secret.call_args
        assert call_kwargs.kwargs["secret"] == {"value": "MY_SECRET"}

    @pytest.mark.asyncio
    async def test_delete_calls_vault_delete_latest(self):
        from shared.auth.mfa_stores import VaultTOTPSecretStore
        store = VaultTOTPSecretStore.__new__(VaultTOTPSecretStore)
        store._bank_id = "test-bank"
        vault_client = _make_vault_client()
        store._vault = vault_client
        await store.delete("user-1")
        vault_client.secrets.kv.v2.delete_latest_version_of_secret.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_does_not_raise_on_vault_error(self):
        from shared.auth.mfa_stores import VaultTOTPSecretStore
        store = VaultTOTPSecretStore.__new__(VaultTOTPSecretStore)
        store._bank_id = "test-bank"
        vault_client = _make_vault_client()
        vault_client.secrets.kv.v2.delete_latest_version_of_secret.side_effect = Exception("gone")
        store._vault = vault_client
        await store.delete("user-1")  # must not raise

    @pytest.mark.asyncio
    async def test_get_uses_correct_path(self):
        from shared.auth.mfa_stores import VaultTOTPSecretStore
        store = VaultTOTPSecretStore.__new__(VaultTOTPSecretStore)
        store._bank_id = "saraswat-coop"
        vault_client = _make_vault_client(get_response="S")
        store._vault = vault_client
        await store.get("usr-42")
        call_kwargs = vault_client.secrets.kv.v2.read_secret_version.call_args
        path_arg = call_kwargs.kwargs.get("path") or call_kwargs.args[0]
        assert "saraswat-coop" in path_arg
        assert "usr-42" in path_arg

    def test_initialise_raises_without_vault_env(self):
        """VaultTOTPSecretStore raises RuntimeError when VAULT_ADDR/TOKEN absent."""
        import os
        from shared.auth.mfa_stores import VaultTOTPSecretStore
        store = VaultTOTPSecretStore("test-bank")
        # clear env so ensure_client raises
        with patch.dict(os.environ, {}, clear=True):
            # _ensure_client() is called lazily; raise on first call
            with pytest.raises(RuntimeError, match="VAULT_ADDR"):
                store._ensure_client()
