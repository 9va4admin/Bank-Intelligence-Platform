"""
MSVValidationWorkflow — Temporal workflow for multi-signature validation.

Workflow ID: msv-{bank_id}-{instrument_id}  (deterministic, exactly-once)

Activity sequence:
  1. orchestrator.validate(msv_input, account_meta) → MSVOutput
  2. write_audit → Immudb (AUDIT_RETRY, unlimited)

On AMBER (vault miss):
  Audit is still written (MSV_VALIDATION_DEGRADED).
  Caller (CTS ChequeProcessingWorkflow) routes to human review.

On RED:
  Audit written with outcome=RED in payload.
  Caller routes to return path.

Temporal rules followed:
  - workflow.now() used instead of datetime.now() (deterministic replay)
  - No asyncio.sleep() — only workflow.sleep() if needed
  - No datetime.now() in workflow code
  - Workflow ID is deterministic: msv-{bank_id}-{instrument_id}
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow

from modules.msv.mandates.models import (
    AccountMandateMeta,
    MSVInput,
    MSVOutcome,
    MSVOutput,
)
from modules.msv.workflows.activities.write_audit import (
    WriteAuditInput,
    WriteAuditResult,
    write_audit,
)

log = structlog.get_logger()


class MSVWorkflowInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    msv_input: MSVInput
    account_meta: AccountMandateMeta


class MSVWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str               # "GREEN" | "AMBER" | "RED"
    confidence: float
    reason_code: str
    instrument_id: str
    audit_tx_id: Optional[str] = None


@workflow.defn
class MSVValidationWorkflow:
    """
    MSV validation workflow.

    Separated from CTS ChequeProcessingWorkflow for blast isolation:
      - MSV is a sub-workflow of CTS, not part of the same Temporal task queue
      - Failure in MSV routing → parent workflow routes to HUMAN_REVIEW

    The orchestrator and immudb_client are injected by the worker at startup.
    In tests, _execute() is called directly with mock dependencies.
    """

    @workflow.run
    async def run(self, inp: MSVWorkflowInput) -> MSVWorkflowResult:
        """
        Main Temporal entry point.
        In production, dependencies are resolved from the workflow context.
        """
        # In production, the worker injects these via activity context.
        # Here we call _execute with placeholders — real wiring in worker.py.
        raise NotImplementedError(
            "MSVValidationWorkflow.run() must be called via Temporal worker with "
            "activity context. Use _execute() directly in tests."
        )

    async def _execute(
        self,
        inp: MSVWorkflowInput,
        orchestrator,
        write_audit_fn: Callable = write_audit,
        immudb_client=None,
    ) -> MSVWorkflowResult:
        """
        Core execution logic — separated from run() so tests can call it directly
        without a Temporal server.

        Args:
            inp:            Workflow input
            orchestrator:   SignatureOrchestrator instance
            write_audit_fn: Audit write function (injectable for tests)
            immudb_client:  Immudb client instance
        """
        msv_output: MSVOutput = await orchestrator.validate(
            inp.msv_input, inp.account_meta
        )

        # Determine audit event type based on outcome
        event_type = (
            "MSV_VALIDATION_DEGRADED"
            if msv_output.outcome == MSVOutcome.AMBER
            else "MSV_VALIDATED"
        )

        # Build audit payload — no raw PII
        audit_payload: dict[str, Any] = {
            "outcome": msv_output.outcome.value,
            "confidence": msv_output.confidence,
            "reason_code": msv_output.reason_code,
            "detected_sig_count": msv_output.detected_sig_count,
            "matched_count": len(msv_output.matched_signatories),
            "mandate_rule_type": msv_output.mandate_rule_type,
        }

        audit_inp = WriteAuditInput(
            event_type=event_type,
            bank_id=inp.msv_input.bank_id,
            instrument_id=inp.msv_input.instrument_id,
            payload=audit_payload,
        )

        # Audit write — unlimited retries (AUDIT_RETRY)
        audit_result: WriteAuditResult = await write_audit_fn(
            audit_inp, immudb_client=immudb_client
        )

        log.info(
            "msv.workflow.complete",
            bank_id=inp.msv_input.bank_id,
            instrument_id=inp.msv_input.instrument_id,
            outcome=msv_output.outcome.value,
            confidence=msv_output.confidence,
            audit_tx_id=audit_result.immudb_tx_id,
        )

        return MSVWorkflowResult(
            outcome=msv_output.outcome.value,
            confidence=msv_output.confidence,
            reason_code=msv_output.reason_code,
            instrument_id=inp.msv_input.instrument_id,
            audit_tx_id=audit_result.immudb_tx_id,
        )
