"""
NGCHSubmissionWorkflow — CTS Presentee Bank outward clearing.

Packages an endorsed lot into a CTS-compliant NGCH file and submits it
to the National Grid Clearing House for settlement.

Activity sequence:
  1. build_ngch_file          — assemble XML/CTS file from lot instruments
  2. submit_to_ngch           — NGCH adapter delivers file (SFTP or REST)
  3. confirm_acknowledgement  — parse NGCH response / ACK message
  4. write_audit              — Immudb audit (ALL terminal outcomes)

Terminal states: SUBMITTED | SUBMISSION_FAILED
Workflow ID: cts-ngchsub-{bank_id}-{lot_number}  (idempotent)
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class NGCHSubmissionInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str
    bank_id: str
    bank_ifsc: str
    session_id: str
    clearing_date: str
    instrument_count: int


class NGCHSubmissionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "SUBMITTED" | "SUBMISSION_FAILED"
    lot_number: str
    bank_id: str
    ngch_reference: Optional[str] = None
    failure_reason: Optional[str] = None
    audit_written: bool = False


class NGCHSubmissionWorkflow:
    def workflow_id(self, bank_id: str, lot_number: str) -> str:
        return f"cts-ngchsub-{bank_id}-{lot_number}"

    async def run_with_mocks(
        self,
        inp: NGCHSubmissionInput,
        mock_results: dict,
    ) -> NGCHSubmissionResult:
        # Step 1: Build NGCH file
        ngch_file = mock_results["ngch_file"]  # noqa: F841

        # Step 2: Submit to NGCH
        submission = mock_results["submission"]

        # Step 3: Confirm acknowledgement
        ack = mock_results["acknowledgement"]

        if not ack.acknowledged:
            failure_reason = getattr(ack, "reason", "NGCH_REJECTED")
            log.warning(
                "ngch_submission_workflow.submission_failed",
                lot_number=inp.lot_number,
                bank_id=inp.bank_id,
                reason=failure_reason,
            )
            await self._write_audit(mock_results, "SUBMISSION_FAILED", inp)
            return NGCHSubmissionResult(
                outcome="SUBMISSION_FAILED",
                lot_number=inp.lot_number,
                bank_id=inp.bank_id,
                ngch_reference=getattr(submission, "reference_number", None),
                failure_reason=failure_reason,
                audit_written=True,
            )

        log.info(
            "ngch_submission_workflow.submitted",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            ngch_reference=ack.reference_number,
        )
        await self._write_audit(mock_results, "SUBMITTED", inp)

        return NGCHSubmissionResult(
            outcome="SUBMITTED",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            ngch_reference=ack.reference_number,
            failure_reason=None,
            audit_written=True,
        )

    async def _write_audit(self, mock_results: dict, outcome: str, inp: NGCHSubmissionInput) -> None:
        audit_result = mock_results.get("audit")  # noqa: F841
        log.info(
            "ngch_submission_workflow.audit_written",
            outcome=outcome,
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
        )
