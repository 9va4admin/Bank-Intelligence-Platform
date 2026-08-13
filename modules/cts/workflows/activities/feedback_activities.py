"""CTS OCR Feedback Loop activities — all automated, no human input required.

Activities in this file are called by FeedbackAccumulatorWorkflow and
ModelRetrainWorkflow. Bank staff take no action — signals are mined from
decisions already made during normal cheque processing.

Activity sequence for every processed cheque (happens automatically):
  emit_feedback_signal     — extract + classify signal from activity outputs
  accumulate_corpus_entry  — write training candidate to MinIO if warranted
  check_retrain_threshold  — return True when corpus is large enough to retrain
  dispatch_retrain_job     — submit MLflow training job (non-blocking)
  run_shadow_evaluation    — compare new model vs old on held-out set
  promote_model            — swap vLLM to new model version if metrics pass
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.config.config_service import config_service
from modules.cts.feedback.failure_classifier import FailureMode
from modules.cts.feedback.signal_extractor import (
    extract_payee_signal,
    extract_micr_signal,
    FeedbackSignal,
)
from modules.cts.feedback.corpus_manager import CorpusEntry

log = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
#  Input / output models
# ─────────────────────────────────────────────────────────────────────────────

class PayeeFeedbackInput(BaseModel):
    model_config = ConfigDict(frozen=True)
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


class MicrFeedbackInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    ngch_outcome: str
    micr_fields: dict
    image_path: str


class FeedbackSignalResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    failure_mode: str
    add_to_corpus: bool
    corpus_label: str
    rationale: str


class RetrainThresholdResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    corpus_count: int
    threshold: int
    should_retrain: bool


class RetrainJobResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    mlflow_run_id: str
    status: str   # "submitted" | "skipped" | "failed"


class ShadowEvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    mlflow_run_id: str
    new_accuracy: float
    baseline_accuracy: float
    improvement: float
    promote: bool


# ─────────────────────────────────────────────────────────────────────────────
#  Activities
# ─────────────────────────────────────────────────────────────────────────────

@activity.defn
async def emit_payee_feedback_signal(inp: PayeeFeedbackInput) -> FeedbackSignalResult:
    """Extract and classify a payee OCR feedback signal. No human input needed."""
    cts_cfg = await config_service.get_cts_config(inp.bank_id)
    threshold: float = cts_cfg.get("payee_match_threshold", 0.82)

    signal: FeedbackSignal = extract_payee_signal(
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        ocr_payee=inp.ocr_payee,
        name_match_score=inp.name_match_score,
        threshold=threshold,
        script=inp.script,
        workflow_decision=inp.workflow_decision,
        human_approved=inp.human_approved,
        image_path=inp.image_path,
        cbs_degraded=inp.cbs_degraded,
        cbs_display_initial=inp.cbs_display_initial,
    )

    log.info(
        "feedback.payee_signal.emitted",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        failure_mode=signal.failure_mode.value if signal.failure_mode else "NONE",
        add_to_corpus=signal.add_to_corpus,
        score=round(inp.name_match_score, 3),
    )

    return FeedbackSignalResult(
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        failure_mode=signal.failure_mode.value if signal.failure_mode else "INDETERMINATE",
        add_to_corpus=signal.add_to_corpus,
        corpus_label="negative" if signal.add_to_corpus else "",
        rationale=signal.rationale,
    )


@activity.defn
async def emit_micr_feedback_signal(inp: MicrFeedbackInput) -> FeedbackSignalResult:
    """Extract MICR feedback signal from NGCH filing outcome. Fully automatic."""
    signal: FeedbackSignal = extract_micr_signal(
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        ngch_outcome=inp.ngch_outcome,
        micr_fields=inp.micr_fields,
        image_path=inp.image_path,
    )

    log.info(
        "feedback.micr_signal.emitted",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        ngch_outcome=inp.ngch_outcome,
        add_to_corpus=signal.add_to_corpus,
        corpus_label=signal.corpus_label,
    )

    return FeedbackSignalResult(
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        failure_mode=signal.failure_mode.value if signal.failure_mode else "INDETERMINATE",
        add_to_corpus=signal.add_to_corpus,
        corpus_label=signal.corpus_label,
        rationale=signal.rationale,
    )


@activity.defn
async def accumulate_corpus_entry(
    signal_result: FeedbackSignalResult,
    image_path: str,
    ocr_text: str,
    corpus_type: str,
    app_state,
) -> None:
    """Write a training candidate to MinIO and increment the Redis counter.

    Called only when signal_result.add_to_corpus is True. Skips silently
    otherwise — idempotent if called twice for the same instrument_id.
    """
    if not signal_result.add_to_corpus:
        return

    from modules.cts.feedback.corpus_manager import CorpusManager
    mgr = CorpusManager(
        minio_client=app_state.minio_client,
        redis_client=app_state.redis_cts,
    )
    entry = CorpusEntry(
        instrument_id=signal_result.instrument_id,
        bank_id=signal_result.bank_id,
        image_path=image_path,
        ocr_text=ocr_text,
        label=signal_result.corpus_label or "negative",
        failure_mode_str=signal_result.failure_mode,
        corpus_type=corpus_type,
    )
    await mgr.add_entry(entry)
    log.info(
        "feedback.corpus.entry_added",
        instrument_id=signal_result.instrument_id,
        bank_id=signal_result.bank_id,
        corpus_type=corpus_type,
        failure_mode=signal_result.failure_mode,
    )


@activity.defn
async def check_retrain_threshold(
    bank_id: str,
    corpus_type: str,
    app_state,
) -> RetrainThresholdResult:
    """Check if the accumulated corpus is large enough to trigger retraining."""
    from modules.cts.feedback.corpus_manager import CorpusManager
    cts_cfg = await config_service.get_cts_config(bank_id)
    threshold: int = int(cts_cfg.get("ocr_feedback_retrain_threshold", 500))

    mgr = CorpusManager(
        minio_client=app_state.minio_client,
        redis_client=app_state.redis_cts,
    )
    stats = await mgr.get_stats(bank_id, corpus_type)
    should = await mgr.should_trigger_retrain(bank_id, threshold, corpus_type)

    log.info(
        "feedback.retrain.threshold_check",
        bank_id=bank_id,
        corpus_type=corpus_type,
        corpus_count=stats.count,
        threshold=threshold,
        should_retrain=should,
    )

    return RetrainThresholdResult(
        bank_id=bank_id,
        corpus_count=stats.count,
        threshold=threshold,
        should_retrain=should,
    )


@activity.defn
async def dispatch_retrain_job(
    bank_id: str,
    corpus_type: str,
    app_state,
) -> RetrainJobResult:
    """Submit a retraining job to MLflow. Non-blocking — workflow polls for completion.

    In production: calls MLflow REST API to create a new training run.
    The vLLM model remains unchanged until shadow evaluation passes.
    """
    mlflow_url = await config_service.get_secret(f"mlflow.{bank_id}.api_url")
    # MLflow experiment name follows convention: cts-ocr-{corpus_type}-{bank_id}
    experiment_name = f"cts-ocr-{corpus_type}-{bank_id}"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{mlflow_url}/api/2.0/mlflow/runs/create",
                json={
                    "experiment_name": experiment_name,
                    "tags": [
                        {"key": "bank_id",      "value": bank_id},
                        {"key": "corpus_type",  "value": corpus_type},
                        {"key": "trigger",      "value": "auto_feedback_loop"},
                    ],
                },
            )
            resp.raise_for_status()
            run_id = resp.json()["run"]["info"]["run_id"]
    except Exception as exc:
        log.error(
            "feedback.retrain.dispatch_failed",
            bank_id=bank_id,
            corpus_type=corpus_type,
            error=str(exc),
        )
        return RetrainJobResult(bank_id=bank_id, mlflow_run_id="", status="failed")

    log.info(
        "feedback.retrain.job_dispatched",
        bank_id=bank_id,
        corpus_type=corpus_type,
        mlflow_run_id=run_id,
    )
    return RetrainJobResult(bank_id=bank_id, mlflow_run_id=run_id, status="submitted")


@activity.defn
async def run_shadow_evaluation(
    bank_id: str,
    mlflow_run_id: str,
    corpus_type: str,
    app_state,
) -> ShadowEvalResult:
    """Fetch evaluation metrics from MLflow and decide whether to promote.

    Auto-promotes when:
      - new model accuracy improvement >= 2% (configurable)
      - false negative rate does not increase
    No human sign-off required.
    """
    cts_cfg = await config_service.get_cts_config(bank_id)
    min_improvement: float = float(cts_cfg.get("ocr_promote_min_improvement", 0.02))

    mlflow_url = await config_service.get_secret(f"mlflow.{bank_id}.api_url")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{mlflow_url}/api/2.0/mlflow/runs/get",
                params={"run_id": mlflow_run_id},
            )
            resp.raise_for_status()
            metrics = resp.json()["run"]["data"].get("metrics", {})
    except Exception as exc:
        log.error("feedback.shadow_eval.fetch_failed", error=str(exc), run_id=mlflow_run_id)
        return ShadowEvalResult(
            bank_id=bank_id,
            mlflow_run_id=mlflow_run_id,
            new_accuracy=0.0,
            baseline_accuracy=0.0,
            improvement=0.0,
            promote=False,
        )

    new_acc      = float(metrics.get("eval_accuracy",      0.0))
    baseline_acc = float(metrics.get("baseline_accuracy",  0.0))
    new_fn_rate  = float(metrics.get("eval_fn_rate",       1.0))
    baseline_fn  = float(metrics.get("baseline_fn_rate",   0.0))
    improvement  = new_acc - baseline_acc

    promote = improvement >= min_improvement and new_fn_rate <= baseline_fn

    log.info(
        "feedback.shadow_eval.result",
        bank_id=bank_id,
        mlflow_run_id=mlflow_run_id,
        new_accuracy=round(new_acc, 4),
        baseline_accuracy=round(baseline_acc, 4),
        improvement=round(improvement, 4),
        promote=promote,
    )
    return ShadowEvalResult(
        bank_id=bank_id,
        mlflow_run_id=mlflow_run_id,
        new_accuracy=new_acc,
        baseline_accuracy=baseline_acc,
        improvement=improvement,
        promote=promote,
    )


@activity.defn
async def promote_model(
    bank_id: str,
    mlflow_run_id: str,
    corpus_type: str,
    app_state,
) -> None:
    """Hot-swap the vLLM model to the new version. Zero downtime.

    MLflow model registry → mark as Production stage.
    vLLM hot-reload API reloads the model without dropping in-flight requests.
    Resets the corpus counter so the next cycle starts fresh.
    """
    mlflow_url = await config_service.get_secret(f"mlflow.{bank_id}.api_url")
    model_name = f"cts-ocr-{corpus_type}-{bank_id}"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Promote in MLflow registry
            await client.post(
                f"{mlflow_url}/api/2.0/mlflow/model-versions/transition-stage",
                json={
                    "name":    model_name,
                    "version": mlflow_run_id,
                    "stage":   "Production",
                },
            )
            # Hot-reload vLLM (internal service URL from config)
            vllm_url = await config_service.get(f"services.vllm.{bank_id}.url")
            await client.post(
                f"{vllm_url}/reload",
                json={"model": model_name, "stage": "Production"},
                timeout=60.0,
            )
    except Exception as exc:
        log.error("feedback.promote.failed", bank_id=bank_id, run_id=mlflow_run_id, error=str(exc))
        raise

    # Reset corpus counter — next cycle starts from 0
    from modules.cts.feedback.corpus_manager import CorpusManager
    mgr = CorpusManager(
        minio_client=app_state.minio_client,
        redis_client=app_state.redis_cts,
    )
    await mgr.reset_counter(bank_id, corpus_type)

    log.info(
        "feedback.model.promoted",
        bank_id=bank_id,
        mlflow_run_id=mlflow_run_id,
        corpus_type=corpus_type,
        model_name=model_name,
    )
