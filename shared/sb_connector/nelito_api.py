"""NELITO_API SB connector — Nelito FinNext REST adapter.

Used when the Sponsor Bank runs Nelito FinNext CBS and exposes a CTS
lot-submission API. Credentials from Vault:
  secret/astra/{agency_id}/sb/{sb_bank_id}/nelito/*

Private methods (_nelito_ping, _nelito_submit, _nelito_fetch_inward)
are patched in tests.
"""
from __future__ import annotations

import structlog

from shared.sb_connector.base import SBConnectorBase, SBSubmissionResult

log = structlog.get_logger()


class NelitApiConnector(SBConnectorBase):

    async def ping(self) -> SBSubmissionResult:
        start, elapsed_ms = self._timed()
        try:
            await self._nelito_ping()
            ms = elapsed_ms()
            log.info("sb_connector.nelito.ping_ok", agency=self.agency_id, sb=self.sb_bank_id, ms=ms)
            return SBSubmissionResult(success=True, latency_ms=ms)
        except Exception as exc:
            log.warning(
                "sb_connector.nelito.ping_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                error=str(exc),
            )
            return SBSubmissionResult(
                success=False,
                error_code="NELITO_PING_FAILED",
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
            response = await self._nelito_submit(lot_file_path, instrument_count, session_id)
            ms = elapsed_ms()

            if not response.get("ack"):
                return SBSubmissionResult(
                    success=False,
                    error_code="NELITO_SUBMISSION_REJECTED",
                    error_message=response.get("error", "No ack from Nelito"),
                )

            log.info(
                "sb_connector.nelito.submitted",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                txn_id=response.get("txn_id"),
                ms=ms,
            )
            return SBSubmissionResult(
                success=True,
                reference_number=response.get("txn_id"),
                latency_ms=ms,
            )
        except Exception as exc:
            log.error(
                "sb_connector.nelito.submit_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                error=str(exc),
            )
            return SBSubmissionResult(
                success=False,
                error_code="NELITO_UPLOAD_FAILED",
                error_message=str(exc),
            )

    async def fetch_inward_instruments(self, session_id: str) -> list[dict]:
        try:
            instruments = await self._nelito_fetch_inward(session_id)
            log.info(
                "sb_connector.nelito.inward_fetched",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                count=len(instruments),
            )
            return instruments
        except Exception as exc:
            log.warning(
                "sb_connector.nelito.inward_fetch_failed",
                agency=self.agency_id,
                sb=self.sb_bank_id,
                session_id=session_id,
                error=str(exc),
            )
            return []

    # ------------------------------------------------------------------ #
    # Private IO methods — patched in tests
    # ------------------------------------------------------------------ #

    async def _nelito_ping(self) -> bool:
        raise NotImplementedError("Requires httpx client — inject via config_service in production")

    async def _nelito_submit(
        self, lot_file_path: str, instrument_count: int, session_id: str
    ) -> dict:
        raise NotImplementedError("Requires httpx client — inject via config_service in production")

    async def _nelito_fetch_inward(self, session_id: str) -> list[dict]:
        raise NotImplementedError("Requires httpx client — inject via config_service in production")
