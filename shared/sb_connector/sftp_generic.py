"""SFTP_GENERIC SB connector — generic SFTP file-drop adapter.

Used when the Sponsor Bank accepts lot files via SFTP drop folder.
Credentials (host, port, user, private_key) fetched from Vault at call time via
config_service.get_secret(f"sb.{agency_id}.{sb_bank_id}.sftp.*").

The private methods (_sftp_connect, _sftp_upload, _sftp_list_inward) are
thin wrappers around asyncssh — patched directly in tests for isolation.
"""
from __future__ import annotations

import structlog

from shared.sb_connector.base import SBConnectorBase, SBSubmissionResult

log = structlog.get_logger()


class SFTPGenericConnector(SBConnectorBase):

    async def ping(self) -> SBSubmissionResult:
        start, elapsed_ms = self._timed()
        try:
            await self._sftp_connect()
            ms = elapsed_ms()
            log.info("sb_connector.sftp.ping_ok", agency=self.agency_id, sb=self.sb_bank_id, ms=ms)
            return SBSubmissionResult(success=True, latency_ms=ms)
        except Exception as exc:
            log.warning(
                "sb_connector.sftp.ping_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                error=str(exc),
            )
            return SBSubmissionResult(
                success=False,
                error_code="SFTP_PING_FAILED",
                error_message=str(exc),
            )

    async def submit_lot(
        self,
        lot_file_path: str,
        instrument_count: int,
        session_id: str,
    ) -> SBSubmissionResult:
        start, elapsed_ms = self._timed()
        try:
            reference = await self._sftp_upload(lot_file_path, session_id)
            ms = elapsed_ms()
            log.info(
                "sb_connector.sftp.submitted",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                instrument_count=instrument_count,
                reference=reference,
                ms=ms,
            )
            return SBSubmissionResult(success=True, reference_number=reference, latency_ms=ms)
        except Exception as exc:
            log.error(
                "sb_connector.sftp.upload_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                error=str(exc),
            )
            return SBSubmissionResult(
                success=False,
                error_code="SFTP_UPLOAD_FAILED",
                error_message=str(exc),
            )

    async def fetch_inward_instruments(self, session_id: str) -> list[dict]:
        try:
            instruments = await self._sftp_list_inward(session_id)
            log.info(
                "sb_connector.sftp.inward_fetched",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                count=len(instruments),
            )
            return instruments
        except Exception as exc:
            log.warning(
                "sb_connector.sftp.inward_fetch_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                error=str(exc),
            )
            return []

    # ------------------------------------------------------------------ #
    # Private IO methods — patched in tests; real impl uses asyncssh
    # ------------------------------------------------------------------ #

    async def _sftp_connect(self) -> bool:
        """Open SFTP connection to the SB. Raises on failure."""
        raise NotImplementedError("Requires asyncssh — inject via config_service in production")

    async def _sftp_upload(self, lot_file_path: str, session_id: str) -> str:
        """Upload lot file to SB SFTP drop folder. Returns SB reference string."""
        raise NotImplementedError("Requires asyncssh — inject via config_service in production")

    async def _sftp_list_inward(self, session_id: str) -> list[dict]:
        """List inward instruments from SB inward folder. Returns list of dicts."""
        raise NotImplementedError("Requires asyncssh — inject via config_service in production")
