"""
Migration: add cts.smb_push_sessions

Tracks every SMB CBS push file processed by SMBVaultPushIngestWorkflow.
file_hash UNIQUE constraint provides idempotency — duplicate file = DUPLICATE_SKIPPED.

Upgrade: additive only (new table). Safe to roll back by dropping the table.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260705_smb_push_sessions"
down_revision = "20260706_alter_ngch_submissions_add_pu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")
    op.create_table(
        "smb_push_sessions",
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True),
        sa.Column("agency_id", sa.Text(), nullable=False),
        sa.Column("smb_id", sa.Text(), nullable=False),
        sa.Column("file_type", sa.Text(), nullable=False),   # STOP_PAYMENTS | PPS_ENTRIES | SIGNATURES
        sa.Column("file_hash", sa.Text(), nullable=False, unique=True),   # idempotency key
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="cts",
    )
    op.create_index(
        "ix_smb_push_sessions_agency_smb",
        "smb_push_sessions",
        ["agency_id", "smb_id", "received_at"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_smb_push_sessions_agency_smb", table_name="smb_push_sessions", schema="cts")
    op.drop_table("smb_push_sessions", schema="cts")
