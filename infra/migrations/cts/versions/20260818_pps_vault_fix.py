"""
PPS vault — backfill audit columns + add history table.

The DB table cts.pps_vault_entries was created in 20260618_006 with the
correct cheque_number / cheque_date / payee_name_enc schema.  This migration
adds what was missing from the audit and upload-pipeline perspective:

  1. registered_by   TEXT  — who submitted the PPS instruction:
                             "user:{user_id}" | "system:{feed_name}"
  2. upload_batch_id UUID  — links to cts.vault_upload_batches (nullable;
                             NULL for CBS SFTP push that predates batch tracking)
  3. cts.pps_vault_entries_history — snapshot before any UPDATE or CANCEL;
                             same changed_by / changed_at / upload_batch_id
                             pattern used across all other vault history tables

No schema-breaking changes.  Old pods that do not write registered_by will
get the server-default "system:legacy".

Revision ID: 20260818_pps_vault_fix
Revises:     20260818_cheque_leaf_lifecycle
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260818_pps_vault_fix"
down_revision = "20260818_cheque_leaf_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extend pps_vault_entries with audit columns
    # ------------------------------------------------------------------
    op.add_column(
        "pps_vault_entries",
        sa.Column("registered_by", sa.Text(), nullable=False,
                  server_default="system:legacy"),
        schema="cts",
    )
    op.add_column(
        "pps_vault_entries",
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="cts",
    )

    # ------------------------------------------------------------------
    # pps_vault_entries_history — snapshot before UPDATE or CANCEL
    # ------------------------------------------------------------------
    op.create_table(
        "pps_vault_entries_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("cheque_number", sa.Text(), nullable=False),
        sa.Column("cheque_date", sa.Date(), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=True),
        sa.Column("amount_range", sa.Text(), nullable=True),
        sa.Column("payee_name_enc", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("registration_channel", sa.Text(), nullable=True),
        sa.Column("registered_by", sa.Text(), nullable=True),
        sa.Column("change_action", sa.Text(), nullable=False),
        # UPDATE | CANCEL | UPSERT
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="cts",
    )
    op.create_index("ix_pps_vault_entries_history_entry_id",
                    "pps_vault_entries_history", ["entry_id", "changed_at"],
                    schema="cts")


def downgrade() -> None:
    op.drop_table("pps_vault_entries_history", schema="cts")
    op.drop_column("pps_vault_entries", "upload_batch_id", schema="cts")
    op.drop_column("pps_vault_entries", "registered_by", schema="cts")
