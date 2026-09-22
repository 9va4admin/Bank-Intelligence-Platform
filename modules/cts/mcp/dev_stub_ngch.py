"""
DevStubNGCHAdapter — DEV/TEST STAND-IN, NOT AN NPCI INTEGRATION.

There is no NGCH sandbox in the dev stack. This keeps the same
file_decision / query_status contract as NGCHAdapter (including exactly-once:
a repeated idempotency key raises DuplicateFilingError) so a decided cheque can
complete end to end. Selected with the ngch.dev_stub platform flag; refuses to
connect unless ASTRA_ENV=development, so it can never front a real bank.

submit_outward_lot / query_status_outward are the outward-clearing counterpart, called by
modules/cts/workflows/activities/ngch_submission_activities.py (NGCHSubmissionWorkflow). Neither the real
NGCHAdapter nor this stub had them until a real outward run reached HSM signing and submission for the first
time — confirmed there is no NPCI-facing outward transport at all yet (see docs/npci-readiness-plan.md).
The dev stub auto-acknowledges immediately (no real async NGCH round trip to simulate) and stays idempotent
per lot_number, same spirit as file_decision's idempotency-key handling.
"""
import os
import uuid
from dataclasses import dataclass
from typing import Optional

from modules.cts.mcp.ngch_adapter import DuplicateFilingError

_VALID_DECISIONS = ("CONFIRM", "RETURN")


@dataclass(frozen=True)
class OutwardAckResult:
    acknowledged: bool
    reason: Optional[str] = None


class DevStubNGCHAdapter:
    def __init__(self, bank_id: str) -> None:
        self._bank_id = bank_id
        self._filed: dict[str, dict] = {}          # idempotency_key -> record
        self._by_instrument: dict[str, dict] = {}
        self._outward: dict[str, str] = {}          # lot_number -> ngch_reference

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

    async def submit_outward_lot(self, bank_ifsc: str, lot_number: str, file_path: str,
                                 cibf_file_path: Optional[str], checksum: str) -> str:
        if lot_number not in self._outward:
            self._outward[lot_number] = f"NGCH-DEV-{uuid.uuid5(uuid.NAMESPACE_URL, lot_number).hex[:16].upper()}"
        return self._outward[lot_number]

    async def query_status_outward(self, reference: str) -> OutwardAckResult:
        if reference in self._outward.values():
            return OutwardAckResult(acknowledged=True)
        return OutwardAckResult(acknowledged=False, reason="NGCH_REFERENCE_UNKNOWN")
