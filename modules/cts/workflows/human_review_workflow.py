"""
HumanReviewWorkflow — waits for an ops_reviewer decision signal.

Triggered: signal from ChequeProcessingWorkflow when decision=HUMAN_REVIEW.
Workflow ID: cts-humanreview-{bank_id}-{instrument_id}

Flow:
  1. push_to_review_queue  — publishes to cts.human.review.{bank_id} Kafka topic
  2. wait_for_signal       — blocks until ops_reviewer confirms/returns (max 55 min)
  3. On signal received    → file_to_ngch + write_audit
  4. On 55-min timeout     → TIMEOUT_AUTO_RETURNED filed to NGCH + write_audit

Terminal states: REVIEWER_CONFIRMED | REVIEWER_RETURNED | TIMEOUT_AUTO_RETURNED

The 55-minute window is intentionally conservative: IET is 180 minutes total,
ChequeProcessingWorkflow consumed ~1–2 min. Human reviewers get ~55 min.
IETWatchdogWorkflow (still running as sibling) fires at T-30s regardless.
"""
import time
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_TIMEOUT_SECONDS = 55 * 60   # 55 minutes — never configurable (safety margin)


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

class HumanReviewWorkflow:
    def __init__(self) -> None:
        self._decision: Optional[ReviewDecision] = None

    def workflow_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-humanreview-{bank_id}-{instrument_id}"

    def receive_decision(self, decision: ReviewDecision) -> None:
        """Signal handler — called by Temporal signal from ops workstation API."""
        self._decision = decision

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
            await audit_writer.write(
                event_type="CTS_HUMAN_REVIEW_DECIDED",
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
