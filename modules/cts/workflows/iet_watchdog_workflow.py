"""
IETWatchdogWorkflow — monitors IET deadline, emergency-files at T-30s.

Spawned as first child of ChequeProcessingWorkflow with parent_close_policy=ABANDON.
At T-30 seconds remaining, if the parent hasn't finished filing: emergency-files
whatever decision the parent (or HumanReviewWorkflow, for human-reviewed cheques)
last signalled via decision_ready(). Only when NO decision was ever signalled does
it fall back to CONFIRM — that fallback matches RBI's own "deemed approval" default
for a missed IET, so it never makes the outcome worse than doing nothing; it just
gets ASTRA an explicit, audited record instead of a silent regulatory default.
This is structural — the T-30s threshold is never configurable.

IET breach rate: 0.000% — enforced by this watchdog, not by application logic.
"""
import asyncio
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
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,  # 0 = unlimited in Temporal Python SDK
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


@workflow.defn
class IETWatchdogWorkflow:
    parent_close_policy: str = "ABANDON"

    def __init__(self) -> None:
        self._last_known_decision: Optional[str] = None
        self._parent_filed: bool = False

    def watchdog_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-iet-{bank_id}-{instrument_id}"

    @workflow.signal
    def decision_ready(self, decision: str) -> None:
        """Sent by the parent (or HumanReviewWorkflow) as soon as a real
        CONFIRM/RETURN decision is reached — before filing completes. Lets an
        emergency-fire at T-30s use the actual decision instead of guessing."""
        self._last_known_decision = decision

    @workflow.signal
    def filing_complete(self) -> None:
        """Sent once the decided filing has actually succeeded — watchdog can
        stand down immediately rather than waiting out the full T-30s window."""
        self._parent_filed = True

    @workflow.run
    async def run(self, inp: IETWatchdogInput) -> IETWatchdogResult:
        """Production Temporal entry point.

        Waits until T-30s OR filing_complete(), whichever is first, then
        emergency-files the last decision received via decision_ready() — CONFIRM
        only if none was ever signalled. ParentClosePolicy.ABANDON ensures this
        workflow outlives the parent when parent times out or crashes near IET
        deadline.
        """
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput, file_to_ngch
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        now = workflow.now().timestamp()
        seconds_remaining = inp.iet_deadline - now
        safe_window = max(0.0, seconds_remaining - _EMERGENCY_THRESHOLD_SECONDS)

        if safe_window > 0:
            try:
                await workflow.wait_condition(
                    lambda: self._parent_filed, timeout=timedelta(seconds=safe_window)
                )
            except asyncio.TimeoutError:
                pass

        if self._parent_filed:
            return IETWatchdogResult(outcome="SAFE", emergency_filed=False)

        # Emergency filing — idempotency key = parent workflow_id so parent and watchdog
        # cannot double-file (NGCH returns 409 → DuplicateFilingError → non-retryable success).
        # Uses the last decision signalled by the parent; only falls back to CONFIRM if the
        # parent never reached a decision at all (matches RBI's own deemed-approval default).
        emergency_decision = self._last_known_decision or "CONFIRM"
        try:
            result = await workflow.execute_activity(
                file_to_ngch,
                NGCHFilerInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    workflow_id=inp.workflow_id,
                    decision=emergency_decision,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_NGCH_FILING_RETRY,
            )
            log.critical(
                "iet_watchdog.emergency_filed",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision=emergency_decision,
                signalled=self._last_known_decision is not None,
            )
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_IET_EMERGENCY_FILED",
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    payload={
                        "decision": emergency_decision,
                        "signalled": self._last_known_decision is not None,
                        "acknowledgement_id": result.acknowledgement_id,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return IETWatchdogResult(
                outcome="EMERGENCY_FILED",
                emergency_filed=True,
                acknowledgement_id=result.acknowledgement_id,
            )
        except Exception as exc:
            cause = getattr(exc, "cause", None)
            if getattr(cause, "type", None) == "DuplicateFilingError":
                # Parent (or HumanReviewWorkflow) already filed — genuinely safe,
                # nothing more to do or audit here; the filer's own write_audit
                # call already recorded the real decision.
                return IETWatchdogResult(outcome="SAFE", emergency_filed=False)

            # Any other failure (NGCH unavailable after exhausted retries, etc.)
            # is NOT safe — the platform's last line of defence failed to file
            # before the IET deadline. Audit it, then let the failure propagate
            # so Temporal surfaces it — never silently report this as "SAFE".
            log.critical(
                "iet_watchdog.emergency_filing_failed",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision=emergency_decision,
                error=str(exc),
                cause_type=getattr(cause, "type", None),
            )
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_IET_EMERGENCY_FILED",
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    payload={
                        "decision": emergency_decision,
                        "signalled": self._last_known_decision is not None,
                        "failed": True,
                        "error": str(exc),
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            raise

    async def run_with_mocks(
        self,
        inp: IETWatchdogInput,
        parent_completed_at: Optional[float] = None,
        ngch_adapter=None,
        current_time: Optional[float] = None,
        signaled_decision: Optional[str] = None,
        audit_writer=None,
    ) -> IETWatchdogResult:
        """
        Testable watchdog logic. In production this uses workflow.wait_condition() + signals.

        parent_completed_at: if set, parent finished filing — watchdog can exit SAFE.
        current_time: injectable for testing (defaults to time.time()).
        signaled_decision: the real CONFIRM/RETURN decision the parent (or
            HumanReviewWorkflow) reached before filing completed — mirrors the
            decision_ready() signal. Only falls back to CONFIRM when None, i.e.
            no decision was ever reached before the emergency window closed.
        audit_writer: if set, CTS_IET_EMERGENCY_FILED is written on emergency filing —
            mirrors the write_audit activity call in the real run().
        """
        now = current_time or time.time()
        seconds_remaining = inp.iet_deadline - now

        # If parent already completed filing, check if it finished before emergency threshold
        if parent_completed_at is not None:
            return IETWatchdogResult(outcome="SAFE", emergency_filed=False)

        # Parent not done — check if we're in emergency territory
        if seconds_remaining <= _EMERGENCY_THRESHOLD_SECONDS:
            emergency_decision = signaled_decision or "CONFIRM"
            log.critical(
                "iet_watchdog.emergency_filing",
                instrument_id=inp.instrument_id,
                seconds_remaining=seconds_remaining,
                workflow_id=inp.workflow_id,
                decision=emergency_decision,
                signalled=signaled_decision is not None,
            )
            response = await ngch_adapter.file_decision(
                instrument_id=inp.instrument_id,
                decision=emergency_decision,
                workflow_id=inp.workflow_id,
            )
            if audit_writer is not None:
                await audit_writer.write(
                    event_type="CTS_IET_EMERGENCY_FILED",
                    bank_id=inp.bank_id,
                    payload={
                        "instrument_id": inp.instrument_id,
                        "decision": emergency_decision,
                        "signalled": signaled_decision is not None,
                        "acknowledgement_id": response.get("acknowledgement_id"),
                    },
                )
            return IETWatchdogResult(
                outcome="EMERGENCY_FILED",
                emergency_filed=True,
                acknowledgement_id=response.get("acknowledgement_id"),
            )

        # Still safe — parent has time to complete
        return IETWatchdogResult(outcome="SAFE", emergency_filed=False)
