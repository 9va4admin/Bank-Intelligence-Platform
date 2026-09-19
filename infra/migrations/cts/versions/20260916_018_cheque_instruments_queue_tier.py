"""Add queue_tier column to cts.cheque_instruments.

The holds list endpoint (GET /v1/cts/holds) joins cheque_instruments and selects
queue_tier to determine processing priority. Column was referenced in code but
never created in any prior migration — schema mismatch caught by query audit.

Values: 'standard' (default) | 'high_value' | 'priority'

Revision ID: 20260916_018
Revises: 20260815_017
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260916_018"
down_revision = "20260815_017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add to the parent (unpartitioned) table — DDL propagates to partitions in YugabyteDB
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "queue_tier",
            sa.Text(),
            nullable=False,
            server_default="standard",
        ),
        schema="cts",
    )

    op.create_index(
        "ix_cts_cheque_instruments_queue_tier",
        "cheque_instruments",
        ["bank_id", "queue_tier"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cts_cheque_instruments_queue_tier",
        table_name="cheque_instruments",
        schema="cts",
    )
    op.drop_column("cheque_instruments", "queue_tier", schema="cts")
