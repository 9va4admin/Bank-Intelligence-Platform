"""
MismatchResolutionWorkflow — branch supervisor resolution for Vision ↔ scanner mismatch.

Triggered by: OutwardScanWorkflow when Vision LLM amount differs from scanner amount.

Flow:
  1. publish_mismatch_hold — publish to cts.mismatch.{bank_id}.{branch_id} Kafka topic
     (EEH SSE feed picks this up → branch portal shows HELD item in real-time)
  2. wait_for_signal      — Temporal signal: GO_AHEAD | REJECTED (or 4-hour timeout)
  3. write_audit          — Immudb audit for all outcomes

Terminal states: GO_AHEAD | REJECTED | TIMEOUT_AUTO_REJECTED
Workflow ID: cts-mismatch-{bank_id}-{branch_id}-{mismatch_id}

ABANDON parent-close policy: this workflow persists even if OutwardScanWorkflow
is interrupted — branch supervisor must still be able to resolve it and the
instrument must be audited regardless of parent state.
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

MISMATCH_TIMEOUT_HOURS = 4          # 4-hour resolution window before auto-reject


class MismatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    mismatch_id: str
    bank_id: str
    branch_id: str
    scan_id: str
    instrument_id: str
    pu_id: str
    scanner_amount_str: str         # as-read by scanner MICR (string, preserves original)
    vision_amount_str: str          # as-read by Vision LLM
    mismatch_fields: list[str]      # e.g. ["amount_figures", "amount_words"]
    payee_display: str              # masked: R***
    session_id: str                 # EEH session context


class MismatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                    # GO_AHEAD | REJECTED | TIMEOUT_AUTO_REJECTED
    mismatch_id: str
    bank_id: str
    branch_id: str
    resolved_by: Optional[str]      # operator_id; None on timeout
    audit_written: bool = False


class MismatchResolutionWorkflow:
    def workflow_id(self, bank_id: str, branch_id: str, mismatch_id: str) -> str:
        return f"cts-mismatch-{bank_id}-{branch_id}-{mismatch_id}"

    def mismatch_kafka_topic(self, bank_id: str, branch_id: str) -> str:
        return f"cts.mismatch.{bank_id}.{branch_id}"

    async def run_with_mocks(
        self,
        inp: MismatchInput,
        mock_results: dict,
    ) -> MismatchResult:
        """
        Testable orchestration. In production this is a Temporal @workflow.run method;
        mock_results replaces each activity/signal call.

        mock_results keys:
          "kafka"  — Kafka publish result (accessed to confirm publish happens)
          "signal" — MagicMock(action="GO_AHEAD"|"REJECTED", resolved_by=str) or None (timeout)
          "audit"  — audit write result
        """
        # Step 1: Publish hold event to branch Kafka topic (before any wait)
        # In production: workflow.execute_activity(publish_mismatch_hold, ...)
        kafka_result = mock_results["kafka"]   # noqa: F841 — activity call in production
        log.info(
            "mismatch_resolution_workflow.hold_published",
            mismatch_id=inp.mismatch_id,
            bank_id=inp.bank_id,
            branch_id=inp.branch_id,
            topic=self.mismatch_kafka_topic(inp.bank_id, inp.branch_id),
            scanner_amount=inp.scanner_amount_str,
            vision_amount=inp.vision_amount_str,
        )

        # Step 2: Wait for branch supervisor signal (GO_AHEAD | REJECTED)
        # In production: await workflow.wait_condition(...) with 4-hour timeout
        # signal=None simulates timeout
        signal = mock_results["signal"]

        if signal is None:
            outcome = "TIMEOUT_AUTO_REJECTED"
            resolved_by = None
            log.info(
                "mismatch_resolution_workflow.timeout_auto_rejected",
                mismatch_id=inp.mismatch_id,
                bank_id=inp.bank_id,
                branch_id=inp.branch_id,
                timeout_hours=MISMATCH_TIMEOUT_HOURS,
            )
        else:
            action = signal.action          # "GO_AHEAD" | "REJECTED"
            resolved_by = signal.resolved_by
            if action == "GO_AHEAD":
                outcome = "GO_AHEAD"
                log.info(
                    "mismatch_resolution_workflow.go_ahead",
                    mismatch_id=inp.mismatch_id,
                    bank_id=inp.bank_id,
                    resolved_by=resolved_by,
                )
            else:
                outcome = "REJECTED"
                log.info(
                    "mismatch_resolution_workflow.rejected",
                    mismatch_id=inp.mismatch_id,
                    bank_id=inp.bank_id,
                    resolved_by=resolved_by,
                )

        # Step 3: Audit — always written regardless of outcome
        # In production: workflow.execute_activity(write_audit, ...)
        audit_result = mock_results["audit"]   # noqa: F841
        log.info(
            "mismatch_resolution_workflow.audit_written",
            outcome=outcome,
            mismatch_id=inp.mismatch_id,
            bank_id=inp.bank_id,
        )

        return MismatchResult(
            outcome=outcome,
            mismatch_id=inp.mismatch_id,
            bank_id=inp.bank_id,
            branch_id=inp.branch_id,
            resolved_by=resolved_by,
            audit_written=True,
        )
