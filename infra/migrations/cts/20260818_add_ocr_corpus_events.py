"""add cts.ocr_corpus_events — per-cheque OCR feedback signal log

One row per feedback signal emitted from ChequeProcessingWorkflow.
Stores the classified failure mode for every instrument where the payee
name or MICR line had a non-clean outcome.

Used by GET /v1/ops/ocr-feedback to power the 30-day failure mode
breakdown chart on the OCR Feedback & Retraining Dashboard.

Only non-CLEAN, non-INDETERMINATE events are written — CLEAN events
are high-volume and carry no diagnostic value.

Revision ID : 20260818_add_ocr_corpus_events
Revises     : 20260811_add_session_reports
"""
from alembic import op
import sqlalchemy as sa

revision = "20260818_add_ocr_corpus_events"
down_revision = "20260811_add_session_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")
    op.execute("""
        CREATE TABLE cts.ocr_corpus_events (
            event_id         UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
            bank_id          TEXT        NOT NULL,
            instrument_id    TEXT        NOT NULL,
            corpus_type      TEXT        NOT NULL,
            failure_mode     TEXT        NOT NULL,
            name_match_score DOUBLE PRECISION,
            rationale        TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX idx_ocr_corpus_events_bank_mode_date
            ON cts.ocr_corpus_events (bank_id, failure_mode, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_ocr_corpus_events_bank_date
            ON cts.ocr_corpus_events (bank_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ocr_corpus_events_bank_date")
    op.execute("DROP INDEX IF EXISTS idx_ocr_corpus_events_bank_mode_date")
    op.execute("DROP TABLE IF EXISTS cts.ocr_corpus_events")
