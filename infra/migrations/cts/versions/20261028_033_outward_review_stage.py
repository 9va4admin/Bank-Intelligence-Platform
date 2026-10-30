"""cts.outward_review_stage - the maker's decision on a held outward instrument, waiting for a checker.

Revision ID: 20261028_033
Revises: 20261028_032
Create Date: 2026-10-28
"""
from alembic import op

revision = "20261028_033"
down_revision = "20261028_032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cts.outward_review_stage (
            bank_id        TEXT NOT NULL,
            instrument_id  TEXT NOT NULL,
            maker_id       TEXT NOT NULL,
            maker_decision TEXT NOT NULL CHECK (maker_decision IN ('CONFIRMED','REJECTED')),
            maker_reason   TEXT NOT NULL DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'MAKER_DECIDED' CHECK (status IN ('MAKER_DECIDED','FINAL')),
            made_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            checker_id     TEXT,
            checked_at     TIMESTAMPTZ,
            PRIMARY KEY (bank_id, instrument_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_outward_review_stage_status ON cts.outward_review_stage (bank_id, status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.outward_review_stage")
