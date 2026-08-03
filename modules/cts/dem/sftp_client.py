"""
DEM SFTP Client — NPCI DEM Spec v20 §2.b / §2.c.

Outward upload protocol (§2.b):
  1. Write file as {filename}.tmp on the CCH SFTP server
  2. Rename to {filename} (atomic — CCH ignores .tmp files)
  3. Save a local backup copy in sftp_local_backup_dir for resend

Inward download protocol (§2.c):
  1. Download up to sftp_max_batch_size files per session (default 5)

The SFTP client uses paramiko. In tests the _open_sftp() seam is patched.
"""
from __future__ import annotations

import asyncio
import io
import os
from typing import List

import paramiko

from modules.cts.dem.models import DEMConfig


class DEMSFTPError(Exception):
    """Raised on SFTP transport failures."""


class DEMSFTPClient:
    """Handles raw SFTP file transfer for the DEM protocol.

    Production: opens a real paramiko SSH connection.
    Tests: patch _open_sftp() with an AsyncMock that has putfo/rename/get methods.
    """

    def __init__(self, config: DEMConfig) -> None:
        self._config = config

    async def _open_sftp(self, sftp_host: str, sftp_port: int) -> paramiko.SFTPClient:
        """Open an authenticated SFTP session.

        Key is loaded from Vault at runtime via config_service. paramiko is
        sync-only — the handshake runs in a thread so it never blocks the
        event loop (this coroutine runs inside a Temporal activity that shares
        its worker's loop with every other concurrent cheque).
        Tests patch this method.
        """
        from shared.config.config_service import config_service

        bank_id = self._config.bank_id
        private_key_pem = await config_service.get_secret(f"banks.{bank_id}.ngch.sftp.private_key")

        def _connect() -> paramiko.SFTPClient:
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key_pem))
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
            ssh.connect(
                hostname=sftp_host,
                port=sftp_port,
                username=self._config.sftp_username,
                pkey=pkey,
                timeout=30,
            )
            return ssh.open_sftp()

        return await asyncio.to_thread(_connect)

    async def upload(
        self,
        *,
        data: bytes,
        filename: str,
        sftp_host: str,
        sftp_port: int,
    ) -> None:
        """Upload wrapped DEM file to CCH SFTP using .tmp-then-rename protocol.

        Per DEM spec §2.b:
          - Write to {filename}.tmp first (CCH ignores .tmp files)
          - Rename to final {filename} (CCH picks it up immediately)
          - Save local backup in sftp_local_backup_dir for resend capability
        """
        tmp_filename = filename + ".tmp"
        backup_path = os.path.join(self._config.sftp_local_backup_dir, filename)

        # Local backup — written before SFTP so resend is always possible
        os.makedirs(self._config.sftp_local_backup_dir, exist_ok=True)
        with open(backup_path, "wb") as f:
            f.write(data)

        sftp = await self._open_sftp(sftp_host, sftp_port)

        def _do_upload() -> None:
            file_obj = io.BytesIO(data)
            sftp.putfo(file_obj, tmp_filename)
            sftp.rename(tmp_filename, filename)

        try:
            await asyncio.to_thread(_do_upload)
        finally:
            await asyncio.to_thread(sftp.close)

    async def download_batch(
        self,
        *,
        filenames: List[str],
        sftp_host: str,
        sftp_port: int,
        local_dir: str,
    ) -> List[str]:
        """Download up to sftp_max_batch_size inward files from CCH SFTP.

        Returns list of local file paths that were successfully downloaded.
        Per DEM spec §2.c: max 5 files per SFTP session.
        """
        batch = filenames[: self._config.sftp_max_batch_size]
        downloaded: List[str] = []

        sftp = await self._open_sftp(sftp_host, sftp_port)

        def _do_download() -> List[str]:
            paths: List[str] = []
            for remote_filename in batch:
                local_path = os.path.join(local_dir, remote_filename)
                sftp.get(remote_filename, local_path)
                paths.append(local_path)
            return paths

        try:
            downloaded = await asyncio.to_thread(_do_download)
        finally:
            await asyncio.to_thread(sftp.close)

        return downloaded
