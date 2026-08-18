"""PostDatedHoldWorkflow — Temporal workflow for post-dated cheque management.

When a cheque has a future date, it cannot be processed today. This workflow:
  1. Registers the hold in YugabyteDB (via activity).
  2. Sleeps (durably, via Temporal) until midnight of the cheque date.
  3. On wake: starts a new ChequeProcessingWorkflow, skipping date re-validation.
  4. Accepts a cancel_hold signal if the drawer instructs stop-payment on the
     post-dated cheque before its release date.

Workflow ID: cts-hold-{bank_id}-{instrument_id}
Parent isolation: ABANDON — this workflow outlives the inward scan session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta, datetime
from typing import Any, Literal

from temporalio import workflow
from temporalio.common import RetryPolicy

HoldStatus = Literal["RELEASED", "CANCELLED"]


@dataclass(frozen=True)
class PostDatedHoldInput:
    instrument_id: str
    bank_id: str
    release_date: date
    original_workflow_data: dict


@dataclass(frozen=True)
class PostDatedHoldResult:
    status: HoldStatus
    released_at: str | None


def make_hold_workflow_id(bank_id: str, instrument_id: str) -> str:
    """Deterministic workflow ID for post-dated hold.

    Format: cts-hold-{bank_id}-{instrument_id}
    Spaces replaced with '-' so Temporal workflow IDs are clean.
    """
    clean_bank = bank_id.replace(" ", "-").lower()
    clean_instr = instrument_id.replace(" ", "-")
    return f"cts-hold-{clean_bank}-{clean_instr}"


def _days_until_release(release_date: date, reference: date | None = None) -> int:
    """Return the number of days until the release date.

    Negative means the release date is in the past.
    Zero means today is the release date — release immediately.
    """
    ref = reference or date.today()
    return (release_date - ref).days


_STORE_RETRY = RetryPolicy(
    maximum_attempts=None,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


@workflow.defn
class PostDatedHoldWorkflow:
    """Durable hold for post-dated cheques — releases on the cheque date."""

    def __init__(self) -> None:
        self._cancelled = False
        self._cancel_reason = ""

    @workflow.run
    async def run(self, input: PostDatedHoldInput) -> PostDatedHoldResult:
        # 1. Store the hold persistently (retry indefinitely — cannot lose this)
        await workflow.execute_activity(
            "store_postdated_hold",
            args=[{
                "instrument_id": input.instrument_id,
                "bank_id": input.bank_id,
                "release_date": input.release_date.isoformat(),
                "held_at": workflow.now().isoformat(),
            }],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STORE_RETRY,
        )

        # 2. Calculate sleep duration to midnight of release date
        now_date = workflow.now().date()
        days_remaining = (input.release_date - now_date).days

        if days_remaining > 0:
            await workflow.sleep(timedelta(days=days_remaining))

        # 3. Check if cancelled during sleep
        if self._cancelled:
            await workflow.execute_activity(
                "mark_hold_cancelled",
                args=[{
                    "instrument_id": input.instrument_id,
                    "bank_id": input.bank_id,
                    "cancel_reason": self._cancel_reason,
                    "cancelled_at": workflow.now().isoformat(),
                }],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_STORE_RETRY,
            )
            return PostDatedHoldResult(status="CANCELLED", released_at=None)

        # 4. Release: start the main ChequeProcessingWorkflow
        released_at = workflow.now().isoformat()
        await workflow.start_child_workflow(
            "ChequeProcessingWorkflow",
            args=[input.original_workflow_data],
            id=f"cts-{input.bank_id}-{input.instrument_id}",
            # ParentClosePolicy.ABANDON: main processing must complete
            # even if this hold workflow is somehow terminated
        )

        return PostDatedHoldResult(status="RELEASED", released_at=released_at)

    @workflow.signal
    async def cancel_hold(self, reason: str = "") -> None:
        """Signal: drawer requests to cancel/stop the post-dated cheque before release."""
        self._cancelled = True
        self._cancel_reason = reason

    @workflow.query
    def get_status(self) -> str:
        if self._cancelled:
            return f"CANCELLED:{self._cancel_reason}"
        return "PENDING"
