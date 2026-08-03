"""
Tests for DEMOutwardTransport — NPCI DEM Spec v20 outward upload orchestrator.

DEMOutwardTransport wires PKI + HTTPS handshake + SFTP upload:
  1. sign_and_encrypt_file(raw_bytes, hsm, cch_key_bundle, bank_routing_no)
  2. reqtype_ru(file_type, clearing_type) → DEMOutwardHandshakeResult (SFTP host)
  3. sftp_upload(wrapped_bytes, filename, sftp_host, sftp_port)
     — uploads as {filename}.tmp then renames to {filename} per DEM spec
  4. reqtype_r(session_ref, filename) → confirmation

Also tests the SFTP client's .tmp-then-rename contract.

RED phase: all tests fail before transport.py and sftp_client.py exist.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import time

import pytest

from modules.cts.dem.models import (
    CCHKeyBundle,
    DEMConfig,
    DEMEncryptionAlgo,
    DEMFileType,
    DEMOutwardHandshakeResult,
    FileClearingType,
)


def _dem_config() -> DEMConfig:
    return DEMConfig(
        bank_id="saraswat-coop",
        bank_routing_no="000550050",
        dem_id="DEM-SARA-001",
        hsm_key_alias="SARA-HSM-KEY",
        cch_https_url="https://cch.npci.org.in/CCHBank/api/ftp",
        cch_sftp_primary="10.1.0.1",
        cch_sftp_secondary="10.1.0.2",
        sftp_username="SARA-SFTP",
        sftp_local_backup_dir="/tmp/dem",
    )


def _cch_bundle() -> CCHKeyBundle:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    pub = priv.public_key()
    nums = pub.public_numbers()
    return CCHKeyBundle(
        modulus=nums.n, exponent=nums.e,
        valid_from="01/01/2026", valid_to="31/12/2026",
        dem_key_alias_name="CCH-TEST", retrieved_at=time.time(),
    )


def _mock_hsm():
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    hsm = MagicMock()
    hsm.sign.side_effect = lambda data: priv.sign(
        data,
        __import__("cryptography.hazmat.primitives.asymmetric.padding", fromlist=["PKCS1v15"]).PKCS1v15(),
        __import__("cryptography.hazmat.primitives.hashes", fromlist=["SHA256"]).SHA256(),
    )
    hsm.get_key_alias.return_value = "TEST-ALIAS"
    return hsm


# ── DEMOutwardTransport ───────────────────────────────────────────────────────


class TestDEMOutwardTransportUpload:
    """Transport orchestrates PKI → RU handshake → SFTP upload → R confirm."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()
        self.bundle = _cch_bundle()
        self.hsm = _mock_hsm()
        self.raw_bytes = b"CXF XML content for testing"
        self.filename = "000550050_CXF_14_07072026_001.cxf"

    def _make_transport(self):
        from modules.cts.dem.transport import DEMOutwardTransport
        return DEMOutwardTransport(config=self.config)

    def test_transport_importable(self):
        from modules.cts.dem.transport import DEMOutwardTransport
        assert DEMOutwardTransport is not None

    @pytest.mark.asyncio
    async def test_upload_calls_sign_and_encrypt(self):
        """Transport must call sign_and_encrypt_file before uploading."""
        from modules.cts.dem.transport import DEMOutwardTransport
        transport = self._make_transport()

        handshake = DEMOutwardHandshakeResult(
            sftp_host="10.1.0.1", sftp_port=22,
            allowed_clearing_types=[FileClearingType.CXF_14],
            session_ref="SES-001",
        )

        with patch("modules.cts.dem.transport.sign_and_encrypt_file") as mock_pki, \
             patch.object(transport, "_https_client") as mock_https, \
             patch.object(transport, "_sftp_upload", new_callable=AsyncMock) as mock_sftp:

            mock_pki.return_value = b"WRAPPED_BYTES"
            mock_https.reqtype_ru = AsyncMock(return_value=handshake)
            mock_https.reqtype_r = AsyncMock(return_value="SES-001")
            mock_sftp.return_value = None

            await transport.upload(
                file_bytes=self.raw_bytes,
                file_type=DEMFileType.CXF,
                clearing_type="14",
                filename=self.filename,
                hsm=self.hsm,
                cch_key_bundle=self.bundle,
            )

        mock_pki.assert_called_once()
        call_kwargs = mock_pki.call_args
        assert call_kwargs[0][0] == self.raw_bytes  # first positional = raw_bytes

    @pytest.mark.asyncio
    async def test_upload_calls_reqtype_ru(self):
        from modules.cts.dem.transport import DEMOutwardTransport
        transport = self._make_transport()

        handshake = DEMOutwardHandshakeResult(
            sftp_host="10.1.0.1", sftp_port=22,
            allowed_clearing_types=[FileClearingType.CXF_14],
            session_ref="SES-001",
        )

        with patch("modules.cts.dem.transport.sign_and_encrypt_file", return_value=b"W"), \
             patch.object(transport, "_https_client") as mock_https, \
             patch.object(transport, "_sftp_upload", new_callable=AsyncMock):

            mock_https.reqtype_ru = AsyncMock(return_value=handshake)
            mock_https.reqtype_r = AsyncMock(return_value="SES-001")

            await transport.upload(
                file_bytes=self.raw_bytes,
                file_type=DEMFileType.CXF,
                clearing_type="14",
                filename=self.filename,
                hsm=self.hsm,
                cch_key_bundle=self.bundle,
            )

        mock_https.reqtype_ru.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_calls_sftp_upload(self):
        from modules.cts.dem.transport import DEMOutwardTransport
        transport = self._make_transport()

        handshake = DEMOutwardHandshakeResult(
            sftp_host="10.1.0.1", sftp_port=22,
            allowed_clearing_types=[FileClearingType.CXF_14],
            session_ref="SES-001",
        )

        with patch("modules.cts.dem.transport.sign_and_encrypt_file", return_value=b"WRAPPED"), \
             patch.object(transport, "_https_client") as mock_https, \
             patch.object(transport, "_sftp_upload", new_callable=AsyncMock) as mock_sftp:

            mock_https.reqtype_ru = AsyncMock(return_value=handshake)
            mock_https.reqtype_r = AsyncMock(return_value="SES-001")

            await transport.upload(
                file_bytes=self.raw_bytes,
                file_type=DEMFileType.CXF,
                clearing_type="14",
                filename=self.filename,
                hsm=self.hsm,
                cch_key_bundle=self.bundle,
            )

        mock_sftp.assert_called_once()
        # sftp_upload must receive the WRAPPED bytes, not raw bytes
        call_args = mock_sftp.call_args
        assert b"WRAPPED" in call_args[0] or call_args[1].get("data") == b"WRAPPED"

    @pytest.mark.asyncio
    async def test_upload_calls_reqtype_r_after_sftp(self):
        from modules.cts.dem.transport import DEMOutwardTransport
        transport = self._make_transport()

        handshake = DEMOutwardHandshakeResult(
            sftp_host="10.1.0.1", sftp_port=22,
            allowed_clearing_types=[FileClearingType.CXF_14],
            session_ref="SES-001",
        )

        with patch("modules.cts.dem.transport.sign_and_encrypt_file", return_value=b"W"), \
             patch.object(transport, "_https_client") as mock_https, \
             patch.object(transport, "_sftp_upload", new_callable=AsyncMock):

            mock_https.reqtype_ru = AsyncMock(return_value=handshake)
            mock_https.reqtype_r = AsyncMock(return_value="SES-001")

            await transport.upload(
                file_bytes=self.raw_bytes,
                file_type=DEMFileType.CXF,
                clearing_type="14",
                filename=self.filename,
                hsm=self.hsm,
                cch_key_bundle=self.bundle,
            )

        mock_https.reqtype_r.assert_called_once()


# ── DEMSFTPClient ─────────────────────────────────────────────────────────────


class TestDEMSFTPClientTmpRename:
    """.tmp upload + rename contract per DEM spec."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()

    def test_sftp_client_importable(self):
        from modules.cts.dem.sftp_client import DEMSFTPClient
        assert DEMSFTPClient is not None

    @pytest.mark.asyncio
    async def test_upload_writes_tmp_file_first(self):
        """SFTP upload must write to {filename}.tmp before renaming."""
        from modules.cts.dem.sftp_client import DEMSFTPClient

        client = DEMSFTPClient(config=self.config)
        mock_sftp = MagicMock()
        mock_sftp.putfo = MagicMock()
        mock_sftp.rename = MagicMock()

        with patch.object(client, "_open_sftp", new_callable=AsyncMock, return_value=mock_sftp), \
             patch("builtins.open", MagicMock()), \
             patch("os.makedirs"):
            await client.upload(
                data=b"file content",
                filename="test.cxf",
                sftp_host="10.1.0.1",
                sftp_port=22,
            )

        # putfo must have been called with the .tmp filename
        put_args = mock_sftp.putfo.call_args
        assert put_args is not None
        tmp_filename = put_args[0][1] if len(put_args[0]) > 1 else put_args[1].get("remotepath", "")
        assert tmp_filename.endswith(".tmp") or "test.cxf.tmp" in str(put_args)

    @pytest.mark.asyncio
    async def test_upload_renames_after_write(self):
        """After putfo, rename must be called to remove .tmp suffix."""
        from modules.cts.dem.sftp_client import DEMSFTPClient

        client = DEMSFTPClient(config=self.config)
        mock_sftp = MagicMock()
        mock_sftp.putfo = MagicMock()
        mock_sftp.rename = MagicMock()

        with patch.object(client, "_open_sftp", new_callable=AsyncMock, return_value=mock_sftp), \
             patch("builtins.open", MagicMock()), \
             patch("os.makedirs"):
            await client.upload(
                data=b"file content",
                filename="test.cxf",
                sftp_host="10.1.0.1",
                sftp_port=22,
            )

        # rename must be called
        mock_sftp.rename.assert_called_once()
        rename_args = mock_sftp.rename.call_args[0]
        # rename from .tmp to final name
        assert "test.cxf.tmp" in rename_args[0] or rename_args[0].endswith(".tmp")
        assert rename_args[1] == "test.cxf" or "test.cxf" in rename_args[1]

    @pytest.mark.asyncio
    async def test_sftp_upload_saves_local_backup(self):
        """Transport must save raw_bytes to local backup dir for resend capability."""
        from modules.cts.dem.sftp_client import DEMSFTPClient
        import os

        client = DEMSFTPClient(config=self.config)
        mock_sftp = MagicMock()
        mock_sftp.putfo = MagicMock()
        mock_sftp.rename = MagicMock()

        with patch.object(client, "_open_sftp", new_callable=AsyncMock, return_value=mock_sftp), \
             patch("builtins.open", MagicMock()) as mock_open:
            await client.upload(
                data=b"file content for backup",
                filename="test.cxf",
                sftp_host="10.1.0.1",
                sftp_port=22,
            )

        # Local backup open must have been called
        assert mock_open.called


# ---------------------------------------------------------------------------
# _open_sftp's real body (not mocked out) — every test above patches
# _open_sftp entirely. _open_sftp is the one call site in the whole DEM await
# sweep that can't just take an `await` — it's a *sync* def calling the async
# get_secret(), because it wraps paramiko (sync-only). Fix: make it async,
# await get_secret() directly, and push the blocking paramiko handshake onto
# a thread so it never stalls the event loop (a Temporal worker's activities
# all share one loop — a blocking SSH handshake here would stall every other
# concurrent cheque, not just this one).
# ---------------------------------------------------------------------------

class TestDEMSFTPClientOpenSftp:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.config = _dem_config()

    @pytest.mark.asyncio
    async def test_open_sftp_awaits_private_key_secret(self, monkeypatch):
        from modules.cts.dem.sftp_client import DEMSFTPClient

        fake_config_service = AsyncMock()
        fake_config_service.get_secret.return_value = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"
        # See test_dem_key_manager.py for why sys.modules is patched directly
        # rather than via `import shared.config.config_service as m`.
        import shared.config.config_service  # noqa: F401 — ensure sys.modules entry exists
        import sys
        real_module = sys.modules["shared.config.config_service"]
        monkeypatch.setattr(real_module, "config_service", fake_config_service)

        fake_sftp = MagicMock()
        fake_pkey = MagicMock()
        fake_ssh = MagicMock()
        fake_ssh.open_sftp.return_value = fake_sftp

        with patch("paramiko.RSAKey.from_private_key", return_value=fake_pkey) as mock_from_key, \
             patch("paramiko.SSHClient", return_value=fake_ssh):
            client = DEMSFTPClient(config=self.config)
            result = await client._open_sftp("10.1.0.1", 22)

        assert result is fake_sftp
        # The whole point: RSAKey.from_private_key must receive the real
        # awaited PEM string, never an unawaited coroutine object.
        assert mock_from_key.call_count == 1
        fake_ssh.connect.assert_called_once_with(
            hostname="10.1.0.1", port=22, username=self.config.sftp_username,
            pkey=fake_pkey, timeout=30,
        )

    @pytest.mark.asyncio
    async def test_open_sftp_propagates_vault_unavailable(self, monkeypatch):
        from modules.cts.dem.sftp_client import DEMSFTPClient

        class _VaultUnavailableError(RuntimeError):
            pass

        fake_config_service = AsyncMock()
        fake_config_service.get_secret.side_effect = _VaultUnavailableError("vault down")
        import shared.config.config_service  # noqa: F401 — ensure sys.modules entry exists
        import sys
        real_module = sys.modules["shared.config.config_service"]
        monkeypatch.setattr(real_module, "config_service", fake_config_service)

        client = DEMSFTPClient(config=self.config)
        with pytest.raises(_VaultUnavailableError):
            await client._open_sftp("10.1.0.1", 22)
