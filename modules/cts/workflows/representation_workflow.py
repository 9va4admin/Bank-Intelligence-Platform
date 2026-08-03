"""
ChequeRepresentationWorkflow — RBI/NPCI 24-hour re-presentation mandate.

When NGCH returns an instrument with a RE_PRESENTATION_CODE, the collecting
bank must fix the issue and re-present in the next clearing cycle (max 24
hours, excluding holidays). This workflow manages that lifecycle.

Activity sequence:
  1. notify_representation_pending  — alert ops that fix + re-presentation is needed
  2. [wait for approve_representation signal or window timeout]
  3a. If approved → re_submit_to_ngch_for_representation → write_audit (SUBMITTED)
  3b. If timeout  → write_audit (EXPIRED)
  3c. If NGCH fails → write_audit (FAILED)

Terminal states: REPRESENTATION_SUBMITTED | REPRESENTATION_EXPIRED | REPRESENTATION_FAILED
Workflow ID: cts-represent-{bank_id}-{instrument_id}
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger()

_NOTIFY_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
)
_NGCH_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=["DuplicateFilingError"],
)
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


class ChequeRepresentationInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    bank_id: str
    bank_ifsc: str
    return_reason_code: str
    original_session_id: str
    clearing_date: str


class ChequeRepresentationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str                        # REPRESENTATION_SUBMITTED | REPRESENTATION_EXPIRED | REPRESENTATION_FAILED
    instrument_id: str
    bank_id: str
    representation_submitted: bool
    audit_written: bool
    ngch_reference: Optional[str] = None


@workflow.defn
class ChequeRepresentationWorkflow:
    def __init__(self) -> None:
        self._approved: bool = False

    def workflow_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-represent-{bank_id}-{instrument_id}"

    @workflow.signal
    async def approve_representation(self) -> None:
        self._approved = True

    @workflow.run
    async def run(self, inp: ChequeRepresentationInput) -> ChequeRepresentationResult:
        from modules.cts.workflows.activities.representation_activities import (
            NotifyRepresentationInput,
            ResubmitNgchInput,
            notify_representation_pending,
            re_submit_to_ngch_for_representation,
        )
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit
        from shared.config.config_service import config_service

        cts_config = await config_service.get_cts_config(inp.bank_id)
        representation_window_hours: int = cts_config.get("representation_window_hours", 24)

        # Step 1: Notify ops that re-presentation is pending
        await workflow.execute_activity(
            notify_representation_pending,
            NotifyRepresentationInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                return_reason_code=inp.return_reason_code,
                original_session_id=inp.original_session_id,
                clearing_date=inp.clearing_date,
                representation_window_hours=representation_window_hours,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_NOTIFY_RETRY,
        )

        # Step 2: Wait for approval signal or window timeout
        approved = await workflow.wait_condition(
            lambda: self._approved,
            timeout=timedelta(hours=representation_window_hours),
        )

        if not approved:
            # Timeout — ops did not act within the window
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_OUT_REPRESENTATION_EXPIRED",
                    bank_id=inp.bank_id,
                    payload={
                        "instrument_id": inp.instrument_id,
                        "return_reason_code": inp.return_reason_code,
                        "original_session_id": inp.original_session_id,
                        "representation_window_hours": representation_window_hours,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return ChequeRepresentationResult(
                outcome="REPRESENTATION_EXPIRED",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                representation_submitted=False,
                audit_written=True,
            )

        # Step 3: Re-submit to NGCH
        resubmit = await workflow.execute_activity(
            re_submit_to_ngch_for_representation,
            ResubmitNgchInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                bank_ifsc=inp.bank_ifsc,
                return_reason_code=inp.return_reason_code,
                original_session_id=inp.original_session_id,
                clearing_date=inp.clearing_date,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_NGCH_RETRY,
        )

        if not resubmit.submitted:
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_OUT_REPRESENTATION_FAILED",
                    bank_id=inp.bank_id,
                    payload={
                        "instrument_id": inp.instrument_id,
                        "return_reason_code": inp.return_reason_code,
                        "original_session_id": inp.original_session_id,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return ChequeRepresentationResult(
                outcome="REPRESENTATION_FAILED",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                representation_submitted=False,
                audit_written=True,
            )

        # Step 4: Audit success
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(
                event_type="CTS_OUT_REPRESENTATION_SUBMITTED",
                bank_id=inp.bank_id,
                payload={
                    "instrument_id": inp.instrument_id,
                    "return_reason_code": inp.return_reason_code,
                    "original_session_id": inp.original_session_id,
                    "ngch_reference": resubmit.ngch_reference,
                },
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )
        return ChequeRepresentationResult(
            outcome="REPRESENTATION_SUBMITTED",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            representation_submitted=True,
            audit_written=True,
            ngch_reference=resubmit.ngch_reference,
        )

    async def run_with_mocks(
        self,
        inp: ChequeRepresentationInput,
        mock_results: dict,
    ) -> ChequeRepresentationResult:
        approved: bool = mock_results.get("approved", True)
        expired: bool = mock_results.get("expired", False)

        # Step 1: notify (mock — just log)
        log.info(
            "representation_workflow.notify",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            return_reason_code=inp.return_reason_code,
        )

        # Step 2: check signal / timeout
        if expired or not approved:
            log.info(
                "representation_workflow.expired",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            )
            return ChequeRepresentationResult(
                outcome="REPRESENTATION_EXPIRED",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                representation_submitted=False,
                audit_written=True,
            )

        # Step 3: re-submit
        resubmit = mock_results.get("resubmit")
        submitted: bool = getattr(resubmit, "submitted", False) if resubmit else False
        ngch_reference: Optional[str] = getattr(resubmit, "ngch_reference", None) if resubmit else None

        if not submitted:
            log.info(
                "representation_workflow.failed",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            )
            return ChequeRepresentationResult(
                outcome="REPRESENTATION_FAILED",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                representation_submitted=False,
                audit_written=True,
            )

        log.info(
            "representation_workflow.submitted",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            ngch_reference=ngch_reference,
        )
        return ChequeRepresentationResult(
            outcome="REPRESENTATION_SUBMITTED",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            representation_submitted=True,
            audit_written=True,
            ngch_reference=ngch_reference,
        )
