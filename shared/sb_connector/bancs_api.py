"""BANCS_API SB connector — TCS BaNCS REST adapter.

Used when the Sponsor Bank exposes BaNCS REST endpoints for lot submission.
Credentials fetched from Vault: secret/astra/{agency_id}/sb/{sb_bank_id}/bancs/*

The private methods (_http_ping, _http_post_lot, _http_get_inward) are
thin wrappers around httpx — patched in tests for isolation.
"""
from __future__ import annotations

import structlog

from shared.sb_connector.base import SBConnectorBase, SBSubmissionResult

log = structlog.get_logger()


class BANCSApiConnector(SBConnectorBase):

    async def ping(self) -> SBSubmissionResult:
        start, elapsed_ms = self._timed()
        try:
            await self._http_ping()
            ms = elapsed_ms()
            log.info("sb_connector.bancs.ping_ok", agency=self.agency_id, sb=self.sb_bank_id, ms=ms)
            return SBSubmissionResult(success=True, latency_ms=ms)
        except Exception as exc:
            log.warning(
                "sb_connector.bancs.ping_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                error=str(exc),
            )
            return SBSubmissionResult(
                success=False,
                error_code="BANCS_PING_FAILED",
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
            response = await self._http_post_lot(lot_file_path, instrument_count, session_id)
            ms = elapsed_ms()

            if response.get("status") != "ACCEPTED" or not response.get("reference_id"):
                error = response.get("error", "REJECTED_BY_SB")
                log.warning(
                    "sb_connector.bancs.rejected",
                    agency=self.agency_id,
                    sb=self.sb_bank_id,
                    session_id=session_id,
                    error=error,
                )
                return SBSubmissionResult(
                    success=False,
                    error_code="BANCS_SUBMISSION_REJECTED",
                    error_message=error,
                )

            log.info(
                "sb_connector.bancs.submitted",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                reference=response["reference_id"],
                ms=ms,
            )
            return SBSubmissionResult(
                success=True,
                reference_number=response["reference_id"],
                latency_ms=ms,
            )
        except Exception as exc:
            log.error(
                "sb_connector.bancs.submit_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                error=str(exc),
            )
            return SBSubmissionResult(
                success=False,
                error_code="BANCS_SUBMIT_FAILED",
                error_message=str(exc),
            )

    async def fetch_inward_instruments(self, session_id: str) -> list[dict]:
        try:
            instruments = await self._http_get_inward(session_id)
            log.info(
                "sb_connector.bancs.inward_fetched",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                count=len(instruments),
            )
            return instruments
        except Exception as exc:
            log.warning(
                "sb_connector.bancs.inward_fetch_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                error=str(exc),
            )
            return []

    # ------------------------------------------------------------------ #
    # Private IO methods — patched in tests
    # ------------------------------------------------------------------ #

    async def _http_ping(self) -> bool:
        raise NotImplementedError("Requires httpx client — inject via config_service in production")

    async def _http_post_lot(
        self, lot_file_path: str, instrument_count: int, session_id: str
    ) -> dict:
        raise NotImplementedError("Requires httpx client — inject via config_service in production")

    async def _http_get_inward(self, session_id: str) -> list[dict]:
        raise NotImplementedError("Requires httpx client — inject via config_service in production")
