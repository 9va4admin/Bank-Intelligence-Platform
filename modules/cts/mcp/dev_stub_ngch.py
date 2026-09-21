"""
DevStubNGCHAdapter — DEV/TEST STAND-IN, NOT AN NPCI INTEGRATION.

There is no NGCH sandbox in the dev stack. This keeps the same
file_decision / query_status contract as NGCHAdapter (including exactly-once:
a repeated idempotency key raises DuplicateFilingError) so a decided cheque can
complete end to end. Selected with the ngch.dev_stub platform flag; refuses to
connect unless ASTRA_ENV=development, so it can never front a real bank.
"""
import os
import uuid

from modules.cts.mcp.ngch_adapter import DuplicateFilingError

_VALID_DECISIONS = ("CONFIRM", "RETURN")


class DevStubNGCHAdapter:
    def __init__(self, bank_id: str) -> None:
        self._bank_id = bank_id
        self._filed: dict[str, dict] = {}          # idempotency_key -> record
        self._by_instrument: dict[str, dict] = {}

    def connect(self) -> None:
        if os.environ.get("ASTRA_ENV", "").lower() != "development":
            raise RuntimeError("DevStubNGCHAdapter may only run with ASTRA_ENV=development")

    async def file_decision(self, instrument_id: str, decision: str, workflow_id: str) -> dict:
        if decision not in _VALID_DECISIONS:
            raise ValueError(f"Invalid decision '{decision}'. Must be one of: {_VALID_DECISIONS}")
        if workflow_id in self._filed:
            raise DuplicateFilingError(f"duplicate filing for {instrument_id} (idempotency_key={workflow_id})")
        rec = {"acknowledgement_id": f"DEVSTUB-{uuid.uuid4().hex[:12].upper()}", "status": "ACCEPTED",
               "instrument_id": instrument_id, "decision": decision, "bank_id": self._bank_id}
        self._filed[workflow_id] = rec
        self._by_instrument[instrument_id] = rec
        return dict(rec)

    async def query_status(self, instrument_id: str) -> dict:
        return dict(self._by_instrument.get(instrument_id, {"status": "NOT_FILED"}))
