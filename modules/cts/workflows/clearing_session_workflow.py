"""
ClearingSessionWorkflow — manages one clearing session per SB per clearing day.

Aggregates sealed lots from all Processing Units, then routes to the correct
submission path based on deployment_mode:

  SB_NGCH          → NGCHSubmissionWorkflow (direct NGCH filing)
  AGENCY_SB_RELAY  → AgencyCCWorkflow (route lots through upstream SB)

Activity sequence:
  1. seal_all_lots        — wait for every PU to seal its lot; collect lot metadata
  2. [SB_NGCH] ngch_submission   — submit aggregated file to NGCH
     [AGENCY]  agency_cc         — hand off to AgencyCCWorkflow
  3. update_session_status        — mark session SUBMITTED or EXCEPTION in DB
  4. write_audit                  — Immudb audit (ALL terminal outcomes)

Terminal states: SUBMITTED | SUBMITTED_TO_SB | EXCEPTION | EMPTY_SESSION
Workflow ID:
  SB_NGCH mode:   cts-clearsess-{bank_id}-{clearing_date}-{session_type}
  AGENCY mode:    cts-clearsess-{bank_id}-{sb_bank_id}-{clearing_date}-{session_type}
"""
from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Optional

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


class DeploymentMode(str, Enum):
    SB_NGCH         = "SB_NGCH"          # SB files directly to NGCH
    AGENCY_SB_RELAY = "AGENCY_SB_RELAY"  # Agency routes via upstream SB


class SessionType(str, Enum):
    MORNING   = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING   = "EVENING"


class ClearingSessionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    bank_id: str
    clearing_date: str               # ISO date: YYYY-MM-DD
    session_type: SessionType
    deployment_mode: DeploymentMode
    pu_ids: list[str]                # all PUs that contribute lots to this session

    # AGENCY_SB_RELAY only
    sb_connection_id: Optional[str] = None
    sb_bank_id: Optional[str] = None


class ClearingSessionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str                     # "SUBMITTED" | "SUBMITTED_TO_SB" | "EXCEPTION" | "EMPTY_SESSION"
    session_id: str
    bank_id: str
    total_instruments: int
    ngch_reference: Optional[str] = None    # NGCH ack ref (SB_NGCH) or SB relay ref (AGENCY)
    failure_reason: Optional[str] = None
    audit_written: bool = False


@workflow.defn
class ClearingSessionWorkflow:

    def workflow_id(
        self,
        bank_id: str,
        clearing_date: str,
        session_type: str,
        sb_bank_id: Optional[str] = None,
    ) -> str:
        if sb_bank_id:
            return f"cts-clearsess-{bank_id}-{sb_bank_id}-{clearing_date}-{session_type}"
        return f"cts-clearsess-{bank_id}-{clearing_date}-{session_type}"

    @workflow.run
    async def run(self, inp: ClearingSessionInput) -> ClearingSessionResult:
        from modules.cts.workflows.activities.clearing_session_activities import (
            SealAllLotsInput,
            UpdateSessionStatusInput,
            seal_all_lots,
            update_session_status,
        )
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        # Step 1: Collect sealed lots from all PUs
        seal_result = await workflow.execute_activity(
            seal_all_lots,
            SealAllLotsInput(
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                pu_ids=inp.pu_ids,
                clearing_date=inp.clearing_date,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_CBS_RETRY,
        )
        sealed_lots = seal_result.sealed_lots
        total_instruments = sum(lot.get("instrument_count", 0) for lot in sealed_lots)

        if not sealed_lots:
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_OUT_SESSION_EMPTY",
                    bank_id=inp.bank_id,
                    payload={"session_id": inp.session_id, "outcome": "EMPTY_SESSION"},
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return ClearingSessionResult(
                outcome="EMPTY_SESSION",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                total_instruments=0,
                audit_written=True,
            )

        # Step 2: Route to correct submission path
        if inp.deployment_mode == DeploymentMode.SB_NGCH:
            from modules.cts.workflows.ngch_submission_workflow import (
                NGCHSubmissionInput,
                NGCHSubmissionWorkflow,
            )
            ngch_result = await workflow.execute_child_workflow(
                NGCHSubmissionWorkflow.run,
                NGCHSubmissionInput(
                    lot_number=f"{inp.session_id}-consolidated",
                    bank_id=inp.bank_id,
                    bank_ifsc="",
                    session_id=inp.session_id,
                    clearing_date=inp.clearing_date,
                    instrument_count=total_instruments,
                ),
                id=f"cts-ngchsub-{inp.bank_id}-{inp.session_id}",
            )
            outcome = ngch_result.outcome
            ngch_reference = ngch_result.ngch_reference
            failure_reason = ngch_result.failure_reason
        else:
            from modules.cts.workflows.agency_cc_workflow import (
                AgencyCCInput,
                AgencyCCWorkflow,
            )
            agency_result = await workflow.execute_child_workflow(
                AgencyCCWorkflow.run,
                AgencyCCInput(
                    agency_id=inp.bank_id,
                    sb_connection_id=inp.sb_connection_id or "",
                    sb_bank_id=inp.sb_bank_id or "",
                    session_id=inp.session_id,
                    lot_numbers=[lot["lot_number"] for lot in sealed_lots],
                    instrument_count=total_instruments,
                    connector_type="SFTP_GENERIC",
                ),
                id=f"cts-agencycc-{inp.bank_id}-{inp.session_id}",
            )
            if agency_result.outcome == "SUBMITTED_TO_SB":
                outcome = "SUBMITTED_TO_SB"
            else:
                outcome = "EXCEPTION"
            ngch_reference = agency_result.sb_reference
            failure_reason = agency_result.failure_reason

        # Step 3: Update session status in DB
        await workflow.execute_activity(
            update_session_status,
            UpdateSessionStatusInput(
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                status=outcome,
                ngch_reference=ngch_reference,
                failure_reason=failure_reason,
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_CBS_RETRY,
        )

        # Step 4: Audit — always written
        event_type = f"CTS_OUT_SESSION_{outcome}"
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(
                event_type=event_type,
                bank_id=inp.bank_id,
                payload={
                    "session_id": inp.session_id,
                    "outcome": outcome,
                    "total_instruments": total_instruments,
                    "ngch_reference": ngch_reference,
                    "failure_reason": failure_reason,
                },
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        return ClearingSessionResult(
            outcome=outcome,
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            total_instruments=total_instruments,
            ngch_reference=ngch_reference,
            failure_reason=failure_reason,
            audit_written=True,
        )

    async def run_with_mocks(
        self,
        inp: ClearingSessionInput,
        mock_results: dict,
    ) -> ClearingSessionResult:
        """
        Testable orchestration. In production this is a Temporal @workflow.run.
        mock_results keys:
          "seal_all_lots"       — list[dict{pu_id, lot_number, instrument_count}]
          "ngch_submission"     — dict{outcome, ngch_reference}     (SB_NGCH only)
          "agency_cc"           — dict{outcome, sb_reference}       (AGENCY mode only)
          "update_session_status" — dict{status}
          "audit"               — dict{written}
        """
        # Step 1: Aggregate sealed lots from all PUs
        sealed_lots: list[dict] = mock_results["seal_all_lots"]
        total_instruments = sum(lot["instrument_count"] for lot in sealed_lots)

        if not sealed_lots:
            log.info(
                "clearing_session_workflow.empty_session",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
            )
            await self._write_audit(mock_results, "EMPTY_SESSION", inp)
            return ClearingSessionResult(
                outcome="EMPTY_SESSION",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                total_instruments=0,
                audit_written=True,
            )

        log.info(
            "clearing_session_workflow.lots_sealed",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            lot_count=len(sealed_lots),
            total_instruments=total_instruments,
        )

        # Step 2: Submit via the correct path
        if inp.deployment_mode == DeploymentMode.SB_NGCH:
            return await self._submit_sb_ngch(inp, mock_results, sealed_lots, total_instruments)
        else:
            return await self._submit_agency_relay(inp, mock_results, sealed_lots, total_instruments)

    async def _submit_sb_ngch(
        self,
        inp: ClearingSessionInput,
        mock_results: dict,
        sealed_lots: list[dict],
        total_instruments: int,
    ) -> ClearingSessionResult:
        ngch_result = mock_results["ngch_submission"]

        if ngch_result["outcome"] != "SUBMITTED":
            log.warning(
                "clearing_session_workflow.ngch_submission_failed",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                outcome=ngch_result["outcome"],
            )
            await self._write_audit(mock_results, "EXCEPTION", inp)
            return ClearingSessionResult(
                outcome="EXCEPTION",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                total_instruments=total_instruments,
                failure_reason="NGCH_SUBMISSION_FAILED",
                audit_written=True,
            )

        log.info(
            "clearing_session_workflow.submitted_to_ngch",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            total_instruments=total_instruments,
            ngch_reference=ngch_result["ngch_reference"],
        )
        await self._write_audit(mock_results, "SUBMITTED", inp)
        return ClearingSessionResult(
            outcome="SUBMITTED",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            total_instruments=total_instruments,
            ngch_reference=ngch_result["ngch_reference"],
            audit_written=True,
        )

    async def _submit_agency_relay(
        self,
        inp: ClearingSessionInput,
        mock_results: dict,
        sealed_lots: list[dict],
        total_instruments: int,
    ) -> ClearingSessionResult:
        agency_result = mock_results["agency_cc"]

        if agency_result["outcome"] != "SUBMITTED_TO_SB":
            log.warning(
                "clearing_session_workflow.agency_cc_failed",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                outcome=agency_result["outcome"],
            )
            await self._write_audit(mock_results, "EXCEPTION", inp)
            return ClearingSessionResult(
                outcome="EXCEPTION",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                total_instruments=total_instruments,
                failure_reason="AGENCY_CC_FAILED",
                audit_written=True,
            )

        log.info(
            "clearing_session_workflow.submitted_to_sb",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            sb_bank_id=inp.sb_bank_id,
            total_instruments=total_instruments,
            sb_reference=agency_result["sb_reference"],
        )
        await self._write_audit(mock_results, "SUBMITTED_TO_SB", inp)
        return ClearingSessionResult(
            outcome="SUBMITTED_TO_SB",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            total_instruments=total_instruments,
            ngch_reference=agency_result["sb_reference"],
            audit_written=True,
        )

    async def _write_audit(self, mock_results: dict, outcome: str, inp: ClearingSessionInput) -> None:
        mock_results.get("audit")  # consumed
        log.info(
            "clearing_session_workflow.audit_written",
            outcome=outcome,
            session_id=inp.session_id,
            bank_id=inp.bank_id,
        )
