"""TDD tests for feedback_activities DB writes.

Tests verify that emit_payee_feedback_signal, emit_micr_feedback_signal,
dispatch_retrain_job, run_shadow_evaluation, and promote_model correctly
write to cts.ocr_corpus_events and cts.model_retrain_runs.

Every test uses asyncpg mocks — no live DB required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.cts.workflows.activities.feedback_activities import (
    FeedbackSignalResult,
    MicrFeedbackInput,
    PayeeFeedbackInput,
    RetrainJobResult,
    ShadowEvalResult,
    dispatch_retrain_job,
    emit_micr_feedback_signal,
    emit_payee_feedback_signal,
    promote_model,
    run_shadow_evaluation,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _fake_payee_inp(**kw) -> PayeeFeedbackInput:
    defaults = dict(
        instrument_id="INST-001",
        bank_id="saraswat-coop",
        ocr_payee="Ramesh Kumar",
        name_match_score=0.45,
        script="devanagari",
        workflow_decision="STP_RETURN",
        human_approved=None,
        image_path="minio://bucket/img.tiff",
    )
    defaults.update(kw)
    return PayeeFeedbackInput(**defaults)


def _fake_micr_inp(**kw) -> MicrFeedbackInput:
    defaults = dict(
        instrument_id="INST-002",
        bank_id="saraswat-coop",
        ngch_outcome="REJECTED_MICR_ERROR",
        micr_fields={"bank_code": "0123", "account_suffix": "1234"},  # masked — no raw account
        image_path="minio://bucket/img.tiff",
    )
    defaults.update(kw)
    return MicrFeedbackInput(**defaults)


def _fake_db_pool():
    """asyncpg pool mock with acquire() context manager."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool, conn


def _fake_config(threshold: float = 0.82):
    cfg = {"payee_match_threshold": threshold, "ocr_promote_min_improvement": 0.02}
    return cfg


# ─── emit_payee_feedback_signal ──────────────────────────────────────────────

class TestEmitPayeeFeedbackSignalDB:

    @pytest.mark.asyncio
    async def test_writes_to_ocr_corpus_events_on_ocr_char_error(self):
        """Score < 0.50 → OCR_CHAR_ERROR → row written to cts.ocr_corpus_events."""
        pool, conn = _fake_db_pool()
        with patch(
            "modules.cts.workflows.activities.feedback_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value=_fake_config())
            result = await emit_payee_feedback_signal(
                _fake_payee_inp(name_match_score=0.40), db_pool=pool
            )
        assert result.failure_mode == "OCR_CHAR_ERROR"
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "cts.ocr_corpus_events" in sql

    @pytest.mark.asyncio
    async def test_skips_db_write_when_clean(self):
        """Score above threshold → CLEAN → no DB write."""
        pool, conn = _fake_db_pool()
        with patch(
            "modules.cts.workflows.activities.feedback_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value=_fake_config(threshold=0.82))
            result = await emit_payee_feedback_signal(
                _fake_payee_inp(name_match_score=0.95), db_pool=pool
            )
        assert result.failure_mode == "CLEAN"
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_degrades_gracefully_when_db_pool_none(self):
        """db_pool=None → returns result without raising."""
        with patch(
            "modules.cts.workflows.activities.feedback_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value=_fake_config())
            result = await emit_payee_feedback_signal(
                _fake_payee_inp(name_match_score=0.40), db_pool=None
            )
        assert result.failure_mode == "OCR_CHAR_ERROR"

    @pytest.mark.asyncio
    async def test_writes_bank_id_and_instrument_id_in_values(self):
        pool, conn = _fake_db_pool()
        with patch(
            "modules.cts.workflows.activities.feedback_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value=_fake_config())
            await emit_payee_feedback_signal(
                _fake_payee_inp(name_match_score=0.40), db_pool=pool
            )
        args = conn.execute.call_args[0]
        # bank_id and instrument_id must appear as positional params
        assert "saraswat-coop" in args
        assert "INST-001" in args

    @pytest.mark.asyncio
    async def test_writes_xlit_gap_failure_mode(self):
        """Human approved, score in [0.50, threshold) → XLIT_GAP → still writes."""
        pool, conn = _fake_db_pool()
        with patch(
            "modules.cts.workflows.activities.feedback_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value=_fake_config(threshold=0.82))
            result = await emit_payee_feedback_signal(
                _fake_payee_inp(name_match_score=0.65, human_approved=True),
                db_pool=pool,
            )
        assert result.failure_mode == "XLIT_GAP"
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_db_write_when_indeterminate(self):
        """script=None → INDETERMINATE → no DB write (not useful for training)."""
        pool, conn = _fake_db_pool()
        with patch(
            "modules.cts.workflows.activities.feedback_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get_cts_config = AsyncMock(return_value=_fake_config())
            result = await emit_payee_feedback_signal(
                _fake_payee_inp(name_match_score=0.40, script=None), db_pool=pool
            )
        assert result.failure_mode == "INDETERMINATE"
        conn.execute.assert_not_called()


# ─── emit_micr_feedback_signal ───────────────────────────────────────────────

class TestEmitMicrFeedbackSignalDB:

    @pytest.mark.asyncio
    async def test_writes_to_ocr_corpus_events_on_micr_rejection(self):
        pool, conn = _fake_db_pool()
        result = await emit_micr_feedback_signal(_fake_micr_inp(), db_pool=pool)
        assert result.failure_mode == "OCR_CHAR_ERROR"
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "cts.ocr_corpus_events" in sql

    @pytest.mark.asyncio
    async def test_skips_db_write_on_accepted(self):
        pool, conn = _fake_db_pool()
        result = await emit_micr_feedback_signal(
            _fake_micr_inp(ngch_outcome="ACCEPTED"), db_pool=pool
        )
        assert result.failure_mode == "CLEAN"
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_degrades_gracefully_when_db_pool_none(self):
        result = await emit_micr_feedback_signal(_fake_micr_inp(), db_pool=None)
        assert result.failure_mode == "OCR_CHAR_ERROR"

    @pytest.mark.asyncio
    async def test_corpus_type_is_micr_in_values(self):
        pool, conn = _fake_db_pool()
        await emit_micr_feedback_signal(_fake_micr_inp(), db_pool=pool)
        args = conn.execute.call_args[0]
        assert "micr" in args


# ─── dispatch_retrain_job ────────────────────────────────────────────────────

class TestDispatchRetrainJobDB:

    @pytest.mark.asyncio
    async def test_inserts_running_row_into_model_retrain_runs(self):
        pool, conn = _fake_db_pool()
        with (
            patch(
                "modules.cts.workflows.activities.feedback_activities.config_service"
            ) as mock_cfg,
            patch("httpx.AsyncClient") as mock_http,
            patch("temporalio.activity.info") as mock_info,
        ):
            mock_cfg.get = AsyncMock(return_value="http://mlflow.local")
            mock_info.return_value = MagicMock(workflow_id="cts-retrain-saraswat-coop-payee-20260818")
            http_resp = MagicMock()
            http_resp.raise_for_status = MagicMock()
            http_resp.json = MagicMock(return_value={"run": {"info": {"run_id": "mlflow-run-abc"}}})
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=http_resp)
            ))
            result = await dispatch_retrain_job("saraswat-coop", "payee", db_pool=pool)

        assert result.status == "submitted"
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "cts.model_retrain_runs" in sql
        args = conn.execute.call_args[0]
        assert "RUNNING" in args

    @pytest.mark.asyncio
    async def test_degrades_gracefully_when_db_pool_none(self):
        with (
            patch(
                "modules.cts.workflows.activities.feedback_activities.config_service"
            ) as mock_cfg,
            patch("httpx.AsyncClient") as mock_http,
            patch("temporalio.activity.info") as mock_info,
        ):
            mock_cfg.get = AsyncMock(return_value="http://mlflow.local")
            mock_info.return_value = MagicMock(workflow_id="cts-retrain-saraswat-coop-payee-20260818")
            http_resp = MagicMock()
            http_resp.raise_for_status = MagicMock()
            http_resp.json = MagicMock(return_value={"run": {"info": {"run_id": "mlflow-run-abc"}}})
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=http_resp)
            ))
            result = await dispatch_retrain_job("saraswat-coop", "payee", db_pool=None)
        assert result.status == "submitted"

    @pytest.mark.asyncio
    async def test_returns_failed_and_skips_db_write_on_http_error(self):
        pool, conn = _fake_db_pool()
        with (
            patch(
                "modules.cts.workflows.activities.feedback_activities.config_service"
            ) as mock_cfg,
            patch("httpx.AsyncClient") as mock_http,
            patch("temporalio.activity.info") as mock_info,
        ):
            mock_cfg.get = AsyncMock(return_value="http://mlflow.local")
            mock_info.return_value = MagicMock(workflow_id="cts-retrain-saraswat-coop-payee-20260818")
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(side_effect=Exception("connection refused"))
            ))
            result = await dispatch_retrain_job("saraswat-coop", "payee", db_pool=pool)
        assert result.status == "failed"
        conn.execute.assert_not_called()


# ─── run_shadow_evaluation ───────────────────────────────────────────────────

class TestRunShadowEvaluationDB:

    @pytest.mark.asyncio
    async def test_updates_accuracy_fields_in_model_retrain_runs(self):
        pool, conn = _fake_db_pool()
        with (
            patch(
                "modules.cts.workflows.activities.feedback_activities.config_service"
            ) as mock_cfg,
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_cfg.get_cts_config = AsyncMock(return_value={"ocr_promote_min_improvement": 0.02})
            mock_cfg.get = AsyncMock(return_value="http://mlflow.local")
            http_resp = MagicMock()
            http_resp.raise_for_status = MagicMock()
            http_resp.json = MagicMock(return_value={"run": {"data": {"metrics": {
                "eval_accuracy": 0.96,
                "baseline_accuracy": 0.93,
                "eval_fn_rate": 0.008,
                "baseline_fn_rate": 0.012,
            }}}})
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                get=AsyncMock(return_value=http_resp)
            ))
            result = await run_shadow_evaluation(
                "saraswat-coop", "mlflow-run-abc", "payee", db_pool=pool
            )

        assert result.promote is True
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "cts.model_retrain_runs" in sql

    @pytest.mark.asyncio
    async def test_degrades_gracefully_when_db_pool_none(self):
        with (
            patch(
                "modules.cts.workflows.activities.feedback_activities.config_service"
            ) as mock_cfg,
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_cfg.get_cts_config = AsyncMock(return_value={"ocr_promote_min_improvement": 0.02})
            mock_cfg.get = AsyncMock(return_value="http://mlflow.local")
            http_resp = MagicMock()
            http_resp.raise_for_status = MagicMock()
            http_resp.json = MagicMock(return_value={"run": {"data": {"metrics": {}}}})
            mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                get=AsyncMock(return_value=http_resp)
            ))
            result = await run_shadow_evaluation(
                "saraswat-coop", "mlflow-run-abc", "payee", db_pool=None
            )
        assert result.promote is False


# ─── promote_model ────────────────────────────────────────────────────────────

class TestPromoteModelDB:

    @pytest.mark.asyncio
    async def test_updates_model_retrain_runs_on_promotion(self):
        pool, conn = _fake_db_pool()
        with (
            patch(
                "modules.cts.workflows.activities.feedback_activities.config_service"
            ) as mock_cfg,
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_cfg.get = AsyncMock(side_effect=lambda key: {
                "services.mlflow.saraswat-coop.url": "http://mlflow.local",
                "services.vllm.saraswat-coop.url": "http://vllm.local",
            }.get(key, ""))
            http_resp = MagicMock()
            http_resp.raise_for_status = MagicMock()
            mock_client = MagicMock(
                post=AsyncMock(return_value=http_resp),
            )
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)

            await promote_model(
                "saraswat-coop", "mlflow-run-abc", "payee",
                db_pool=pool,
                improvement_pct=0.03,
            )

        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "cts.model_retrain_runs" in sql
        args = conn.execute.call_args[0]
        assert "PROMOTED" in args

    @pytest.mark.asyncio
    async def test_degrades_gracefully_when_db_pool_none(self):
        with (
            patch(
                "modules.cts.workflows.activities.feedback_activities.config_service"
            ) as mock_cfg,
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_cfg.get = AsyncMock(side_effect=lambda key: {
                "services.mlflow.saraswat-coop.url": "http://mlflow.local",
                "services.vllm.saraswat-coop.url": "http://vllm.local",
            }.get(key, ""))
            http_resp = MagicMock()
            http_resp.raise_for_status = MagicMock()
            mock_client = MagicMock(post=AsyncMock(return_value=http_resp))
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            # Should not raise even with db_pool=None
            await promote_model(
                "saraswat-coop", "mlflow-run-abc", "payee",
                db_pool=None,
                improvement_pct=0.03,
            )
