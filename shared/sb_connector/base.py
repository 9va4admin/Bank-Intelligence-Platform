"""Abstract SB connector interface + factory.

An SBConnector mediates all communication between the Agency Command Center
and an upstream Sponsor Bank. The Agency submits sealed lots to the SB for
NGCH filing; the SB returns inward instruments back to the Agency.

Three concrete implementations:
  SFTP_GENERIC  — generic SFTP file-drop (most UCBs, legacy SBs)
  BANCS_API     — TCS BaNCS REST API
  NELITO_API    — Nelito FinNext REST API
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class SBSubmissionResult(BaseModel):
    """Result of a single SB interaction (ping, lot submit)."""
    model_config = ConfigDict(frozen=True)

    success: bool
    reference_number: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None


class SBInwardBatch(BaseModel):
    """Batch of inward instruments received from the SB relay."""
    model_config = ConfigDict(frozen=True)

    session_id: str
    sb_bank_id: str
    instruments: list[dict]
    received_at: str


class SBConnectorBase(ABC):
    """
    Abstract base for all SB adapters.

    Implementations must be safe to instantiate without IO — all IO happens
    inside the async methods. Credentials come from config_service at call time.
    """

    def __init__(self, agency_id: str, sb_bank_id: str) -> None:
        self.agency_id = agency_id
        self.sb_bank_id = sb_bank_id

    @abstractmethod
    async def ping(self) -> SBSubmissionResult:
        """Health check — connect and authenticate, return latency."""
        ...

    @abstractmethod
    async def submit_lot(
        self,
        lot_file_path: str,
        instrument_count: int,
        session_id: str,
    ) -> SBSubmissionResult:
        """
        Deliver a sealed lot to the SB.

        Returns a result with success=True and reference_number set on
        acceptance. Returns success=False with error_code on rejection.
        Never raises — all errors are expressed as SBSubmissionResult fields.
        """
        ...

    @abstractmethod
    async def fetch_inward_instruments(self, session_id: str) -> list[dict]:
        """
        Pull inward instruments the SB has queued for this agency.
        Returns empty list when none pending. Never raises.
        """
        ...

    def _timed(self) -> tuple[float, callable]:
        """Returns (start_ns, elapsed_ms_fn) for latency tracking."""
        start = time.perf_counter()
        return start, lambda: int((time.perf_counter() - start) * 1000)


def get_connector_for_type(
    connector_type: str,
    agency_id: str,
    sb_bank_id: str,
) -> SBConnectorBase:
    """Factory: instantiate the correct SB adapter for the given connector_type."""
    from shared.sb_connector.sftp_generic import SFTPGenericConnector
    from shared.sb_connector.bancs_api import BANCSApiConnector
    from shared.sb_connector.nelito_api import NelitApiConnector

    mapping: dict[str, type[SBConnectorBase]] = {
        "SFTP_GENERIC": SFTPGenericConnector,
        "BANCS_API": BANCSApiConnector,
        "NELITO_API": NelitApiConnector,
    }

    cls = mapping.get(connector_type)
    if cls is None:
        raise ValueError(
            f"Unknown connector_type '{connector_type}'. "
            f"Valid types: {sorted(mapping.keys())}"
        )

    log.info(
        "sb_connector.instantiated",
        connector_type=connector_type,
        agency_id=agency_id,
        sb_bank_id=sb_bank_id,
    )
    return cls(agency_id=agency_id, sb_bank_id=sb_bank_id)
