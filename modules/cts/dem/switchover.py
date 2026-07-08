"""
DEM Switchover Handler — NPCI DEM Spec v20 §2.e.

CCH signals a DR switchover by placing a zero-byte file of type SWITCHOVER
in the inward file list (Reqtype=FL response). On detection:
  1. Download and ACK the SWITCHOVER file (required, even though it is zero bytes)
  2. Flip the active SFTP host from primary to secondary (or back)

The bank's DEM client must then use the new active_sftp_host for all subsequent
SFTP operations until the next SWITCHOVER instruction arrives.
"""
from __future__ import annotations

from modules.cts.dem.models import DEMConfig, DEMFileType, DEMInwardFileInfo


class SwitchoverHandler:
    """Tracks the active CCH SFTP host and applies DR switchover instructions.

    State is in-process only — on restart the primary is assumed active.
    Production: persist active_sftp_host in Redis (CTS cluster) for cross-pod awareness.
    """

    def __init__(self, config: DEMConfig) -> None:
        self._config = config
        self._active_host = config.cch_sftp_primary

    @property
    def active_sftp_host(self) -> str:
        return self._active_host

    def is_switchover(self, file_info: DEMInwardFileInfo) -> bool:
        """Return True if this inward file is a SWITCHOVER instruction.

        Per DEM spec §2.e: file type must be SWITCHOVER and size must be 0.
        """
        return (
            file_info.file_type == DEMFileType.SWITCHOVER
            and file_info.size_bytes == 0
        )

    def apply_switchover(self) -> str:
        """Flip active SFTP host between primary and secondary.

        Returns the new active host.
        """
        if self._active_host == self._config.cch_sftp_primary:
            self._active_host = self._config.cch_sftp_secondary
        else:
            self._active_host = self._config.cch_sftp_primary
        return self._active_host
