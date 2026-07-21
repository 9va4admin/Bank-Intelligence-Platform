"""
SBInwardForwardingWorkflow — routes inward instruments from SB relay to PUs.

In AGENCY_SB_RELAY mode, inward cheques (drawn on SMBs the agency serves)
arrive from the upstream Sponsor Bank via Kafka:
  cts.sb.relay.inward.{agency_id}.{sb_bank_id}

This workflow receives that batch, resolves each instrument's target PU via
the CRL service, and publishes each instrument to the correct PU's inward queue
(cts.inward.{bank_id}) with original_ngch_ts preserved for IET enforcement.

Activity sequence:
  1. crl_lookups          — resolve drawee_ifsc → pu_id for every instrument
  2. publish_to_pu_queues — fan-out: each instrument → cts.inward.{bank_id}.{pu_id}
  3. write_audit          — Immudb audit (ALL terminal outcomes)

Terminal states: ROUTED | PARTIAL_FAILURE | FAILED | EMPTY
Workflow ID: cts-sbinward-{agency_id}-{sb_bank_id}-{session_id}

IET note: original_ngch_ts (the timestamp when NGCH first received the cheque
at the SB) is passed through unchanged. The receiving ChequeProcessingWorkflow
uses this as the IET start time, not the time of relay receipt.
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


class SBInwardForwardingInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    sb_bank_id: str
    session_id: str
    instruments: list[dict]          # each: {instrument_id, drawee_ifsc, original_ngch_ts, ...}


class SBInwardForwardingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str                     # "ROUTED" | "PARTIAL_FAILURE" | "FAILED" | "EMPTY"
    agency_id: str
    session_id: str
    routed_count: int
    failed_count: int
    audit_written: bool = False


@workflow.defn
class SBInwardForwardingWorkflow:

    def workflow_id(self, agency_id: str, sb_bank_id: str, session_id: str) -> str:
        return f"cts-sbinward-{agency_id}-{sb_bank_id}-{session_id}"

    @workflow.run
    async def run(self, inp: SBInwardForwardingInput) -> SBInwardForwardingResult:
        from modules.cts.workflows.activities.sb_relay_activities import (
            CRLBatchInput,
            PublishToPUInput,
            publish_to_pu_queues,
            resolve_crl_batch,
        )
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        if not inp.instruments:
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_SB_INWARD_EMPTY",
                    bank_id=inp.agency_id,
                    payload={"session_id": inp.session_id, "outcome": "EMPTY"},
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return SBInwardForwardingResult(
                outcome="EMPTY",
                agency_id=inp.agency_id,
                session_id=inp.session_id,
                routed_count=0,
                failed_count=0,
                audit_written=True,
            )

        # Step 1: Resolve IFSC → PU IDs
        crl_result = await workflow.execute_activity(
            resolve_crl_batch,
            CRLBatchInput(
                agency_id=inp.agency_id,
                instruments=inp.instruments,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_CBS_RETRY,
        )

        resolved = crl_result.resolved
        routed_count = sum(1 for r in resolved if r.get("success"))
        failed_count = sum(1 for r in resolved if not r.get("success"))

        # Step 2: Publish to PU inward queues
        await workflow.execute_activity(
            publish_to_pu_queues,
            PublishToPUInput(
                agency_id=inp.agency_id,
                resolved_instruments=resolved,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_CBS_RETRY,
        )

        outcome = "ROUTED" if failed_count == 0 else (
            "FAILED" if routed_count == 0 else "PARTIAL_FAILURE"
        )

        # Step 3: Audit — always written
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(
                event_type=f"CTS_SB_INWARD_{outcome}",
                bank_id=inp.agency_id,
                payload={
                    "session_id": inp.session_id,
                    "sb_bank_id": inp.sb_bank_id,
                    "outcome": outcome,
                    "routed_count": routed_count,
                    "failed_count": failed_count,
                },
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        return SBInwardForwardingResult(
            outcome=outcome,
            agency_id=inp.agency_id,
            session_id=inp.session_id,
            routed_count=routed_count,
            failed_count=failed_count,
            audit_written=True,
        )

    async def run_with_mocks(
        self,
        inp: SBInwardForwardingInput,
        mock_results: dict,
    ) -> SBInwardForwardingResult:
        """
        Testable orchestration. In production this is a Temporal @workflow.run.
        mock_results keys:
          "crl_lookups"        — list[dict{instrument_id, pu_id, success, error?}]
          "publish_to_pu_queues" — dict{published_count, events?}
          "audit"              — dict{written}
        """
        if not inp.instruments:
            await self._write_audit(mock_results, "EMPTY", inp)
            return SBInwardForwardingResult(
                outcome="EMPTY",
                agency_id=inp.agency_id,
                session_id=inp.session_id,
                routed_count=0,
                failed_count=0,
                audit_written=True,
            )

        # Step 1: CRL resolution for every instrument
        crl_results: list[dict] = mock_results["crl_lookups"]

        routed_count = sum(1 for r in crl_results if r.get("success"))
        failed_count = sum(1 for r in crl_results if not r.get("success"))

        log.info(
            "sb_inward_forwarding_workflow.crl_resolved",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
            total=len(crl_results),
            routed=routed_count,
            failed=failed_count,
        )

        # Step 2: Publish routed instruments to PU inward queues
        # original_ngch_ts is carried through — IET deadline is the SB's NGCH receipt time
        mock_results.get("publish_to_pu_queues")  # consumed

        # Step 3: Audit
        if routed_count == 0:
            outcome = "FAILED"
        elif failed_count > 0:
            outcome = "PARTIAL_FAILURE"
        else:
            outcome = "ROUTED"

        await self._write_audit(mock_results, outcome, inp)

        log.info(
            "sb_inward_forwarding_workflow.complete",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
            outcome=outcome,
            routed_count=routed_count,
            failed_count=failed_count,
        )

        return SBInwardForwardingResult(
            outcome=outcome,
            agency_id=inp.agency_id,
            session_id=inp.session_id,
            routed_count=routed_count,
            failed_count=failed_count,
            audit_written=True,
        )

    async def _write_audit(
        self, mock_results: dict, outcome: str, inp: SBInwardForwardingInput
    ) -> None:
        mock_results.get("audit")  # consumed
        log.info(
            "sb_inward_forwarding_workflow.audit_written",
            outcome=outcome,
            agency_id=inp.agency_id,
            session_id=inp.session_id,
        )
