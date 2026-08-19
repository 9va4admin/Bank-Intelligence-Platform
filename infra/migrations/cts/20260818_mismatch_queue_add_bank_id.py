"""Add bank_id to cts.mismatch_queue and fix watchdog index

The original mismatch_queue migration created the table without a bank_id column,
relying on JOINs through cheque_instruments for bank scoping. This has two problems:

  1. The resolve endpoint queried WHERE mismatch_id=$1 with no bank check (IDOR).
  2. The 4-hour timeout watchdog cannot efficiently scan HELD items per bank without
     a direct bank_id column — the original index comment said "by bank + held_at"
     but the actual index only had held_at.
  3. MismatchResolutionWorkflow never inserted rows into this table (rows lived only
     in Temporal state + Kafka). This migration is paired with the new
     persist_mismatch_hold_to_db activity that does the actual INSERT.

Revision ID: 20260818_mismatch_queue_add_bank_id
Revises: 20260705_add_mismatch_queue
"""
from alembic import op
import sqlalchemy as sa

revision = "20260818_mismatch_queue_add_bank_id"
down_revision = "20260705_add_mismatch_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add bank_id column. Table is empty in production (INSERT was never wired) so
    # NOT NULL with no default is safe. The FK to platform.banks ensures isolation.
    op.execute(
        """
        ALTER TABLE cts.mismatch_queue
        ADD COLUMN bank_id TEXT NOT NULL
        REFERENCES platform.banks(bank_id)
        """
    )

    # Drop the original bare held_at index (comment in original said "by bank" but
    # bank was never included — replacing with the correct compound index).
    op.drop_index("ix_mismatch_queue_held_at", table_name="mismatch_queue", schema="cts")

    # New index: (bank_id, held_at) — used by the 4-hour timeout watchdog in
    # MismatchResolutionWorkflow to scan HELD items per bank efficiently.
    op.create_index(
        "ix_mismatch_queue_bank_held_at",
        "mismatch_queue",
        ["bank_id", "held_at"],
        schema="cts",
    )

    # New index: (bank_id, status) — used by the mismatch list API
    # (GET /v1/cts/mismatches) to fetch all HELD items for a bank.
    op.create_index(
        "ix_mismatch_queue_bank_status",
        "mismatch_queue",
        ["bank_id", "status"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_mismatch_queue_bank_status", table_name="mismatch_queue", schema="cts")
    op.drop_index("ix_mismatch_queue_bank_held_at", table_name="mismatch_queue", schema="cts")
    op.create_index(
        "ix_mismatch_queue_held_at",
        "mismatch_queue",
        ["held_at"],
        schema="cts",
    )
    op.execute("ALTER TABLE cts.mismatch_queue DROP COLUMN bank_id")
