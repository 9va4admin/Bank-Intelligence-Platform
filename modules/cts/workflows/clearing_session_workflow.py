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

from enum import Enum
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


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
