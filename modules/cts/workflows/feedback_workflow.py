"""CTS OCR Feedback Loop Workflows — fully automated, zero human triggers.

FeedbackAccumulatorWorkflow
  Runs as a per-bank persistent workflow (continue-as-new every 10k events).
  Receives FeedbackSignal via Temporal signal from the main ChequeProcessingWorkflow.
  Accumulates corpus entries, checks threshold, triggers retraining automatically.

ModelRetrainWorkflow
  Spawned automatically by FeedbackAccumulatorWorkflow when corpus threshold
  is reached. Dispatches MLflow training job, polls for completion, runs shadow
  evaluation, auto-promotes if metrics pass. No human approval step.

FeedbackEmitWorkflow
  Fire-and-forget child workflow spawned by ChequeProcessingWorkflow after each
  decision. Sends one payee or MICR signal to the running FeedbackAccumulatorWorkflow
  without blocking the main cheque processing timeline.

Workflow IDs:
  FeedbackAccumulatorWorkflow : cts-feedback-{bank_id}
  ModelRetrainWorkflow        : cts-retrain-{bank_id}-{corpus_type}-{ts}
  FeedbackEmitWorkflow        : cts-feedback-emit-{bank_id}-{instrument_id}
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from modules.cts.workflows.activities.feedback_activities import (
        emit_payee_feedback_signal,
        emit_micr_feedback_signal,
        accumulate_corpus_entry,
        check_retrain_threshold,
        dispatch_retrain_job,
        run_shadow_evaluation,
        promote_model,
        PayeeFeedbackInput,
        MicrFeedbackInput,
        FeedbackSignalResult,
        RetrainThresholdResult,
        RetrainJobResult,
        ShadowEvalResult,
    )
    from modules.cts.workflows.feedback_types import FeedbackEmitInput as FeedbackEmitInput


# ─────────────────────────────────────────────────────────────────────────────
#  Retry policies
# ─────────────────────────────────────────────────────────────────────────────

_CORPUS_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
)

_MLFLOW_RETRY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)

_PROMOTE_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=1.5,
    non_retryable_error_types=["ModelNotReadyError"],
)

# How long to poll between shadow evaluation attempts (7 days max wait)
_SHADOW_POLL_INTERVAL = timedelta(hours=6)
_SHADOW_MAX_WAIT      = timedelta(days=7)

# Continue-as-new after this many signals to avoid event history bloat
_CONTINUE_AFTER = 10_000


# ─────────────────────────────────────────────────────────────────────────────
#  Signal / input types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PayeeSignalMessage:
    instrument_id: str
    bank_id: str
    ocr_payee: str
    name_match_score: float
    script: Optional[str]
    workflow_decision: str
    human_approved: Optional[bool]
    image_path: str
    cbs_degraded: bool = False
    cbs_display_initial: Optional[str] = None


@dataclass
class MicrSignalMessage:
    instrument_id: str
    bank_id: str
    ngch_outcome: str
    micr_fields: dict
    image_path: str


@dataclass
class FeedbackAccumulatorInput:
    bank_id: str
    corpus_type: str = "payee"   # "payee" | "micr"
    event_count: int = 0         # for continue-as-new carry-over


@dataclass
class ModelRetrainInput:
    bank_id: str
    corpus_type: str


# ─────────────────────────────────────────────────────────────────────────────
#  FeedbackAccumulatorWorkflow
# ─────────────────────────────────────────────────────────────────────────────

@workflow.defn
class FeedbackAccumulatorWorkflow:
    """Persistent per-bank workflow that accumulates OCR feedback signals.

    Receives signals from ChequeProcessingWorkflow (for payee) and
    from NGCHFilingActivity (for MICR). Auto-triggers ModelRetrainWorkflow
    when corpus threshold is reached. Never blocks cheque processing.
    """

    def __init__(self) -> None:
        self._payee_queue: list[PayeeSignalMessage] = []
        self._micr_queue:  list[MicrSignalMessage]  = []
        self._retrain_in_progress = False
        self._event_count = 0

    @workflow.signal
    async def receive_payee_signal(self, msg: PayeeSignalMessage) -> None:
        self._payee_queue.append(msg)

    @workflow.signal
    async def receive_micr_signal(self, msg: MicrSignalMessage) -> None:
        self._micr_queue.append(msg)

    @workflow.query
    def get_event_count(self) -> int:
        return self._event_count

    @workflow.query
    def is_retrain_in_progress(self) -> bool:
        return self._retrain_in_progress

    @workflow.run
    async def run(self, inp: FeedbackAccumulatorInput) -> None:
        self._event_count = inp.event_count

        while True:
            # Wait for any signal
            await workflow.wait_condition(
                lambda: bool(self._payee_queue or self._micr_queue),
                timeout=timedelta(minutes=30),
            )

            # Drain payee queue
            while self._payee_queue:
                msg = self._payee_queue.pop(0)
                self._event_count += 1
                await self._process_payee(msg, inp.bank_id, inp.corpus_type)

            # Drain MICR queue
            while self._micr_queue:
                msg = self._micr_queue.pop(0)
                self._event_count += 1
                await self._process_micr(msg, inp.bank_id)

            # Check if retraining should fire
            if not self._retrain_in_progress:
                threshold_result: RetrainThresholdResult = await workflow.execute_activity(
                    check_retrain_threshold,
                    args=[inp.bank_id, inp.corpus_type],
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=_CORPUS_RETRY,
                )
                if threshold_result.should_retrain:
                    self._retrain_in_progress = True
                    await workflow.start_child_workflow(
                        ModelRetrainWorkflow.run,
                        args=[ModelRetrainInput(
                            bank_id=inp.bank_id,
                            corpus_type=inp.corpus_type,
                        )],
                        id=f"cts-retrain-{inp.bank_id}-{inp.corpus_type}-{workflow.now().strftime('%Y%m%d%H%M%S')}",
                        task_queue=f"cts-processing-{inp.bank_id}",
                    )

            # Continue-as-new to prevent event history bloat
            if self._event_count >= _CONTINUE_AFTER:
                workflow.continue_as_new(
                    FeedbackAccumulatorInput(
                        bank_id=inp.bank_id,
                        corpus_type=inp.corpus_type,
                        event_count=self._event_count,
                    )
                )

    async def _process_payee(
        self,
        msg: PayeeSignalMessage,
        bank_id: str,
        corpus_type: str,
    ) -> None:
        signal_result: FeedbackSignalResult = await workflow.execute_activity(
            emit_payee_feedback_signal,
            PayeeFeedbackInput(
                instrument_id=msg.instrument_id,
                bank_id=msg.bank_id,
                ocr_payee=msg.ocr_payee,
                name_match_score=msg.name_match_score,
                script=msg.script,
                workflow_decision=msg.workflow_decision,
                human_approved=msg.human_approved,
                image_path=msg.image_path,
                cbs_degraded=msg.cbs_degraded,
                cbs_display_initial=msg.cbs_display_initial,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_CORPUS_RETRY,
        )
        if signal_result.add_to_corpus:
            await workflow.execute_activity(
                accumulate_corpus_entry,
                args=[signal_result, msg.image_path, msg.ocr_payee, corpus_type],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_CORPUS_RETRY,
            )

    async def _process_micr(
        self,
        msg: MicrSignalMessage,
        bank_id: str,
    ) -> None:
        signal_result: FeedbackSignalResult = await workflow.execute_activity(
            emit_micr_feedback_signal,
            MicrFeedbackInput(
                instrument_id=msg.instrument_id,
                bank_id=msg.bank_id,
                ngch_outcome=msg.ngch_outcome,
                micr_fields=msg.micr_fields,
                image_path=msg.image_path,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_CORPUS_RETRY,
        )
        if signal_result.add_to_corpus:
            await workflow.execute_activity(
                accumulate_corpus_entry,
                args=[signal_result, msg.image_path, "", "micr"],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_CORPUS_RETRY,
            )


# ─────────────────────────────────────────────────────────────────────────────
#  ModelRetrainWorkflow
# ─────────────────────────────────────────────────────────────────────────────

@workflow.defn
class ModelRetrainWorkflow:
    """Fully automated model retraining — no human approval step.

    Steps:
    1. Dispatch MLflow training job
    2. Poll for job completion (up to 7 days)
    3. Run shadow evaluation
    4. Auto-promote if improvement >= threshold AND fn_rate doesn't increase
    5. If not promoted → log and stop (human can investigate via MLflow UI)
    """

    @workflow.run
    async def run(self, inp: ModelRetrainInput) -> None:
        # Step 1 — dispatch training job
        job_result: RetrainJobResult = await workflow.execute_activity(
            dispatch_retrain_job,
            args=[inp.bank_id, inp.corpus_type],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_MLFLOW_RETRY,
        )

        if job_result.status != "submitted":
            return   # dispatch failed — activities already logged the error

        # Step 2 — poll shadow evaluation until promotion decision or timeout
        elapsed = timedelta()
        eval_result: Optional[ShadowEvalResult] = None

        while elapsed < _SHADOW_MAX_WAIT:
            await workflow.sleep(_SHADOW_POLL_INTERVAL)
            elapsed += _SHADOW_POLL_INTERVAL

            eval_result = await workflow.execute_activity(
                run_shadow_evaluation,
                args=[inp.bank_id, job_result.mlflow_run_id, inp.corpus_type],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_MLFLOW_RETRY,
            )

            if eval_result.promote or eval_result.new_accuracy > 0:
                break   # got a result — stop polling

        # Step 3 — promote if metrics pass
        if eval_result and eval_result.promote:
            await workflow.execute_activity(
                promote_model,
                args=[inp.bank_id, job_result.mlflow_run_id, inp.corpus_type],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=_PROMOTE_RETRY,
            )


# ─────────────────────────────────────────────────────────────────────────────
#  FeedbackEmitWorkflow
# ─────────────────────────────────────────────────────────────────────────────

@workflow.defn
class FeedbackEmitWorkflow:
    """Fire-and-forget child workflow that sends one feedback signal.

    Spawned by ChequeProcessingWorkflow after each decision. Exits immediately
    after signalling FeedbackAccumulatorWorkflow, so the main processing
    timeline is never blocked by corpus accumulation.

    Accepts feedback_types.FeedbackEmitInput (inline fields) from
    ChequeProcessingWorkflow — Temporal serialises to JSON so the class
    identity does not matter, only the field names.
    """

    @workflow.run
    async def run(self, inp: "FeedbackEmitInput") -> None:
        """Best-effort signal to FeedbackAccumulatorWorkflow. Completes gracefully
        if the accumulator is not running (new bank, restart, or test environment).
        Never raises — feedback loss is acceptable; IET breach is not.
        """
        with workflow.unsafe.imports_passed_through():
            import structlog as _log_mod
        _log = _log_mod.get_logger()

        try:
            from modules.cts.workflows.feedback_types import PayeeSignalMessage

            accumulator_id = f"cts-feedback-{inp.bank_id}"
            handle = workflow.get_external_workflow_handle_for(
                FeedbackAccumulatorWorkflow.run,
                workflow_id=accumulator_id,
            )

            # feedback_types.FeedbackEmitInput (inline fields) — from ChequeProcessingWorkflow
            if hasattr(inp, "ocr_payee"):
                await handle.signal(
                    FeedbackAccumulatorWorkflow.receive_payee_signal,
                    PayeeSignalMessage(
                        instrument_id=inp.instrument_id,
                        bank_id=inp.bank_id,
                        ocr_payee=inp.ocr_payee,
                        name_match_score=inp.name_match_score,
                        script=getattr(inp, "script", None),
                        workflow_decision=inp.workflow_decision,
                        human_approved=getattr(inp, "human_approved", None),
                        image_path=inp.image_path,
                        cbs_degraded=getattr(inp, "cbs_degraded", False),
                        cbs_display_initial=getattr(inp, "cbs_display_initial", None),
                    ),
                )
            # Legacy FeedbackEmitInput (nested payee_msg / micr_msg)
            elif hasattr(inp, "signal_type"):
                if inp.signal_type == "payee" and inp.payee_msg is not None:
                    await handle.signal(
                        FeedbackAccumulatorWorkflow.receive_payee_signal,
                        inp.payee_msg,
                    )
                elif inp.signal_type == "micr" and inp.micr_msg is not None:
                    await handle.signal(
                        FeedbackAccumulatorWorkflow.receive_micr_signal,
                        inp.micr_msg,
                    )
        except BaseException as exc:
            # Accumulator not running (new bank, restart, test env) — acceptable loss.
            # BaseException (not just Exception) to catch Temporal's CancelledError too.
            _log.warning(
                "feedback_emit.accumulator_unreachable",
                bank_id=getattr(inp, "bank_id", "?"),
                instrument_id=getattr(inp, "instrument_id", "?"),
                error=str(exc),
            )
