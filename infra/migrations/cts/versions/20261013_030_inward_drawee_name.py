"""cts.inward_drawee_name: drawee (account holder) name per inward instrument, from CBS.

Plain text by decision of the bank owner (2026-10-13): exempt from column encryption/masking.

Revision ID: 20261013_030
Revises: 20261012_029
Create Date: 2026-10-13
"""
from alembic import op

revision = "20261013_030"
down_revision = "20261012_029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cts.inward_drawee_name (
            bank_id       TEXT NOT NULL,
            instrument_id UUID NOT NULL,
            drawee_name   TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (bank_id, instrument_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.inward_drawee_name")
