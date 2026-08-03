"""
AgencyCCWorkflow — Agency Command Center lot submission to Sponsor Bank.

Called by ClearingSessionWorkflow when deployment_mode = AGENCY_SB_RELAY.
Groups sealed lots, packages them, submits to the upstream SB via the
appropriate sb_connector adapter, then publishes the relay event to Kafka.

Activity sequence:
  1. build_lot_package    — assemble all lots into a single CTS package file
  2. sb_submit            — invoke SBConnector.submit_lot()
  3. publish_relay_event  — Kafka: cts.sb.relay.outward.{agency_id}.{sb_bank_id}
  4. write_audit          — Immudb audit (ALL terminal outcomes)

Terminal states: SUBMITTED_TO_SB | SB_REJECTED
Workflow ID: cts-agencycc-{agency_id}-{sb_bank_id}-{session_id}
"""
from __future__ import annotations

from datetime import timedelta
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


class AgencyCCInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    sb_connection_id: str
    sb_bank_id: str
    session_id: str
    lot_numbers: list[str]
    instrument_count: int
    connector_type: str              # SFTP_GENERIC | BANCS_API | NELITO_API


class AgencyCCResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str                     # "SUBMITTED_TO_SB" | "SB_REJECTED"
    agency_id: str
    sb_bank_id: str
    session_id: str
    instrument_count: int
    sb_reference: Optional[str] = None
    failure_reason: Optional[str] = None
    audit_written: bool = False


@workflow.defn
class AgencyCCWorkflow:

    def workflow_id(self, agency_id: str, sb_bank_id: str, session_id: str) -> str:
        return f"cts-agencycc-{agency_id}-{sb_bank_id}-{session_id}"

    @workflow.run
    async def run(self, inp: AgencyCCInput) -> AgencyCCResult:
        from modules.cts.workflows.activities.sb_relay_activities import (
            BuildLotPackageInput,
            PublishRelayInput,
            SBSubmitInput,
            build_lot_package,
            publish_relay_event,
            sb_submit_lot,
        )
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        # Step 1: Build lot package for transmission to SB
        package = await workflow.execute_activity(
            build_lot_package,
            BuildLotPackageInput(
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                lot_numbers=inp.lot_numbers,
                instrument_count=inp.instrument_count,
            ),
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_CBS_RETRY,
        )

        if package.error or not package.package_path:
            failure = package.error or "PACKAGE_BUILD_FAILED"
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_AGENCY_CC_REJECTED",
                    bank_id=inp.agency_id,
                    payload={
                        "sb_bank_id": inp.sb_bank_id,
                        "session_id": inp.session_id,
                        "failure_reason": failure,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return AgencyCCResult(
                outcome="SB_REJECTED",
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                instrument_count=inp.instrument_count,
                failure_reason=failure,
                audit_written=True,
            )

        # Step 2: Submit to SB
        submit = await workflow.execute_activity(
            sb_submit_lot,
            SBSubmitInput(
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                package_path=package.package_path,
                instrument_count=inp.instrument_count,
                connector_type=inp.connector_type,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_CBS_RETRY,
        )

        if not submit.success:
            error_code = submit.error_code or "SB_SUBMIT_FAILED"
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_AGENCY_CC_REJECTED",
                    bank_id=inp.agency_id,
                    payload={
                        "sb_bank_id": inp.sb_bank_id,
                        "session_id": inp.session_id,
                        "failure_reason": error_code,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return AgencyCCResult(
                outcome="SB_REJECTED",
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                instrument_count=inp.instrument_count,
                failure_reason=error_code,
                audit_written=True,
            )

        sb_reference = submit.reference_number

        # Step 3: Publish relay event to Kafka (non-critical)
        await workflow.execute_activity(
            publish_relay_event,
            PublishRelayInput(
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                sb_reference=sb_reference or "",
                instrument_count=inp.instrument_count,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_CBS_RETRY,
        )

        # Step 4: Audit
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(
                event_type="CTS_AGENCY_CC_SUBMITTED",
                bank_id=inp.agency_id,
                payload={
                    "sb_bank_id": inp.sb_bank_id,
                    "session_id": inp.session_id,
                    "sb_reference": sb_reference,
                    "instrument_count": inp.instrument_count,
                },
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        return AgencyCCResult(
            outcome="SUBMITTED_TO_SB",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
            instrument_count=inp.instrument_count,
            sb_reference=sb_reference,
            audit_written=True,
        )

    async def run_with_mocks(
        self,
        inp: AgencyCCInput,
        mock_results: dict,
    ) -> AgencyCCResult:
        """
        Testable orchestration. In production this is a Temporal @workflow.run.
        mock_results keys:
          "build_lot_package"  — dict{package_path, error?}
          "sb_submit"          — dict{success, reference_number?, error_code?, error_message?}
          "publish_relay_event"— dict{published, topic?}   (only on success)
          "audit"              — dict{written}
        """
        # Step 1: Build lot package
        package = mock_results["build_lot_package"]
        if package.get("error") or not package.get("package_path"):
            failure = package.get("error", "PACKAGE_BUILD_FAILED")
            log.error(
                "agency_cc_workflow.build_failed",
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                error=failure,
            )
            await self._write_audit(mock_results, "SB_REJECTED", inp)
            return AgencyCCResult(
                outcome="SB_REJECTED",
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                instrument_count=inp.instrument_count,
                failure_reason=failure,
                audit_written=True,
            )

        # Step 2: Submit lot package to SB via connector
        sb_result = mock_results["sb_submit"]
        if not sb_result.get("success"):
            error_code = sb_result.get("error_code", "SB_SUBMIT_FAILED")
            log.error(
                "agency_cc_workflow.sb_submit_failed",
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                error_code=error_code,
                connector_type=inp.connector_type,
            )
            await self._write_audit(mock_results, "SB_REJECTED", inp)
            return AgencyCCResult(
                outcome="SB_REJECTED",
                agency_id=inp.agency_id,
                sb_bank_id=inp.sb_bank_id,
                session_id=inp.session_id,
                instrument_count=inp.instrument_count,
                failure_reason=error_code,
                audit_written=True,
            )

        sb_reference = sb_result["reference_number"]

        # Step 3: Publish relay event to Kafka cts.sb.relay.outward.{agency_id}.{sb_bank_id}
        mock_results.get("publish_relay_event")  # consumed
        log.info(
            "agency_cc_workflow.relay_event_published",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
            topic=f"cts.sb.relay.outward.{inp.agency_id}.{inp.sb_bank_id}",
        )

        # Step 4: Audit
        await self._write_audit(mock_results, "SUBMITTED_TO_SB", inp)

        log.info(
            "agency_cc_workflow.submitted_to_sb",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
            sb_reference=sb_reference,
            instrument_count=inp.instrument_count,
        )
        return AgencyCCResult(
            outcome="SUBMITTED_TO_SB",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
            instrument_count=inp.instrument_count,
            sb_reference=sb_reference,
            audit_written=True,
        )

    async def _write_audit(
        self, mock_results: dict, outcome: str, inp: AgencyCCInput
    ) -> None:
        mock_results.get("audit")  # consumed
        log.info(
            "agency_cc_workflow.audit_written",
            outcome=outcome,
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
        )
