"""
HoldEscalationWorkflow — time-based escalation chain while an instrument is on hold.

Three escalation checkpoints (all times relative to IET deadline):
  T+30min (from hold placement): if no branch note yet → send reminder to branch
  T-60min (before IET expiry): if hold still active → CRITICAL alert to ops_manager
  T-5min  (before IET expiry): P0 alert bypassing debouncer → immediate action required

The workflow exits cleanly when:
  a) The `released` signal is received (hold was released before all checkpoints fire), or
  b) All three checkpoints have fired.

IET safety: This workflow NEVER files to NGCH. The IETWatchdogWorkflow (running as a sibling
of ChequeProcessingWorkflow) owns the T-30s emergency filing. This workflow is notification-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import structlog
    log = structlog.get_logger()


@dataclass
class HoldEscalationInput:
    instrument_id: str
    bank_id: str
    reviewer_id: str
    iet_deadline: float          # Unix timestamp — IET deadline (immutable)
    held_at: float               # Unix timestamp — when hold was placed
    branch_email: Optional[str] = None
    ops_manager_email: Optional[str] = None


_NOTIFY_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
)


@workflow.defn(name="HoldEscalationWorkflow")
class HoldEscalationWorkflow:
    """
    Escalation chain for an instrument on hold.
    Cancelled via `released` signal when the hold is cleared by ops_reviewer.
    """

    def __init__(self) -> None:
        self._released = False

    @workflow.signal
    def released(self) -> None:
        """Signal sent by the release_hold API endpoint to cancel this escalation chain."""
        self._released = True

    @workflow.run
    async def run(self, inp: HoldEscalationInput) -> None:
        import time

        # --- Checkpoint 1: T+30min from hold placement ---
        # If the branch hasn't responded after 30 minutes, send a reminder.
        thirty_min = timedelta(minutes=30).total_seconds()
        elapsed_since_hold = workflow.now().timestamp() - inp.held_at
        sleep_to_30min = max(0.0, thirty_min - elapsed_since_hold)

        await workflow.wait_condition(
            lambda: self._released,
            timeout=timedelta(seconds=sleep_to_30min),
        )
        if self._released:
            return

        await workflow.execute_activity(
            "send_hold_reminder",
            args=[{
                "instrument_id": inp.instrument_id,
                "bank_id": inp.bank_id,
                "checkpoint": "30_MIN_REMINDER",
                "branch_email": inp.branch_email,
            }],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_NOTIFY_RETRY,
        )

        # --- Checkpoint 2: T-60min before IET ---
        now_ts = workflow.now().timestamp()
        sleep_to_crit = max(0.0, inp.iet_deadline - 3600 - now_ts)

        if sleep_to_crit > 0:
            await workflow.wait_condition(
                lambda: self._released,
                timeout=timedelta(seconds=sleep_to_crit),
            )
            if self._released:
                return

        # Only send if we are not past the IET deadline already
        if workflow.now().timestamp() < inp.iet_deadline:
            await workflow.execute_activity(
                "send_hold_critical_alert",
                args=[{
                    "instrument_id": inp.instrument_id,
                    "bank_id": inp.bank_id,
                    "checkpoint": "T_MINUS_60_MIN",
                    "ops_manager_email": inp.ops_manager_email,
                    "iet_deadline": inp.iet_deadline,
                }],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_NOTIFY_RETRY,
            )

        # --- Checkpoint 3: T-5min before IET (P0 — bypass debouncer) ---
        now_ts = workflow.now().timestamp()
        sleep_to_p0 = max(0.0, inp.iet_deadline - 300 - now_ts)

        if sleep_to_p0 > 0:
            await workflow.wait_condition(
                lambda: self._released,
                timeout=timedelta(seconds=sleep_to_p0),
            )
            if self._released:
                return

        if workflow.now().timestamp() < inp.iet_deadline:
            await workflow.execute_activity(
                "send_hold_p0_alert",
                args=[{
                    "instrument_id": inp.instrument_id,
                    "bank_id": inp.bank_id,
                    "checkpoint": "T_MINUS_5_MIN_P0",
                    "ops_manager_email": inp.ops_manager_email,
                    "iet_deadline": inp.iet_deadline,
                    "bypass_debouncer": True,
                }],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_NOTIFY_RETRY,
            )
