"""
DEM Resend Handler — NPCI DEM Spec v20 §2.f.

CCH places a DEMID_Resend_{timestamp}.txt file in the inward file list when
one or more previously submitted outward files must be retransmitted.
Each line in the .txt file is the filename that must be resent.

Resend process:
  1. Parse DEMID_Resend_*.txt → list of filenames
  2. For each filename: load the original wrapped bytes from sftp_local_backup_dir
  3. Re-upload via the normal outward SFTP path (already signed+encrypted)
     — no need to re-sign, the original wrapped file is reused as-is

Raises ResendError (not silent failure) if any backup file is missing,
so the operator can investigate without data loss.
"""
from __future__ import annotations

import os
from typing import List

from modules.cts.dem.models import DEMConfig


class ResendError(Exception):
    """Raised when a resend cannot be completed (e.g. backup file missing)."""


class ResendHandler:
    """Handles CCH resend instructions by retransmitting backed-up wrapped files."""

    def __init__(self, config: DEMConfig) -> None:
        self._config = config

    def parse_resend_file(self, content: str) -> List[str]:
        """Parse DEMID_Resend_*.txt content into a list of filenames.

        Each non-empty line is one filename. Strips whitespace.
        """
        filenames: List[str] = []
        for line in content.splitlines():
            line = line.strip()
            if line:
                filenames.append(line)
        return filenames

    async def _transmit(self, filename: str, data: bytes) -> None:
        """Re-upload a file to CCH SFTP. Seam for testing."""
        from modules.cts.dem.sftp_client import DEMSFTPClient
        from modules.cts.dem.switchover import SwitchoverHandler

        switchover = SwitchoverHandler(config=self._config)
        sftp = DEMSFTPClient(config=self._config)
        await sftp.upload(
            data=data,
            filename=filename,
            sftp_host=switchover.active_sftp_host,
            sftp_port=22,
        )

    async def resend(self, filenames: List[str]) -> None:
        """Re-transmit backed-up wrapped files to CCH.

        Raises:
            ResendError: if a backup file is not found in sftp_local_backup_dir.
        """
        for filename in filenames:
            backup_path = os.path.join(self._config.sftp_local_backup_dir, filename)
            try:
                with open(backup_path, "rb") as f:
                    data = f.read()
            except FileNotFoundError as exc:
                raise ResendError(
                    f"Backup not found for resend: {backup_path}"
                ) from exc

            await self._transmit(filename, data)
