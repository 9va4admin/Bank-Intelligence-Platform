"""
MSVValidationWorkflow — Temporal workflow for multi-signature validation.

Workflow ID: msv-{bank_id}-{instrument_id}  (deterministic, exactly-once)

Activity sequence:
  1. orchestrate_msv_validation → MSVOutput  (I/O: detector, embeddings, registry, BRE)
  2. write_audit → Immudb  (AUDIT_RETRY, unlimited)

On AMBER (vault miss or orchestrator unavailable):
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
  - All I/O inside execute_activity() — workflow itself is deterministic
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy

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

# Standard retry policies for MSV activities
_MSV_ACTIVITY_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
)
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


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
        Main Temporal entry point — dispatches to registered activities.

        Dependencies (orchestrator, immudb_client) are provided at worker
        registration time via BoundMSVActivities — never passed directly here.
        In tests, use _execute() with injected mocks (no Temporal server needed).
        """
        from modules.msv.workflows.activities.orchestrate import (
            orchestrate_msv_validation,
        )

        # ── 1. Run MSV orchestration (detector → embed → BRE) ────────────────
        raw_output = await workflow.execute_activity(
            orchestrate_msv_validation,
            args=[inp],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_MSV_ACTIVITY_RETRY,
        )
        # Temporal's default converter deserialises Pydantic models as dicts
        # in the installed temporalio version (no pydantic converter shipped).
        msv_output = (
            MSVOutput.model_validate(raw_output)
            if isinstance(raw_output, dict)
            else raw_output
        )

        # ── 2. Determine audit event type ────────────────────────────────────
        event_type = (
            "MSV_VALIDATION_DEGRADED"
            if msv_output.outcome == MSVOutcome.AMBER
            else "MSV_VALIDATED"
        )

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

        # ── 3. Write audit (unlimited retries — must succeed) ────────────────
        raw_audit = await workflow.execute_activity(
            write_audit,
            args=[audit_inp],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )
        audit_result = (
            WriteAuditResult.model_validate(raw_audit)
            if isinstance(raw_audit, dict)
            else raw_audit
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
