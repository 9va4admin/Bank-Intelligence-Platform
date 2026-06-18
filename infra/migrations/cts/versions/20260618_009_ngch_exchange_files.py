"""NGCH exchange files and acknowledgements.

ngch_exchange_files    — SFTP files sent to / received from NGCH grid
ngch_acknowledgements  — NGCH's per-file and per-item acknowledgement records

The NGCH Adapter (MCP server) manages the actual SFTP transfers.
These tables are the database-side record for reconciliation and retry.

Revision ID: 20260618_009
Revises: 20260618_008
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_009"
down_revision = "20260618_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ngch_exchange_files ────────────────────────────────────────────────
    # One row per NGCH exchange file (inward or outward).
    # Outward: bank sends to NGCH (presentation file + image bundles).
    # Inward: NGCH sends to bank (acknowledgement + settlement files).
    op.create_table(
        "ngch_exchange_files",
        sa.Column("file_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_batches.batch_id"), nullable=True),

        # File identity
        sa.Column("file_type", sa.Text, nullable=False),
        # OUTWARD_PRESENTATION | OUTWARD_RETURN | INWARD_PRESENTATION |
        # INWARD_ACKNOWLEDGEMENT | INWARD_SETTLEMENT | INWARD_RETURN

        sa.Column("file_name", sa.Text, nullable=False),    # NGCH-format filename
        sa.Column("file_date", sa.Date, nullable=False),
        sa.Column("session_ref", sa.Text, nullable=True),   # NGCH session reference

        # File contents summary
        sa.Column("instrument_count", sa.Integer, nullable=True),
        sa.Column("total_amount_paise", sa.BigInteger, nullable=True),

        # Integrity
        sa.Column("file_hash", sa.Text, nullable=True),     # SHA-256 of file before SFTP upload
        sa.Column("file_size_bytes", sa.Integer, nullable=True),

        # MinIO storage (archive copy of the exchange file)
        sa.Column("minio_key", sa.Text, nullable=True),
        # ngch/{bank_id}/{file_date}/{file_name}

        # SFTP transfer status
        sa.Column("direction", sa.Text, nullable=False),
        # OUTBOUND | INBOUND
        sa.Column("transfer_status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | IN_PROGRESS | TRANSFERRED | TRANSFER_FAILED | RECEIVED | PROCESSED

        sa.Column("transfer_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transfer_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transfer_attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_transfer_error", sa.Text, nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_ngch_files_bank_date",
                    "ngch_exchange_files", ["bank_id", "file_date"], schema="cts")
    op.create_index("ix_cts_ngch_files_batch",
                    "ngch_exchange_files", ["batch_id"],
                    postgresql_where=sa.text("batch_id IS NOT NULL"), schema="cts")
    op.create_index("ix_cts_ngch_files_transfer_status",
                    "ngch_exchange_files", ["bank_id", "transfer_status"],
                    postgresql_where=sa.text("transfer_status NOT IN ('PROCESSED', 'RECEIVED')"),
                    schema="cts")

    # ── ngch_acknowledgements ──────────────────────────────────────────────
    # NGCH sends acknowledgement files confirming receipt + item-level status.
    # Used to detect which instruments were rejected by NGCH (rare but must be handled).
    op.create_table(
        "ngch_acknowledgements",
        sa.Column("ack_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("file_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.ngch_exchange_files.file_id"), nullable=False),

        # NGCH acknowledgement details
        sa.Column("ngch_ack_ref", sa.Text, nullable=False),
        sa.Column("ack_type", sa.Text, nullable=False),
        # FILE_ACCEPTED | FILE_REJECTED | ITEM_ACCEPTED | ITEM_REJECTED

        # For item-level acknowledgements
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ngch_instrument_ref", sa.Text, nullable=True),
        sa.Column("item_status", sa.Text, nullable=True),
        # ACCEPTED | REJECTED | DUPLICATE

        # Rejection details (when status is REJECTED)
        sa.Column("rejection_code", sa.Text, nullable=True),   # NGCH rejection code
        sa.Column("rejection_reason", sa.Text, nullable=True),

        sa.Column("ack_received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),

        schema="cts",
    )
    op.create_index("ix_cts_ngch_acks_file",
                    "ngch_acknowledgements", ["file_id"], schema="cts")
    op.create_index("ix_cts_ngch_acks_instrument",
                    "ngch_acknowledgements", ["instrument_id"],
                    postgresql_where=sa.text("instrument_id IS NOT NULL"), schema="cts")
    op.create_index("ix_cts_ngch_acks_bank_type",
                    "ngch_acknowledgements", ["bank_id", "ack_type"], schema="cts")


def downgrade() -> None:
    op.drop_table("ngch_acknowledgements", schema="cts")
    op.drop_table("ngch_exchange_files", schema="cts")
