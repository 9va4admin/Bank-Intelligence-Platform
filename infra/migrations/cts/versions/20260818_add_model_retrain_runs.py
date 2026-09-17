"""add cts.model_retrain_runs — OCR model retraining run history

One row per ModelRetrainWorkflow execution. Tracks the full lifecycle:
RUNNING → PROMOTED or REJECTED or FAILED.

run_id matches the Temporal workflow ID (cts-retrain-{bank_id}-{corpus_type}-{ts})
so run history can be correlated with Temporal's workflow UI.

Used by GET /v1/ops/ocr-feedback to power the retraining history table
on the OCR Feedback & Retraining Dashboard.

Revision ID : 20260818_add_model_retrain_runs
Revises     : 20260818_add_ocr_corpus_events
"""
from alembic import op
import sqlalchemy as sa

revision = "20260818_add_model_retrain_runs"
down_revision = "20260818_add_ocr_corpus_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")
    op.execute("""
        CREATE TABLE cts.model_retrain_runs (
            run_id           TEXT        NOT NULL PRIMARY KEY,
            bank_id          TEXT        NOT NULL,
            corpus_type      TEXT        NOT NULL,
            mlflow_run_id    TEXT,
            triggered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at     TIMESTAMPTZ,
            status           TEXT        NOT NULL DEFAULT 'RUNNING',
            accuracy_before  DOUBLE PRECISION,
            accuracy_after   DOUBLE PRECISION,
            improvement_pct  DOUBLE PRECISION,
            promoted         BOOLEAN
        )
    """)
    op.execute("""
        CREATE INDEX idx_model_retrain_runs_bank_date
            ON cts.model_retrain_runs (bank_id, triggered_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_model_retrain_runs_bank_date")
    op.execute("DROP TABLE IF EXISTS cts.model_retrain_runs")
