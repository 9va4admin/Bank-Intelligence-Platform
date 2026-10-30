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
from typing import Any, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
with workflow.unsafe.imports_passed_through():
    from shared.messages import get_message

log = structlog.get_logger()

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
    # HIGH-1 fix: configurable timeout instead of hardcoded 55-minute constant.
    # ChequeProcessingWorkflow sets a shorter value for SUPERVISED STP mode
    # (reviewers are confirming an AI recommendation, not doing a full review).
    # Minimum 1 to prevent zero/negative timeout bugs.
    review_timeout_minutes: int = Field(default=55, ge=1)
    # Buckets. bucket says which reviewer bucket the item belongs to. system_decision is set only for the SIP
    # buckets, where the SYSTEM has already decided: a reviewer may confirm or overrule it, and if nobody acts before
    # the timeout the system's own decision is filed (never the human-review auto-return).
    bucket: Optional[str] = None
    system_decision: Optional[Literal["CONFIRM", "RETURN"]] = None
    # Maker-checker. When on, the first reviewer decision (the maker's) is not filed: it goes to a second person (the
    # checker) through the VAL bucket, who confirms or overrules it. If no checker acts in checker_timeout_minutes (bounded
    # so the IET guard is never crossed) the maker's decision is filed. The maker can never be their own checker.
    # Not applied to SIP items: there the system is the maker and the reviewer is already the checker.
    maker_checker: bool = False
    checker_timeout_minutes: int = Field(default=15, ge=1)
    iet_guard_minutes: int = Field(default=10, ge=0)
    maker_decision: Optional[Literal["CONFIRM", "RETURN"]] = None    # set on the checker-stage queue event
    maker_id: Optional[str] = None


class ReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: str            # "CONFIRM" | "RETURN"
    reason: str            # mandatory — reviewer must give a reason
    reviewer_id: str       # ops_reviewer user ID (from JWT)
    decided_at: float      # Unix timestamp


class HumanReviewResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    outcome: str           # "REVIEWER_CONFIRMED" | "REVIEWER_RETURNED" | "TIMEOUT_AUTO_RETURNED" | "SIP_AUTO_FILED" | "MAKER_AUTO_FILED"
    filed_decision: str    # "CONFIRM" | "RETURN"
    acknowledgement_id: str
    reviewer_id: Optional[str] = None
    reason: Optional[str] = None
    timed_out: bool = False
    maker_id: Optional[str] = None
    checker_id: Optional[str] = None


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
    if event_producer is None:
        log.warning(
            "human_review.queue_publish_skipped",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            reason="event_producer unavailable (Kafka not configured)",
        )
        return
    payload = {
        "instrument_id": inp.instrument_id,
        "workflow_id": inp.workflow_id,
        "context_bundle": inp.context_bundle,
        "iet_deadline": inp.iet_deadline,
    }
    if inp.bucket:
        payload["bucket"] = inp.bucket
    if inp.system_decision:
        payload["system_decision"] = inp.system_decision
    if inp.maker_decision:
        payload["stage"] = "VALIDATION"
        payload["maker_decision"] = inp.maker_decision
        payload["maker_id"] = inp.maker_id
    await event_producer.publish(
        topic=f"cts.human.review.{inp.bank_id}",
        event_type="CTS_HUMAN_REVIEW_REQUIRED",
        payload=payload,
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
        self._checker_decision: Optional[ReviewDecision] = None

    def workflow_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-humanreview-{bank_id}-{instrument_id}"

    def watchdog_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-iet-{bank_id}-{instrument_id}"

    @workflow.signal
    def receive_decision(self, decision: ReviewDecision) -> None:
        """Signal handler — called by Temporal signal from ops workstation API
        (apps/api/routers/cts.py POST /v1/cts/review/{id}/decide)."""
        self._decision = decision

    @workflow.signal
    def receive_checker_decision(self, decision: ReviewDecision) -> None:
        """The checker's confirm / overrule. Ignored unless a maker has decided and the checker is someone else."""
        if self._decision is None or decision.reviewer_id == self._decision.reviewer_id:
            log.warning("human_review.checker_decision_ignored", reviewer_id=decision.reviewer_id,
                        reason="no maker decision yet" if self._decision is None else "maker cannot check their own decision")
            return
        self._checker_decision = decision

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
                timeout=timedelta(minutes=inp.review_timeout_minutes),
            )
        except asyncio.TimeoutError:
            pass

        maker_id_out: Optional[str] = None
        checker_id_out: Optional[str] = None
        maker_action_out: Optional[str] = None
        if self._decision is not None and inp.maker_checker and not inp.system_decision:
            maker = self._decision
            maker_id_out, maker_action_out = maker.reviewer_id, maker.action
            try:
                # If the IET watchdog ever has to fire, it must file the maker's decision.
                await workflow.get_external_workflow_handle(self.watchdog_id(inp.bank_id, inp.instrument_id)).signal(
                    IETWatchdogWorkflow.decision_ready, maker.action)
            except Exception as exc:
                log.warning("human_review.maker_watchdog_signal_failed", instrument_id=inp.instrument_id, error=str(exc))
            remaining_min = (inp.iet_deadline - workflow.now().timestamp()) / 60.0 - inp.iet_guard_minutes
            wait_min = min(float(inp.checker_timeout_minutes), remaining_min)
            if wait_min >= 1:
                try:
                    await workflow.execute_activity(
                        push_to_review_queue,
                        inp.model_copy(update={"bucket": "VAL", "maker_decision": maker.action,
                                               "maker_id": maker.reviewer_id}),
                        start_to_close_timeout=timedelta(seconds=15),
                        retry_policy=_QUEUE_PUSH_RETRY,
                    )
                except Exception as exc:
                    log.critical("human_review.checker_queue_push_failed", instrument_id=inp.instrument_id, error=str(exc))
                try:
                    await workflow.wait_condition(lambda: self._checker_decision is not None,
                                                  timeout=timedelta(minutes=wait_min))
                except asyncio.TimeoutError:
                    pass

        if self._decision is not None and self._checker_decision is not None and inp.maker_checker and not inp.system_decision:
            checker = self._checker_decision
            checker_id_out = checker.reviewer_id
            ngch_action = checker.action
            outcome = {"CONFIRM": "REVIEWER_CONFIRMED", "RETURN": "REVIEWER_RETURNED"}[ngch_action]
            reviewer_id = checker.reviewer_id
            reason = checker.reason
            timed_out = False
        elif self._decision is not None and inp.maker_checker and not inp.system_decision:
            ngch_action = self._decision.action
            outcome = "MAKER_AUTO_FILED"
            reviewer_id = self._decision.reviewer_id
            reason = get_message("CTS_CHECKER_TIMEOUT_NO_CHECKER_ACTED", ngch_action=ngch_action)
            timed_out = True
            log.info("human_review.maker_decision_filed_no_checker", instrument_id=inp.instrument_id, bank_id=inp.bank_id)
        elif self._decision is not None:
            ngch_action = self._decision.action   # "CONFIRM" | "RETURN"
            outcome_map = {"CONFIRM": "REVIEWER_CONFIRMED", "RETURN": "REVIEWER_RETURNED"}
            outcome = outcome_map[ngch_action]
            reviewer_id = self._decision.reviewer_id
            reason = self._decision.reason
            timed_out = False
        elif inp.system_decision:
            # SIP hold: nobody reviewed it in time, so the system's own decision stands.
            ngch_action = inp.system_decision
            outcome = "SIP_AUTO_FILED"
            reviewer_id = None
            reason = get_message("CTS_SIP_REVIEW_TIMEOUT_MIN_SYSTEM", review_timeout_minutes=inp.review_timeout_minutes, system_decision=inp.system_decision)
            timed_out = True
            log.info("human_review.sip_timeout_system_decision", instrument_id=inp.instrument_id,
                     bank_id=inp.bank_id, decision=inp.system_decision)
        else:
            ngch_action = "RETURN"
            outcome = "TIMEOUT_AUTO_RETURNED"
            reviewer_id = None
            reason = f"human_review_timeout_{inp.review_timeout_minutes}min"
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
            "SIP_AUTO_FILED": "CTS_WF_SIP_AUTO_FILED",
            "MAKER_AUTO_FILED": "CTS_WF_MAKER_AUTO_FILED",
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
                    **({"bucket": inp.bucket} if inp.bucket else {}),
                    **({"system_decision": inp.system_decision,
                        "overrode_system": ngch_action != inp.system_decision} if inp.system_decision else {}),
                    **({"maker_id": maker_id_out, "maker_decision": maker_action_out, "checker_id": checker_id_out,
                        "overrode_maker": checker_id_out is not None and ngch_action != maker_action_out}
                       if maker_id_out else {}),
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
            maker_id=maker_id_out,
            checker_id=checker_id_out,
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
        injected_checker_decision: Optional[ReviewDecision] = None,
        simulate_checker_timeout: bool = False,
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

        # Step 2b: maker-checker. The maker's decision goes to a checker (a different person) before it is filed.
        maker_id_out: Optional[str] = None
        checker_id_out: Optional[str] = None
        maker_action_out: Optional[str] = None
        mc_stage = self._decision is not None and inp.maker_checker and not inp.system_decision
        if mc_stage:
            maker_id_out, maker_action_out = self._decision.reviewer_id, self._decision.action
            await push_to_review_queue(
                inp.model_copy(update={"bucket": "VAL", "maker_decision": self._decision.action,
                                       "maker_id": self._decision.reviewer_id}),
                event_producer=event_producer)
            if (injected_checker_decision is not None and not simulate_checker_timeout
                    and injected_checker_decision.reviewer_id != self._decision.reviewer_id):
                self._checker_decision = injected_checker_decision

        # Step 3: determine action
        if mc_stage and self._checker_decision is not None:
            ngch_action = self._checker_decision.action
            outcome = {"CONFIRM": "REVIEWER_CONFIRMED", "RETURN": "REVIEWER_RETURNED"}[ngch_action]
            reviewer_id = self._checker_decision.reviewer_id
            checker_id_out = reviewer_id
            reason = self._checker_decision.reason
            timed_out = False
        elif mc_stage:
            ngch_action = self._decision.action
            outcome = "MAKER_AUTO_FILED"
            reviewer_id = self._decision.reviewer_id
            reason = get_message("CTS_CHECKER_TIMEOUT_NO_CHECKER_ACTED", ngch_action=ngch_action)
            timed_out = True
        elif self._decision is not None:
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
        elif inp.system_decision:
            # SIP hold: nobody reviewed it in time, so the system's own decision stands.
            ngch_action = inp.system_decision
            outcome = "SIP_AUTO_FILED"
            reviewer_id = None
            reason = get_message("CTS_SIP_REVIEW_TIMEOUT_MIN_SYSTEM", review_timeout_minutes=inp.review_timeout_minutes, system_decision=inp.system_decision)
            timed_out = True
        else:
            # Timeout — auto-return to protect bank
            ngch_action = "RETURN"
            outcome = "TIMEOUT_AUTO_RETURNED"
            reviewer_id = None
            reason = f"human_review_timeout_{inp.review_timeout_minutes}min"
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
                "SIP_AUTO_FILED": "CTS_WF_SIP_AUTO_FILED",
                "MAKER_AUTO_FILED": "CTS_WF_MAKER_AUTO_FILED",
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
                    **({"bucket": inp.bucket} if inp.bucket else {}),
                    **({"system_decision": inp.system_decision,
                        "overrode_system": ngch_action != inp.system_decision} if inp.system_decision else {}),
                    **({"maker_id": maker_id_out, "maker_decision": maker_action_out, "checker_id": checker_id_out,
                        "overrode_maker": checker_id_out is not None and ngch_action != maker_action_out}
                       if maker_id_out else {}),
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
            maker_id=maker_id_out,
            checker_id=checker_id_out,
        )
