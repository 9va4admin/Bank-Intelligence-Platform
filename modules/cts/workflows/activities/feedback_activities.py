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

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.feedback.corpus_manager import CorpusEntry, CorpusManager
from modules.cts.feedback.signal_extractor import (
    FeedbackSignal,
    extract_micr_signal,
    extract_payee_signal,
)
from shared.config.config_service import config_service

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)


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

_SKIP_DB_MODES = frozenset({"CLEAN", "INDETERMINATE"})


@activity.defn
async def emit_payee_feedback_signal(
    inp: PayeeFeedbackInput,
    db_pool=None,
) -> FeedbackSignalResult:
    """Extract and classify a payee OCR feedback signal. No human input needed."""
    with tracer.start_as_current_span("activity.emit_payee_feedback_signal") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
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

        failure_mode = signal.failure_mode.value if signal.failure_mode else "INDETERMINATE"

        log.info(
            "feedback.payee_signal.emitted",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            failure_mode=failure_mode,
            add_to_corpus=signal.add_to_corpus,
            score=round(inp.name_match_score, 3),
        )

        if db_pool is not None and failure_mode not in _SKIP_DB_MODES:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO cts.ocr_corpus_events
                            (bank_id, instrument_id, corpus_type, failure_mode,
                             name_match_score, rationale)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        inp.bank_id,
                        inp.instrument_id,
                        "payee",
                        failure_mode,
                        inp.name_match_score,
                        signal.rationale,
                    )
            except Exception as exc:
                log.warning("feedback.payee_signal.db_write_failed", error=str(exc),
                            instrument_id=inp.instrument_id)

        return FeedbackSignalResult(
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            failure_mode=failure_mode,
            add_to_corpus=signal.add_to_corpus,
            corpus_label="negative" if signal.add_to_corpus else "",
            rationale=signal.rationale,
        )


@activity.defn
async def emit_micr_feedback_signal(
    inp: MicrFeedbackInput,
    db_pool=None,
) -> FeedbackSignalResult:
    """Extract MICR feedback signal from NGCH filing outcome. Fully automatic."""
    with tracer.start_as_current_span("activity.emit_micr_feedback_signal") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        signal: FeedbackSignal = extract_micr_signal(
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            ngch_outcome=inp.ngch_outcome,
            micr_fields=inp.micr_fields,
            image_path=inp.image_path,
        )

        failure_mode = signal.failure_mode.value if signal.failure_mode else "INDETERMINATE"

        log.info(
            "feedback.micr_signal.emitted",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            ngch_outcome=inp.ngch_outcome,
            add_to_corpus=signal.add_to_corpus,
            corpus_label=signal.corpus_label,
        )

        if db_pool is not None and failure_mode not in _SKIP_DB_MODES:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO cts.ocr_corpus_events
                            (bank_id, instrument_id, corpus_type, failure_mode,
                             name_match_score, rationale)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        inp.bank_id,
                        inp.instrument_id,
                        "micr",
                        failure_mode,
                        None,
                        signal.rationale,
                    )
            except Exception as exc:
                log.warning("feedback.micr_signal.db_write_failed", error=str(exc),
                            instrument_id=inp.instrument_id)

        return FeedbackSignalResult(
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            failure_mode=failure_mode,
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
    minio_client=None,
    redis_client=None,
) -> None:
    """Write a training candidate to MinIO and increment the Redis counter.

    Called only when signal_result.add_to_corpus is True. Skips silently
    otherwise — idempotent if called twice for the same instrument_id.
    """
    with tracer.start_as_current_span("activity.accumulate_corpus_entry") as span:
        span.set_attribute("bank_id", signal_result.bank_id)
        if not signal_result.add_to_corpus:
            return

        if minio_client is None or redis_client is None:
            log.warning(
                "feedback.corpus.skipped_no_clients",
                instrument_id=signal_result.instrument_id,
                bank_id=signal_result.bank_id,
            )
            return

        mgr = CorpusManager(
            minio_client=minio_client,
            redis_client=redis_client,
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
    minio_client=None,
    redis_client=None,
) -> RetrainThresholdResult:
    """Check if the accumulated corpus is large enough to trigger retraining."""
    with tracer.start_as_current_span("activity.check_retrain_threshold") as span:
        span.set_attribute("bank_id", bank_id)
        cts_cfg = await config_service.get_cts_config(bank_id)
        threshold: int = int(cts_cfg.get("ocr_feedback_retrain_threshold", 500))

        if minio_client is None or redis_client is None:
            log.warning(
                "feedback.retrain.skipped_no_clients",
                bank_id=bank_id,
                corpus_type=corpus_type,
            )
            return RetrainThresholdResult(
                bank_id=bank_id,
                corpus_count=0,
                threshold=threshold,
                should_retrain=False,
            )

        mgr = CorpusManager(
            minio_client=minio_client,
            redis_client=redis_client,
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
    db_pool=None,
) -> RetrainJobResult:
    """Submit a retraining job to MLflow. Non-blocking — workflow polls for completion.

    In production: calls MLflow REST API to create a new training run.
    The vLLM model remains unchanged until shadow evaluation passes.
    """
    with tracer.start_as_current_span("activity.dispatch_retrain_job") as span:
        span.set_attribute("bank_id", bank_id)
        mlflow_url = await config_service.get(f"services.mlflow.{bank_id}.url")
        # MLflow experiment name follows convention: cts-ocr-{corpus_type}-{bank_id}
        experiment_name = f"cts-ocr-{corpus_type}-{bank_id}"

        from temporalio import activity as _activity
        workflow_run_id = _activity.info().workflow_id

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

        if db_pool is not None:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO cts.model_retrain_runs
                            (run_id, bank_id, corpus_type, mlflow_run_id, status)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (run_id) DO NOTHING
                        """,
                        workflow_run_id,
                        bank_id,
                        corpus_type,
                        run_id,
                        "RUNNING",
                    )
            except Exception as exc:
                log.warning("feedback.retrain.db_insert_failed", error=str(exc), bank_id=bank_id)

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
    db_pool=None,
) -> ShadowEvalResult:
    """Fetch evaluation metrics from MLflow and decide whether to promote.

    Auto-promotes when:
      - new model accuracy improvement >= 2% (configurable)
      - false negative rate does not increase
    No human sign-off required.
    """
    with tracer.start_as_current_span("activity.run_shadow_evaluation") as span:
        span.set_attribute("bank_id", bank_id)
        cts_cfg = await config_service.get_cts_config(bank_id)
        min_improvement: float = float(cts_cfg.get("ocr_promote_min_improvement", 0.02))

        mlflow_url = await config_service.get(f"services.mlflow.{bank_id}.url")

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

        if db_pool is not None and new_acc > 0:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE cts.model_retrain_runs
                           SET accuracy_before = $1,
                               accuracy_after  = $2,
                               improvement_pct = $3
                         WHERE mlflow_run_id = $4
                        """,
                        baseline_acc,
                        new_acc,
                        round(improvement * 100, 2),
                        mlflow_run_id,
                    )
            except Exception as exc:
                log.warning("feedback.shadow_eval.db_update_failed", error=str(exc),
                            run_id=mlflow_run_id)

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
    minio_client=None,
    redis_client=None,
    db_pool=None,
    improvement_pct: Optional[float] = None,
) -> None:
    """Hot-swap the vLLM model to the new version. Zero downtime.

    MLflow model registry → mark as Production stage.
    vLLM hot-reload API reloads the model without dropping in-flight requests.
    Resets the corpus counter so the next cycle starts fresh.
    """
    with tracer.start_as_current_span("activity.promote_model") as span:
        span.set_attribute("bank_id", bank_id)
        mlflow_url = await config_service.get(f"services.mlflow.{bank_id}.url")
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
        if minio_client is not None and redis_client is not None:
            mgr = CorpusManager(
                minio_client=minio_client,
                redis_client=redis_client,
            )
            await mgr.reset_counter(bank_id, corpus_type)

        if db_pool is not None:
            from datetime import datetime, timezone
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE cts.model_retrain_runs
                           SET status       = $1,
                               completed_at = $2,
                               improvement_pct = COALESCE($3, improvement_pct),
                               promoted     = TRUE
                         WHERE mlflow_run_id = $4
                        """,
                        "PROMOTED",
                        datetime.now(timezone.utc),
                        improvement_pct,
                        mlflow_run_id,
                    )
            except Exception as exc:
                log.warning("feedback.promote.db_update_failed", error=str(exc),
                            run_id=mlflow_run_id)

        log.info(
            "feedback.model.promoted",
            bank_id=bank_id,
            mlflow_run_id=mlflow_run_id,
            corpus_type=corpus_type,
            model_name=model_name,
        )
