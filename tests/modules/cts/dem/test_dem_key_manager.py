"""
Tests for DEM CCH Key Manager — NPCI DEM Spec v20 §2.b (Reqtype=W).

The key manager fetches CCH's RSA public key every 4 hours via an HTTPS POST
(Reqtype=W) and caches it. Callers use get_cch_key() which returns a CCHKeyBundle.

Key exchange response format (DEM spec):
  StatusCode=00
  StatusDesc=Success
  TransactionId=<txn_id>
  Modulus=<hex_string>          ← RSA public key modulus N
  Exponent=<hex_string>         ← RSA public exponent e
  ValidFrom=01/01/2026
  ValidTo=31/12/2026
  DEM_keyaliasname=CCH-ALIAS-01

RED phase: all tests fail before key_manager.py exists.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.cts.dem.models import CCHKeyBundle, DEMConfig, DEMEncryptionAlgo


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _dem_config() -> DEMConfig:
    return DEMConfig(
        bank_id="saraswat-coop",
        bank_routing_no="000550050",
        dem_id="DEM-TEST-001",
        hsm_key_alias="TEST-HSM-KEY",
        cch_https_url="https://cch.npci.org.in/CCHBank/api/ftp",
        cch_sftp_primary="10.0.0.1",
        cch_sftp_secondary="10.0.0.2",
        sftp_username="SFTP-TEST",
        sftp_local_backup_dir="/tmp/dem_backup",
        key_refresh_interval_hours=4,
    )


def _mock_rsa_key_pair():
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    return priv, priv.public_key()


def _reqtype_w_response(pub_key, valid_from="01/01/2026", valid_to="31/12/2026",
                         alias="CCH-ALIAS-01", status="00") -> str:
    """Build a mock Reqtype=W HTTPS response body (key=value format per DEM spec)."""
    nums = pub_key.public_numbers()
    mod_hex = hex(nums.n)[2:].upper()
    exp_hex = hex(nums.e)[2:].upper()
    return (
        f"StatusCode={status}\n"
        f"StatusDesc=Success\n"
        f"TransactionId=TXN-TEST-12345\n"
        f"Modulus={mod_hex}\n"
        f"Exponent={exp_hex}\n"
        f"ValidFrom={valid_from}\n"
        f"ValidTo={valid_to}\n"
        f"DEM_keyaliasname={alias}\n"
    )


# ── Tests: DEMKeyManager.get_cch_key ─────────────────────────────────────────


class TestDEMKeyManagerGetCchKey:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()
        self._priv, self.cch_pub = _mock_rsa_key_pair()
        self.response_body = _reqtype_w_response(self.cch_pub)

    def _make_manager(self):
        from modules.cts.dem.key_manager import DEMKeyManager
        return DEMKeyManager(config=self.config)

    @pytest.mark.asyncio
    async def test_get_cch_key_returns_cch_key_bundle(self):
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            bundle = await manager.get_cch_key()
        assert isinstance(bundle, CCHKeyBundle)

    @pytest.mark.asyncio
    async def test_bundle_has_correct_modulus(self):
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            bundle = await manager.get_cch_key()
        assert bundle.modulus == self.cch_pub.public_numbers().n

    @pytest.mark.asyncio
    async def test_bundle_has_correct_exponent(self):
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            bundle = await manager.get_cch_key()
        assert bundle.exponent == self.cch_pub.public_numbers().e

    @pytest.mark.asyncio
    async def test_bundle_has_correct_alias(self):
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            bundle = await manager.get_cch_key()
        assert bundle.dem_key_alias_name == "CCH-ALIAS-01"

    @pytest.mark.asyncio
    async def test_bundle_valid_dates_stored(self):
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            bundle = await manager.get_cch_key()
        assert bundle.valid_from == "01/01/2026"
        assert bundle.valid_to == "31/12/2026"


class TestDEMKeyManagerCaching:
    """Second call within 4 hours must NOT make a new HTTPS request."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()
        self._priv, self.cch_pub = _mock_rsa_key_pair()
        self.response_body = _reqtype_w_response(self.cch_pub)

    @pytest.mark.asyncio
    async def test_second_call_uses_cache(self):
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            b1 = await manager.get_cch_key()
            b2 = await manager.get_cch_key()
        assert mock_fetch.call_count == 1
        assert b1 is b2

    @pytest.mark.asyncio
    async def test_expired_cache_triggers_refresh(self):
        """When cache is older than key_refresh_interval_hours, re-fetch."""
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            b1 = await manager.get_cch_key()
            # Manually expire the cache
            manager._cached_bundle = CCHKeyBundle(
                modulus=b1.modulus,
                exponent=b1.exponent,
                valid_from=b1.valid_from,
                valid_to=b1.valid_to,
                dem_key_alias_name=b1.dem_key_alias_name,
                retrieved_at=time.time() - (4 * 3600 + 1),  # 4h+1s ago
            )
            b2 = await manager.get_cch_key()
        assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self):
        """force_refresh=True must always re-fetch regardless of cache age."""
        from modules.cts.dem.key_manager import DEMKeyManager
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = self.response_body
            await manager.get_cch_key()
            await manager.get_cch_key(force_refresh=True)
        assert mock_fetch.call_count == 2


class TestDEMKeyManagerErrorHandling:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()
        self._priv, self.cch_pub = _mock_rsa_key_pair()

    @pytest.mark.asyncio
    async def test_non_zero_status_code_raises(self):
        from modules.cts.dem.key_manager import DEMKeyManager, DEMKeyError
        error_response = _reqtype_w_response(self.cch_pub, status="99")
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = error_response
            with pytest.raises(DEMKeyError, match="StatusCode"):
                await manager.get_cch_key()

    @pytest.mark.asyncio
    async def test_missing_modulus_raises(self):
        from modules.cts.dem.key_manager import DEMKeyManager, DEMKeyError
        bad_response = "StatusCode=00\nStatusDesc=Success\nExponent=10001\n"
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = bad_response
            with pytest.raises(DEMKeyError, match="Modulus"):
                await manager.get_cch_key()

    @pytest.mark.asyncio
    async def test_missing_exponent_raises(self):
        from modules.cts.dem.key_manager import DEMKeyManager, DEMKeyError
        nums = self.cch_pub.public_numbers()
        bad_response = f"StatusCode=00\nStatusDesc=Success\nModulus={hex(nums.n)[2:].upper()}\n"
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = bad_response
            with pytest.raises(DEMKeyError, match="Exponent"):
                await manager.get_cch_key()

    @pytest.mark.asyncio
    async def test_network_error_raises_dem_key_error(self):
        from modules.cts.dem.key_manager import DEMKeyManager, DEMKeyError
        manager = DEMKeyManager(config=self.config)
        with patch.object(manager, "_fetch_from_cch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = ConnectionError("HTTPS connection refused")
            with pytest.raises(DEMKeyError):
                await manager.get_cch_key()


class TestDEMKeyManagerParseResponse:
    """Unit tests for the _parse_w_response helper."""

    def test_parse_valid_response(self):
        from modules.cts.dem.key_manager import DEMKeyManager, _parse_w_response
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric import rsa
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        pub = priv.public_key()
        nums = pub.public_numbers()
        response = _reqtype_w_response(pub)
        bundle = _parse_w_response(response)
        assert bundle.modulus == nums.n
        assert bundle.exponent == nums.e
        assert bundle.dem_key_alias_name == "CCH-ALIAS-01"

    def test_parse_raises_on_status_nonzero(self):
        from modules.cts.dem.key_manager import _parse_w_response, DEMKeyError
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric import rsa
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        pub = priv.public_key()
        bad = _reqtype_w_response(pub, status="88")
        with pytest.raises(DEMKeyError):
            _parse_w_response(bad)


# ---------------------------------------------------------------------------
# _fetch_from_cch's real body (not mocked out) — every test above patches
# _fetch_from_cch entirely, which is exactly how a missing `await` on both
# get_secret() calls (production bug, now fixed) went unnoticed: the coroutine
# objects were silently passed to httpx.AsyncClient(cert=...) and never
# actually exercised.
# ---------------------------------------------------------------------------

class TestDEMKeyManagerFetchFromCCH:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()

    @pytest.mark.asyncio
    async def test_fetch_from_cch_awaits_cert_and_key_secrets(self, monkeypatch):
        import sys
        from modules.cts.dem.key_manager import DEMKeyManager

        fake_response = MagicMock()
        fake_response.text = "StatusCode=00\n"
        fake_response.raise_for_status = MagicMock()

        fake_client_ctx = AsyncMock()
        fake_client_ctx.__aenter__.return_value = fake_client_ctx
        fake_client_ctx.post = AsyncMock(return_value=fake_response)

        fake_httpx = MagicMock()
        fake_httpx.AsyncClient.return_value = fake_client_ctx
        monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

        fake_config_service = AsyncMock()
        fake_config_service.get_secret.side_effect = lambda key: {
            f"banks.{self.config.bank_id}.ngch.tls.cert": "REAL-CERT-PEM",
            f"banks.{self.config.bank_id}.ngch.tls.key": "REAL-KEY-PEM",
        }[key]
        # shared/config/__init__.py rebinds the "config_service" package attribute
        # to the singleton instance, so `import shared.config.config_service as m`
        # resolves to the instance, not the module. Patch via sys.modules directly
        # instead — that's what the production code's own
        # `from shared.config.config_service import config_service` resolves through.
        import shared.config.config_service  # noqa: F401 — ensure sys.modules entry exists
        real_module = sys.modules["shared.config.config_service"]
        monkeypatch.setattr(real_module, "config_service", fake_config_service)

        manager = DEMKeyManager(config=self.config)
        body = await manager._fetch_from_cch()

        assert body == "StatusCode=00\n"
        # The whole point: httpx.AsyncClient must receive real decoded strings,
        # never unawaited coroutine objects, as the cert=(cert, key) tuple.
        fake_httpx.AsyncClient.assert_called_once_with(
            cert=("REAL-CERT-PEM", "REAL-KEY-PEM"), timeout=30.0
        )

    @pytest.mark.asyncio
    async def test_fetch_from_cch_propagates_vault_unavailable(self, monkeypatch):
        import sys
        from modules.cts.dem.key_manager import DEMKeyManager

        class _VaultUnavailableError(RuntimeError):
            pass

        fake_httpx = MagicMock()
        monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

        fake_config_service = AsyncMock()
        fake_config_service.get_secret.side_effect = _VaultUnavailableError("vault down")
        import shared.config.config_service  # noqa: F401 — ensure sys.modules entry exists
        real_module = sys.modules["shared.config.config_service"]
        monkeypatch.setattr(real_module, "config_service", fake_config_service)

        manager = DEMKeyManager(config=self.config)
        with pytest.raises(_VaultUnavailableError):
            await manager._fetch_from_cch()
