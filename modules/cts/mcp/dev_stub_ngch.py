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

fetch_settlement_report / submit_representation are the session-reconciliation counterpart, called by
modules/cts/workflows/activities/session_reconciliation_activities.py and
modules/cts/workflows/activities/representation_activities.py (SessionReconciliationWorkflow /
ChequeRepresentationWorkflow). Same story again — there is no NGCH settlement sandbox to poll, so
fetch_settlement_report reads back the instruments this same dev stub already accepted for the session
(via submit_outward_lot's ngch_instrument_ref, matched off the real cts.cheque_instruments table) and
reports every one of them SETTLED. That means this stub can never itself produce a reconciliation
exception — a real exception can only be exercised today by writing a non-SETTLED settlement row
by hand for a test. submit_representation follows the exact same auto-acknowledge, idempotent-by-key
pattern as submit_outward_lot.
"""
import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from modules.cts.mcp.ngch_adapter import DuplicateFilingError

_VALID_DECISIONS = ("CONFIRM", "RETURN")


@dataclass(frozen=True)
class OutwardAckResult:
    acknowledged: bool
    reason: Optional[str] = None


class DevStubNGCHAdapter:
    def __init__(self, bank_id: str, db_pool: Any = None) -> None:
        self._bank_id = bank_id
        self._db_pool = db_pool
        self._filed: dict[str, dict] = {}          # idempotency_key -> record
        self._by_instrument: dict[str, dict] = {}
        self._outward: dict[str, str] = {}          # lot_number -> ngch_reference
        self._representations: dict[str, str] = {}  # instrument_id -> ngch_reference

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

    async def fetch_settlement_report(self, session_id: str, clearing_date: str,
                                      bank_ifsc: str) -> list[dict]:
        if self._db_pool is None:
            return []
        try:
            session_uuid = uuid.UUID(session_id)
        except ValueError:
            return []
        async with self._db_pool.acquire() as conn:
            session_row = await conn.fetchrow(
                "SELECT ngch_session_ref FROM cts.clearing_sessions "
                "WHERE session_id = $1 AND bank_id = $2",
                session_uuid, self._bank_id,
            )
            if session_row is None or not session_row["ngch_session_ref"]:
                return []
            rows = await conn.fetch(
                "SELECT DISTINCT instrument_id FROM cts.cheque_instruments "
                "WHERE bank_id = $1 AND direction = 'OUTWARD' AND ngch_instrument_ref = $2",
                self._bank_id, session_row["ngch_session_ref"],
            )
        return [{"instrument_id": str(r["instrument_id"]), "status": "SETTLED"} for r in rows]

    async def submit_representation(self, instrument_id: str, bank_ifsc: str,
                                     return_reason_code: str, original_session_id: str) -> str:
        if instrument_id not in self._representations:
            self._representations[instrument_id] = (
                f"NGCH-DEV-REP-{uuid.uuid5(uuid.NAMESPACE_URL, instrument_id).hex[:16].upper()}"
            )
        return self._representations[instrument_id]
