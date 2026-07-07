"""
NGCHAdapter — MCP server wrapping NGCH (National Grid Cheque Hub) SFTP/API.

Exposes MCP tools: file_decision, query_status, get_inward_instruments.
All NGCH submissions go exclusively through this adapter — never direct.
Exactly-once semantics enforced by idempotency_key = workflow_id.
mTLS: client cert + key loaded from Vault via config_service on connect().

Inward parsing:
  get_inward_instruments(pxf_xml_bytes) — delegates to PXFParser.parse() so that
  each InwardInstrument carries iet_deadline derived from the per-item ItemExpiryTime
  field in the PXF XML (IST → UTC Unix timestamp).  Callers must NOT compute
  iet_deadline from config iet_minutes — the PXF value is authoritative per NPCI spec.
"""
from __future__ import annotations

import os
import ssl
import tempfile
from typing import TYPE_CHECKING, List

import structlog

if TYPE_CHECKING:
    from modules.cts.ngch.pxf_parser import InwardInstrument

log = structlog.get_logger()

_VALID_DECISIONS = {"CONFIRM", "RETURN"}


class NGCHUnavailableError(RuntimeError):
    """Raised when NGCH is unreachable or returns an unexpected error."""


class DuplicateFilingError(RuntimeError):
    """Raised when NGCH rejects a submission as a duplicate (409 Conflict)."""


def _build_ssl_context(cert_pem: str, key_pem: str) -> ssl.SSLContext:
    """Build an SSLContext with a client cert/key for mTLS.

    Python's ssl module requires file paths for load_cert_chain — we write to
    a NamedTemporaryFile and delete immediately after the context is built.
    The SSLContext retains the cert in memory; the temp files are ephemeral.
    """
    ctx = ssl.create_default_context()
    cert_fd, cert_path = tempfile.mkstemp(suffix=".pem")
    key_fd, key_path = tempfile.mkstemp(suffix=".pem")
    try:
        os.write(cert_fd, cert_pem.encode())
        os.close(cert_fd)
        os.write(key_fd, key_pem.encode())
        os.close(key_fd)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    finally:
        try:
            os.unlink(cert_path)
        except OSError:
            pass
        try:
            os.unlink(key_path)
        except OSError:
            pass
    return ctx


class NGCHAdapter:
    def __init__(self, bank_id: str, base_url: str) -> None:
        self._bank_id = bank_id
        self._base_url = base_url.rstrip("/")
        self._http = None
        self._ready = False

    async def connect(self, http_client=None, config_service=None) -> None:
        """Initialise the HTTP client.

        Production callers must inject config_service so that a mTLS SSLContext
        is built from Vault-held client cert/key.  Test callers inject http_client
        directly and may omit config_service.
        """
        if http_client is not None:
            self._http = http_client
        else:
            import httpx  # type: ignore[import]

            if config_service is not None:
                cert_pem = config_service.get_secret("ngch.tls.client_cert")
                key_pem = config_service.get_secret("ngch.tls.client_key")
                ssl_ctx = _build_ssl_context(cert_pem, key_pem)
                self._http = httpx.AsyncClient(timeout=30.0, verify=ssl_ctx)
                log.info(
                    "ngch_adapter.connected",
                    base_url=self._base_url,
                    bank_id=self._bank_id,
                    mtls=True,
                )
            else:
                # Test / development path — no mTLS.
                # Production deployments must always inject config_service.
                log.warning(
                    "ngch_adapter.connected_no_mtls",
                    base_url=self._base_url,
                    bank_id=self._bank_id,
                )
                self._http = httpx.AsyncClient(timeout=30.0)

        self._ready = True

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "NGCHAdapter.connect() has not been called. "
                "Call it during service startup before filing to NGCH."
            )

    async def file_decision(
        self,
        instrument_id: str,
        decision: str,
        workflow_id: str,
    ) -> dict:
        """
        File a cheque decision (CONFIRM or RETURN) to NGCH.

        idempotency_key = workflow_id ensures Temporal retries are safe.
        Raises DuplicateFilingError on 409 (already filed with same key).
        Raises NGCHUnavailableError on network or server errors.
        Raises ValueError for invalid decision values.
        """
        self._assert_ready()

        if decision not in _VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision '{decision}'. Must be one of: {_VALID_DECISIONS}. "
                "Only CONFIRM or RETURN are valid NGCH filing decisions."
            )

        url = f"{self._base_url}/decisions"
        payload = {
            "instrument_id": instrument_id,
            "decision": decision,
            "bank_id": self._bank_id,
            "idempotency_key": workflow_id,
        }

        try:
            response = await self._http.post(url, json=payload)

            if response.status_code == 409:
                log.warning(
                    "ngch_adapter.duplicate_filing",
                    instrument_id=instrument_id,
                    workflow_id=workflow_id,
                )
                raise DuplicateFilingError(
                    f"NGCH rejected duplicate filing for instrument {instrument_id} "
                    f"(idempotency_key={workflow_id})"
                )

            response.raise_for_status()
            data = response.json()
        except (DuplicateFilingError, ValueError):
            raise
        except Exception as exc:
            log.error(
                "ngch_adapter.file_decision.failed",
                instrument_id=instrument_id,
                error=str(exc),
            )
            raise NGCHUnavailableError(f"NGCH file_decision failed: {exc}") from exc

        log.info(
            "ngch_adapter.filed",
            instrument_id=instrument_id,
            decision=decision,
            acknowledgement_id=data.get("acknowledgement_id"),
        )
        return data

    async def query_status(self, instrument_id: str) -> dict:
        """Query the current NGCH status for a filed instrument."""
        self._assert_ready()
        url = f"{self._base_url}/decisions/{instrument_id}"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            log.error("ngch_adapter.query_status.failed", instrument_id=instrument_id, error=str(exc))
            raise NGCHUnavailableError(f"NGCH query_status failed: {exc}") from exc

    def get_inward_instruments(self, pxf_xml_bytes: bytes) -> List["InwardInstrument"]:
        """Parse a PXF XML payload from NGCH and return per-instrument records.

        Each returned InwardInstrument has iet_deadline set from the per-item
        ItemExpiryTime field (IST → UTC Unix timestamp) — not from config.

        This is the P0 wiring point: callers receive accurate individual deadlines
        and must use them as the iet_deadline for ChequeWorkflowInput rather than
        computing a shared deadline from iet_minutes configuration.

        Raises:
            PXFParseError: if the XML is malformed, missing mandatory fields, or
                           contains an unparseable ItemExpiryTime.
            ValueError: if pxf_xml_bytes is empty.
        """
        from modules.cts.ngch.pxf_parser import PXFParser
        return PXFParser().parse(pxf_xml_bytes)

    def list_tools(self) -> list[dict]:
        """Return MCP tool descriptors for this adapter."""
        return [
            {
                "name": "file_decision",
                "description": (
                    "File a cheque decision (CONFIRM or RETURN) to NGCH. "
                    "Exactly-once: idempotency_key prevents duplicate submissions."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instrument_id": {"type": "string", "description": "Unique cheque instrument ID"},
                        "decision": {"type": "string", "enum": ["CONFIRM", "RETURN"]},
                        "workflow_id": {"type": "string", "description": "Temporal workflow ID (idempotency key)"},
                    },
                    "required": ["instrument_id", "decision", "workflow_id"],
                },
            },
            {
                "name": "query_status",
                "description": "Query the current NGCH filing status for an instrument.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instrument_id": {"type": "string", "description": "Unique cheque instrument ID"},
                    },
                    "required": ["instrument_id"],
                },
            },
        ]
