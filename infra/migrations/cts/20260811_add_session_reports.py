"""add cts.session_reports — immutable outward session clearing digest

One row per clearing session per branch. Generated automatically at the end of
every OutwardScanWorkflow session (after all lots sealed + NGCH submitted).

Both HTML and PDF are stored in MinIO under WORM COMPLIANCE mode. The Immudb
sequence number provides cryptographic proof of the timestamp. This table is
the metadata index; the actual files live in MinIO.

MinIO path convention:
  cts/reports/{bank_id}/{branch_ifsc}/{yyyy}/{mm}/{session_id}/report.html
  cts/reports/{bank_id}/{branch_ifsc}/{yyyy}/{mm}/{session_id}/report.pdf

Revision ID: 20260811_add_session_reports
Revises:     20260811_scanner_registrations
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_add_session_reports"
down_revision = "20260811_scanner_registrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")
    op.execute("""
        CREATE TABLE cts.session_reports (
            report_id            UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
            session_id           TEXT        NOT NULL,
            bank_id              TEXT        NOT NULL,
            branch_id            TEXT        NOT NULL,
            branch_ifsc          TEXT        NOT NULL,
            clearing_date        DATE        NOT NULL,
            session_type         TEXT        NOT NULL,
            generated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            html_minio_path      TEXT,
            pdf_minio_path       TEXT,
            instrument_count     INTEGER     NOT NULL DEFAULT 0,
            lot_count            INTEGER     NOT NULL DEFAULT 0,
            accepted_count       INTEGER     NOT NULL DEFAULT 0,
            rejected_count       INTEGER     NOT NULL DEFAULT 0,
            held_count           INTEGER     NOT NULL DEFAULT 0,
            compliance_pass_count INTEGER    NOT NULL DEFAULT 0,
            compliance_fail_count INTEGER    NOT NULL DEFAULT 0,
            immudb_tx_id         BIGINT,
            status               TEXT        NOT NULL DEFAULT 'GENERATING',
            error_detail         TEXT,
            CONSTRAINT uq_session_reports_session UNIQUE (session_id, bank_id)
        )
    """)
    op.execute("""
        CREATE INDEX idx_session_reports_bank_date
            ON cts.session_reports (bank_id, clearing_date DESC)
    """)
    op.execute("""
        CREATE INDEX idx_session_reports_branch
            ON cts.session_reports (bank_id, branch_id, clearing_date DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_session_reports_branch")
    op.execute("DROP INDEX IF EXISTS idx_session_reports_bank_date")
    op.execute("DROP TABLE IF EXISTS cts.session_reports")
