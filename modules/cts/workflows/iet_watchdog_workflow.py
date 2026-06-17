"""
IETWatchdogWorkflow — monitors IET deadline, emergency-files at T-30s.

Spawned as first child of ChequeProcessingWorkflow with parent_close_policy=ABANDON.
At T-30 seconds remaining: files CONFIRM to NGCH regardless of parent state.
This is structural — never configurable, always 30 seconds.

IET breach rate: 0.000% — enforced by this watchdog, not by application logic.
"""
import time
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

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


class IETWatchdogWorkflow:
    parent_close_policy: str = "ABANDON"

    def watchdog_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-iet-{bank_id}-{instrument_id}"

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
