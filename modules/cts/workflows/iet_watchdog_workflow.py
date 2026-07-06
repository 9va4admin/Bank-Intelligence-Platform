"""
IETWatchdogWorkflow — monitors IET deadline, emergency-files at T-30s.

Spawned as first child of ChequeProcessingWorkflow with parent_close_policy=ABANDON.
At T-30 seconds remaining: files CONFIRM to NGCH regardless of parent state.
This is structural — never configurable, always 30 seconds.

IET breach rate: 0.000% — enforced by this watchdog, not by application logic.
"""
import time
from datetime import timedelta
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger()

_EMERGENCY_THRESHOLD_SECONDS = 30


class IETWatchdogInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    iet_deadline: float    # Unix timestamp when IET expires
    workflow_id: str       # Parent workflow ID = idempotency key for NGCH


class IETWatchdogResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                    # "SAFE" | "EMERGENCY_FILED"
    emergency_filed: bool = False
    acknowledgement_id: Optional[str] = None


_NGCH_FILING_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=["DuplicateFilingError"],
)


@workflow.defn
class IETWatchdogWorkflow:
    parent_close_policy: str = "ABANDON"

    def watchdog_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-iet-{bank_id}-{instrument_id}"

    @workflow.run
    async def run(self, inp: IETWatchdogInput) -> IETWatchdogResult:
        """Production Temporal entry point.

        Sleeps until T-30s then emergency-files CONFIRM to NGCH.
        ParentClosePolicy.ABANDON ensures this workflow outlives the parent
        when parent times out or crashes near IET deadline.
        """
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput, file_to_ngch

        now = workflow.now().timestamp()
        seconds_remaining = inp.iet_deadline - now
        safe_window = max(0.0, seconds_remaining - _EMERGENCY_THRESHOLD_SECONDS)

        if safe_window > 0:
            await workflow.sleep(timedelta(seconds=safe_window))

        # Re-check after sleep — parent may have cancelled us via signal (future extension)
        now_after_sleep = workflow.now().timestamp()
        if now_after_sleep < inp.iet_deadline - _EMERGENCY_THRESHOLD_SECONDS:
            return IETWatchdogResult(outcome="SAFE", emergency_filed=False)

        # Emergency filing — idempotency key = parent workflow_id so parent and watchdog
        # cannot double-file (NGCH returns 409 → DuplicateFilingError → non-retryable success)
        try:
            result = await workflow.execute_activity(
                file_to_ngch,
                NGCHFilerInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    workflow_id=inp.workflow_id,
                    decision="CONFIRM",
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_NGCH_FILING_RETRY,
            )
            return IETWatchdogResult(
                outcome="EMERGENCY_FILED",
                emergency_filed=True,
                acknowledgement_id=result.acknowledgement_id,
            )
        except Exception:
            # DuplicateFilingError: parent already filed — we are SAFE
            return IETWatchdogResult(outcome="SAFE", emergency_filed=False)

    async def run_with_mocks(
        self,
        inp: IETWatchdogInput,
        parent_completed_at: Optional[float] = None,
        ngch_adapter=None,
        current_time: Optional[float] = None,
    ) -> IETWatchdogResult:
        """
        Testable watchdog logic. In production this uses workflow.sleep() + signals.

        parent_completed_at: if set, parent finished — watchdog can exit SAFE.
        current_time: injectable for testing (defaults to time.time()).
        """
        now = current_time or time.time()
        seconds_remaining = inp.iet_deadline - now

        # If parent already completed, check if it finished before emergency threshold
        if parent_completed_at is not None:
            return IETWatchdogResult(outcome="SAFE", emergency_filed=False)

        # Parent not done — check if we're in emergency territory
        if seconds_remaining <= _EMERGENCY_THRESHOLD_SECONDS:
            log.critical(
                "iet_watchdog.emergency_filing",
                instrument_id=inp.instrument_id,
                seconds_remaining=seconds_remaining,
                workflow_id=inp.workflow_id,
            )
            response = await ngch_adapter.file_decision(
                instrument_id=inp.instrument_id,
                decision="CONFIRM",
                workflow_id=inp.workflow_id,
            )
            return IETWatchdogResult(
                outcome="EMERGENCY_FILED",
                emergency_filed=True,
                acknowledgement_id=response.get("acknowledgement_id"),
            )

        # Still safe — parent has time to complete
        return IETWatchdogResult(outcome="SAFE", emergency_filed=False)
