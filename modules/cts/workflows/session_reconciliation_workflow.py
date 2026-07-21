"""
SessionReconciliationWorkflow — CTS Presentee Bank outward clearing.

At clearing session close, matches submitted instruments against NGCH
settlement confirmation. Generates Return Reason File (RRF) for any
instruments returned by NGCH.

Activity sequence:
  1. fetch_ngch_settlement_report  — retrieve session settlement data from NGCH
  2. match_submitted_vs_settled    — ReconciliationEngine matches NGCH vs CBS
  3. generate_rrf                  — RRF generator builds return file (only if returns exist)
  4. write_audit                   — Immudb audit (ALL terminal outcomes)

Terminal states: RECONCILED | EXCEPTIONS_FLAGGED
Workflow ID: cts-recon-{bank_id}-{session_id}  (idempotent)
"""
from __future__ import annotations

from datetime import timedelta

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger()

_CBS_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5,
)
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


class SessionReconciliationInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    bank_id: str
    bank_ifsc: str
    clearing_date: str
    submitted_count: int


class SessionReconciliationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "RECONCILED" | "EXCEPTIONS_FLAGGED"
    session_id: str
    bank_id: str
    matched_count: int
    exception_count: int
    rrf_generated: bool = False
    audit_written: bool = False


@workflow.defn
class SessionReconciliationWorkflow:
    def workflow_id(self, bank_id: str, session_id: str) -> str:
        return f"cts-recon-{bank_id}-{session_id}"

    @workflow.run
    async def run(self, inp: SessionReconciliationInput) -> SessionReconciliationResult:
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            FetchSettlementInput,
            GenerateRRFInput,
            MatchInput,
            fetch_ngch_settlement_report,
            generate_rrf,
            match_submitted_vs_settled,
        )
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        # Step 1: Fetch NGCH settlement report
        settlement = await workflow.execute_activity(
            fetch_ngch_settlement_report,
            FetchSettlementInput(
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                clearing_date=inp.clearing_date,
                bank_ifsc=inp.bank_ifsc,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_CBS_RETRY,
        )

        # Step 2: Match submitted vs settled
        recon = await workflow.execute_activity(
            match_submitted_vs_settled,
            MatchInput(
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                settlement_rows=settlement.rows,
                submitted_count=inp.submitted_count,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_CBS_RETRY,
        )

        # Step 3: Generate RRF if there are exceptions
        rrf = await workflow.execute_activity(
            generate_rrf,
            GenerateRRFInput(
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                bank_ifsc=inp.bank_ifsc,
                clearing_date=inp.clearing_date,
                exception_instruments=recon.exception_instruments,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_CBS_RETRY,
        )

        # Step 4: Audit — always written
        event_type = (
            "CTS_OUT_RECON_COMPLETE" if recon.outcome == "RECONCILED"
            else "CTS_OUT_RECON_EXCEPTIONS"
        )
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(
                event_type=event_type,
                bank_id=inp.bank_id,
                payload={
                    "session_id": inp.session_id,
                    "outcome": recon.outcome,
                    "matched_count": recon.matched_count,
                    "exception_count": recon.exception_count,
                    "rrf_generated": rrf.generated,
                    "rrf_path": rrf.rrf_path,
                },
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        return SessionReconciliationResult(
            outcome=recon.outcome,
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            matched_count=recon.matched_count,
            exception_count=recon.exception_count,
            rrf_generated=rrf.generated,
            audit_written=True,
        )

    async def run_with_mocks(
        self,
        inp: SessionReconciliationInput,
        mock_results: dict,
    ) -> SessionReconciliationResult:
        # Step 1: Fetch NGCH settlement report
        settlement_report = mock_results["settlement_report"]  # noqa: F841

        # Step 2: Match submitted vs settled
        recon = mock_results["reconciliation"]
        matched_count = getattr(recon, "matched_count", 0)
        exception_count = getattr(recon, "exception_count", 0)
        outcome = getattr(recon, "outcome", "RECONCILED")

        # Step 3: Generate RRF (only if returns/exceptions exist)
        rrf = mock_results["rrf"]
        rrf_generated = getattr(rrf, "generated", False)

        log.info(
            "session_reconciliation_workflow.complete",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            outcome=outcome,
            matched_count=matched_count,
            exception_count=exception_count,
            rrf_generated=rrf_generated,
        )

        # Step 4: Audit — write for ALL outcomes
        await self._write_audit(mock_results, outcome, inp)

        return SessionReconciliationResult(
            outcome=outcome,
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            matched_count=matched_count,
            exception_count=exception_count,
            rrf_generated=rrf_generated,
            audit_written=True,
        )

    async def _write_audit(self, mock_results: dict, outcome: str, inp: SessionReconciliationInput) -> None:
        audit_result = mock_results.get("audit")  # noqa: F841
        log.info(
            "session_reconciliation_workflow.audit_written",
            outcome=outcome,
            session_id=inp.session_id,
            bank_id=inp.bank_id,
        )
