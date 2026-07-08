"""
DEM Outward Transport — NPCI DEM Spec v20.

Orchestrates the full outward upload sequence:
  1. sign_and_encrypt_file(raw_bytes, hsm, cch_key_bundle, bank_routing_no)
  2. reqtype_ru(file_type, clearing_type)   → DEMOutwardHandshakeResult (SFTP host)
  3. _sftp_upload(wrapped_bytes, filename, sftp_host, sftp_port)
     — internally uses DEMSFTPClient: .tmp write → rename → local backup
  4. reqtype_r(session_ref, filename)        → confirmed session_ref

All methods are async. HTTPS and SFTP clients are seams for testing.
"""
from __future__ import annotations

from typing import Any

from modules.cts.dem.https_client import DEMHTTPSClient
from modules.cts.dem.models import (
    CCHKeyBundle,
    DEMConfig,
    DEMFileType,
)
from modules.cts.dem.pki import DEMHSMProtocol, sign_and_encrypt_file
from modules.cts.dem.sftp_client import DEMSFTPClient


class DEMTransportError(Exception):
    """Raised when the outward upload sequence fails."""


class DEMOutwardTransport:
    """Orchestrates PKI → HTTPS handshake → SFTP upload → HTTPS confirm.

    Usage:
        transport = DEMOutwardTransport(config=dem_config)
        await transport.upload(
            file_bytes=cxf_bytes,
            file_type=DEMFileType.CXF,
            clearing_type="14",
            filename="000550050_CXF_14_08072026_001.cxf",
            hsm=hsm_client,
            cch_key_bundle=bundle,
        )

    Tests patch _https_client and _sftp_upload to avoid real network calls.
    """

    def __init__(self, config: DEMConfig) -> None:
        self._config = config
        self._https_client = DEMHTTPSClient(config=config)
        self._sftp_client = DEMSFTPClient(config=config)

    async def _sftp_upload(
        self,
        data: bytes,
        filename: str,
        sftp_host: str,
        sftp_port: int,
    ) -> None:
        """Thin async wrapper around DEMSFTPClient.upload. Tests patch this."""
        await self._sftp_client.upload(
            data=data,
            filename=filename,
            sftp_host=sftp_host,
            sftp_port=sftp_port,
        )

    async def upload(
        self,
        *,
        file_bytes: bytes,
        file_type: DEMFileType,
        clearing_type: str,
        filename: str,
        hsm: DEMHSMProtocol,
        cch_key_bundle: CCHKeyBundle,
    ) -> str:
        """Execute the full DEM outward upload sequence.

        Returns the confirmed session_ref from CCH (Reqtype=R response).

        Steps per DEM Spec v20 §2:
          1. PKI: sign + encrypt raw bytes
          2. HTTPS RU: register upload intent → get SFTP host + allowed types
          3. SFTP: upload wrapped bytes as .tmp then rename
          4. HTTPS R: confirm upload to CCH → receive session_ref

        Raises:
            DEMTransportError on any step failure.
        """
        # Step 1 — sign and encrypt
        wrapped_bytes = sign_and_encrypt_file(
            file_bytes,
            hsm=hsm,
            cch_key_bundle=cch_key_bundle,
            bank_routing_no=self._config.bank_routing_no,
        )

        # Step 2 — Reqtype=RU: upload intent registration
        handshake = await self._https_client.reqtype_ru(
            file_type=file_type,
            clearing_type=clearing_type,
        )

        # Step 3 — SFTP upload to CCH (wrapped bytes, .tmp then rename)
        await self._sftp_upload(
            data=wrapped_bytes,
            filename=filename,
            sftp_host=handshake.sftp_host,
            sftp_port=handshake.sftp_port,
        )

        # Step 4 — Reqtype=R: confirm upload
        confirmed_session_ref = await self._https_client.reqtype_r(
            session_ref=handshake.session_ref,
            filename=filename,
        )

        return confirmed_session_ref
