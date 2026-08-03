"""
HumanReviewWorkflow — waits for an ops_reviewer decision signal.

Started (as an independent, ABANDON-policy child) by ChequeProcessingWorkflow
when decision=HUMAN_REVIEW. Workflow ID: cts-humanreview-{bank_id}-{instrument_id}
Signalled by apps/api/routers/cts.py's POST /v1/cts/review/{id}/decide.

Flow:
  1. push_to_review_queue  — publishes to cts.human.review.{bank_id} Kafka topic
  2. wait_for_signal       — blocks until ops_reviewer confirms/returns (max 55 min)
  3. On signal received    → signal IETWatchdogWorkflow with the decision,
                             file_to_ngch, signal filing_complete, write_audit
  4. On 55-min timeout     → TIMEOUT_AUTO_RETURNED filed to NGCH + write_audit

Terminal states: REVIEWER_CONFIRMED | REVIEWER_RETURNED | TIMEOUT_AUTO_RETURNED

The 55-minute window is intentionally conservative: IET is 180 minutes total,
ChequeProcessingWorkflow consumed ~1–2 min. Human reviewers get ~55 min.
IETWatchdogWorkflow (still running as sibling) fires at T-30s regardless — this
workflow signals it with the real decision as soon as one is reached, so an
emergency fire during the review window files the reviewer's actual decision
instead of the watchdog's no-information CONFIRM fallback.
"""
import asyncio
import time
from datetime import timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger()

_TIMEOUT_SECONDS = 55 * 60   # 55 minutes — never configurable (safety margin)

# Standard retry policies (temporal.md) — same values as cheque_workflow.py / iet_watchdog_workflow.py
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
# Bounded (unlike the implicit unbounded SDK default) — a persistent Kafka
# outage must not block this workflow from ever reaching wait_condition.
# If the queue push never lands, the 55-min timeout's auto-RETURN is still a
# safe outcome; falling through to the IET watchdog's own no-signal CONFIRM
# fallback (which is what happens if this workflow never progresses at all)
# would not be.
_QUEUE_PUSH_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5,
)


# ---------------------------------------------------------------------------
# Input / result models
# ---------------------------------------------------------------------------

class HumanReviewInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    workflow_id: str       # idempotency key for NGCH filing
    context_bundle: dict[str, Any]   # OCR fields, fraud score, SHAP, sig score
    iet_deadline: float    # Unix timestamp — for display in ops workstation


class ReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: str            # "CONFIRM" | "RETURN"
    reason: str            # mandatory — reviewer must give a reason
    reviewer_id: str       # ops_reviewer user ID (from JWT)
    decided_at: float      # Unix timestamp


class HumanReviewResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    outcome: str           # "REVIEWER_CONFIRMED" | "REVIEWER_RETURNED" | "TIMEOUT_AUTO_RETURNED"
    filed_decision: str    # "CONFIRM" | "RETURN"
    acknowledgement_id: str
    reviewer_id: Optional[str] = None
    reason: Optional[str] = None
    timed_out: bool = False


# ---------------------------------------------------------------------------
# Activity: push_to_review_queue
# ---------------------------------------------------------------------------

@activity.defn
async def push_to_review_queue(
    inp: HumanReviewInput,
    event_producer=None,
) -> None:
    """
    Publish instrument to cts.human.review.{bank_id} Kafka topic.
    Ops workstation listens on this topic and displays the item in queue.
    """
    await event_producer.publish(
        topic=f"cts.human.review.{inp.bank_id}",
        event_type="CTS_HUMAN_REVIEW_REQUIRED",
        payload={
            "instrument_id": inp.instrument_id,
            "workflow_id": inp.workflow_id,
            "context_bundle": inp.context_bundle,
            "iet_deadline": inp.iet_deadline,
        },
        schema_version="1.0",
    )
    log.info(
        "human_review.pushed_to_queue",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
    )


# ---------------------------------------------------------------------------
# HumanReviewWorkflow
# ---------------------------------------------------------------------------

@workflow.defn
class HumanReviewWorkflow:
    def __init__(self) -> None:
        self._decision: Optional[ReviewDecision] = None

    def workflow_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-humanreview-{bank_id}-{instrument_id}"

    def watchdog_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-iet-{bank_id}-{instrument_id}"

    @workflow.signal
    def receive_decision(self, decision: ReviewDecision) -> None:
        """Signal handler — called by Temporal signal from ops workstation API
        (apps/api/routers/cts.py POST /v1/cts/review/{id}/decide)."""
        self._decision = decision

    @workflow.run
    async def run(self, inp: HumanReviewInput) -> HumanReviewResult:
        """Production Temporal entry point — see module docstring for the flow."""
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput, file_to_ngch
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        try:
            await workflow.execute_activity(
                push_to_review_queue,
                inp,
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_QUEUE_PUSH_RETRY,
            )
        except Exception as exc:
            # Degrade, don't block: a reviewer who never sees this in the queue
            # still gets the safe outcome via the 55-min timeout's auto-RETURN
            # below. Never let a Kafka outage prevent reaching wait_condition —
            # that would fall through to the IET watchdog's no-signal CONFIRM
            # fallback instead, which is the outcome ASTRA-02 exists to avoid.
            log.critical(
                "human_review.push_to_queue_failed",
                instrument_id=inp.instrument_id, bank_id=inp.bank_id, error=str(exc),
            )

        try:
            await workflow.wait_condition(
                lambda: self._decision is not None,
                timeout=timedelta(seconds=_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            pass

        if self._decision is not None:
            ngch_action = self._decision.action   # "CONFIRM" | "RETURN"
            outcome_map = {"CONFIRM": "REVIEWER_CONFIRMED", "RETURN": "REVIEWER_RETURNED"}
            outcome = outcome_map[ngch_action]
            reviewer_id = self._decision.reviewer_id
            reason = self._decision.reason
            timed_out = False
        else:
            ngch_action = "RETURN"
            outcome = "TIMEOUT_AUTO_RETURNED"
            reviewer_id = None
            reason = "human_review_timeout_55min"
            timed_out = True
            log.warning(
                "human_review.timeout_auto_return",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                workflow_id=inp.workflow_id,
            )

        # Let the watchdog know the real decision before we finish filing it —
        # if T-30s hits mid-filing, the watchdog files THIS decision, not CONFIRM.
        watchdog_id = self.watchdog_id(inp.bank_id, inp.instrument_id)
        try:
            watchdog_handle = workflow.get_external_workflow_handle(watchdog_id)
            await watchdog_handle.signal(IETWatchdogWorkflow.decision_ready, ngch_action)
        except Exception as exc:
            # No self-healing path recovers from this: if the watchdog never
            # learns the real decision, an emergency-fire at T-30s falls back
            # to blind CONFIRM — exactly the ASTRA-02 bug this fix closes.
            log.critical(
                "human_review.watchdog_signal_failed",
                instrument_id=inp.instrument_id,
                watchdog_id=watchdog_id,
                error=str(exc),
            )

        ack_id = ""   # HumanReviewResult.acknowledgement_id is a required str
        filed_by_watchdog = False
        try:
            ngch_result = await workflow.execute_activity(
                file_to_ngch,
                NGCHFilerInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    workflow_id=inp.workflow_id,
                    decision=ngch_action,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_NGCH_FILING_RETRY,
            )
            ack_id = ngch_result.acknowledgement_id
        except Exception as exc:
            cause = getattr(exc, "cause", None)
            if getattr(cause, "type", None) != "DuplicateFilingError":
                # Genuine failure — not a safe race loss. The IET watchdog is
                # still running and will emergency-file at T-30s; propagate so
                # Temporal surfaces this workflow failure rather than losing it.
                raise
            log.warning(
                "human_review.watchdog_won_filing_race",
                instrument_id=inp.instrument_id, decision=ngch_action,
            )
            filed_by_watchdog = True

        try:
            watchdog_handle = workflow.get_external_workflow_handle(watchdog_id)
            await watchdog_handle.signal(IETWatchdogWorkflow.filing_complete)
        except Exception as exc:
            # Self-healing: worst case is one redundant NGCH attempt, which
            # itself resolves via the same DuplicateFilingError path above.
            log.warning(
                "human_review.watchdog_stand_down_signal_failed",
                instrument_id=inp.instrument_id,
                watchdog_id=watchdog_id,
                error=str(exc),
            )

        # Aligned with shared/messages/locales/messages.yaml — outcome-specific
        # keys carry the correct severity/notification routing (a timeout is
        # ERROR + NOTIFICATION; a routine confirm is INFO with none).
        _outcome_event_type = {
            "REVIEWER_CONFIRMED": "CTS_WF_HUMAN_CONFIRMED",
            "REVIEWER_RETURNED": "CTS_WF_HUMAN_RETURNED",
            "TIMEOUT_AUTO_RETURNED": "CTS_WF_REVIEW_TIMEOUT",
        }
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(
                event_type=_outcome_event_type[outcome],
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                payload={
                    "outcome": outcome,
                    "filed_decision": ngch_action,
                    "reviewer_id": reviewer_id,
                    "reason": reason,
                    "acknowledgement_id": ack_id,
                    "timed_out": timed_out,
                    "filed_by_watchdog": filed_by_watchdog,
                },
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        log.info(
            "human_review.complete",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            outcome=outcome,
            timed_out=timed_out,
        )

        return HumanReviewResult(
            instrument_id=inp.instrument_id,
            outcome=outcome,
            filed_decision=ngch_action,
            acknowledgement_id=ack_id,
            reviewer_id=reviewer_id,
            reason=reason,
            timed_out=timed_out,
        )

    async def run_with_mocks(
        self,
        inp: HumanReviewInput,
        event_producer=None,
        ngch_adapter=None,
        audit_writer=None,
        injected_decision: Optional[ReviewDecision] = None,
        simulate_timeout: bool = False,
        current_time: Optional[float] = None,
    ) -> HumanReviewResult:
        """
        Testable orchestration. Production Temporal @workflow.run wraps this.

        injected_decision: pre-set decision for testing (simulates signal received).
        simulate_timeout: True forces the timeout path.
        """
        # Step 1: push to queue
        await push_to_review_queue(inp, event_producer=event_producer)

        # Step 2: wait for decision signal (or timeout)
        if injected_decision is not None and not simulate_timeout:
            self._decision = injected_decision
        elif simulate_timeout:
            self._decision = None
        else:
            # In production: await workflow.wait_condition(lambda: self._decision is not None,
            #                    timeout=timedelta(seconds=_TIMEOUT_SECONDS))
            self._decision = None

        # Step 3: determine action
        if self._decision is not None:
            # Reviewer made a decision
            ngch_action = self._decision.action   # "CONFIRM" | "RETURN"
            outcome_map = {
                "CONFIRM": "REVIEWER_CONFIRMED",
                "RETURN": "REVIEWER_RETURNED",
            }
            outcome = outcome_map[ngch_action]
            reviewer_id = self._decision.reviewer_id
            reason = self._decision.reason
            timed_out = False
        else:
            # Timeout — auto-return to protect bank
            ngch_action = "RETURN"
            outcome = "TIMEOUT_AUTO_RETURNED"
            reviewer_id = None
            reason = "human_review_timeout_55min"
            timed_out = True
            log.warning(
                "human_review.timeout_auto_return",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                workflow_id=inp.workflow_id,
            )

        # Step 4: file to NGCH
        response = await ngch_adapter.file_decision(
            instrument_id=inp.instrument_id,
            decision=ngch_action,
            workflow_id=inp.workflow_id,
        )
        ack_id = response.get("acknowledgement_id", "")

        # Step 5: write audit event
        if audit_writer is not None:
            _outcome_event_type = {
                "REVIEWER_CONFIRMED": "CTS_WF_HUMAN_CONFIRMED",
                "REVIEWER_RETURNED": "CTS_WF_HUMAN_RETURNED",
                "TIMEOUT_AUTO_RETURNED": "CTS_WF_REVIEW_TIMEOUT",
            }
            await audit_writer.write(
                event_type=_outcome_event_type[outcome],
                bank_id=inp.bank_id,
                payload={
                    "instrument_id": inp.instrument_id,
                    "outcome": outcome,
                    "filed_decision": ngch_action,
                    "reviewer_id": reviewer_id,
                    "reason": reason,
                    "acknowledgement_id": ack_id,
                    "timed_out": timed_out,
                },
            )

        log.info(
            "human_review.complete",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            outcome=outcome,
            timed_out=timed_out,
        )

        return HumanReviewResult(
            instrument_id=inp.instrument_id,
            outcome=outcome,
            filed_decision=ngch_action,
            acknowledgement_id=ack_id,
            reviewer_id=reviewer_id,
            reason=reason,
            timed_out=timed_out,
        )
