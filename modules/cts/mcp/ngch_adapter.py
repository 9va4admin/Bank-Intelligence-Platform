"""
NGCHAdapter — MCP server wrapping NGCH (National Grid Cheque Hub) SFTP/API.

Exposes MCP tools: file_decision, query_status.
All NGCH submissions go exclusively through this adapter — never direct.
Exactly-once semantics enforced by idempotency_key = workflow_id.
"""
import structlog

log = structlog.get_logger()

_VALID_DECISIONS = {"CONFIRM", "RETURN"}


class NGCHUnavailableError(RuntimeError):
    """Raised when NGCH is unreachable or returns an unexpected error."""


class DuplicateFilingError(RuntimeError):
    """Raised when NGCH rejects a submission as a duplicate (409 Conflict)."""


class NGCHAdapter:
    def __init__(self, bank_id: str, base_url: str) -> None:
        self._bank_id = bank_id
        self._base_url = base_url.rstrip("/")
        self._http = None
        self._ready = False

    def connect(self, http_client=None) -> None:
        if http_client is not None:
            self._http = http_client
        else:
            import httpx  # type: ignore[import]
            self._http = httpx.AsyncClient(timeout=30.0)
        self._ready = True
        log.info("ngch_adapter.connected", base_url=self._base_url, bank_id=self._bank_id)

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
