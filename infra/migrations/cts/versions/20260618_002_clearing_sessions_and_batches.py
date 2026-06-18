"""Clearing sessions and batches — supports continuous clearing (Jan 2026 RBI mandate).

Revision ID: 20260618_002
Revises: 20260618_001
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_002"
down_revision = "20260618_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── clearing_sessions ──────────────────────────────────────────────────
    # Represents one clearing window — continuous clearing has multiple per day
    op.create_table(
        "clearing_sessions",
        sa.Column("session_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("center_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.processing_centers.center_id"), nullable=False),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("session_type", sa.Text, nullable=False),            # "INWARD" | "OUTWARD" | "RETURN"
        sa.Column("clearing_type", sa.Text, nullable=False),           # "CTS" | "MICR" | "NON_MICR"
        # Continuous clearing Phase 2: 3-hour confirmation windows
        sa.Column("presentation_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presentation_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="'OPEN'"),
        # "OPEN" | "SUBMITTED" | "SETTLED" | "RECONCILED"
        sa.Column("ngch_session_ref", sa.Text, nullable=True),         # NGCH-assigned reference
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_clearing_sessions_bank_date",
                    "clearing_sessions", ["bank_id", "session_date"], schema="cts")
    op.create_index("ix_cts_clearing_sessions_status",
                    "clearing_sessions", ["status"], schema="cts")

    # ── clearing_batches ───────────────────────────────────────────────────
    # A batch is a group of instruments submitted together in one NGCH file
    op.create_table(
        "clearing_batches",
        sa.Column("batch_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_sessions.session_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("batch_type", sa.Text, nullable=False),             # "INWARD" | "OUTWARD" | "RETURN"
        sa.Column("instrument_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_amount_paise", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("ngch_batch_ref", sa.Text, nullable=True),          # NGCH batch reference
        sa.Column("file_hash", sa.Text, nullable=True),               # SHA-256 of exchange file
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # "PENDING" | "SUBMITTED" | "ACKNOWLEDGED" | "REJECTED"
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_clearing_batches_session",
                    "clearing_batches", ["session_id"], schema="cts")
    op.create_index("ix_cts_clearing_batches_bank_status",
                    "clearing_batches", ["bank_id", "status"], schema="cts")

    # ── settlement_positions ───────────────────────────────────────────────
    # Net debit/credit per bank per session after multilateral netting
    op.create_table(
        "settlement_positions",
        sa.Column("position_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_sessions.session_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("gross_debit_paise", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("gross_credit_paise", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("net_position_paise", sa.BigInteger, nullable=False, server_default="0"),
        # positive = net credit (receiving funds), negative = net debit (paying out)
        sa.Column("instrument_count_debit", sa.Integer, nullable=False, server_default="0"),
        sa.Column("instrument_count_credit", sa.Integer, nullable=False, server_default="0"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rbi_settlement_ref", sa.Text, nullable=True),      # RBI settlement reference
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_settlement_positions_session_bank",
                    "settlement_positions", ["session_id", "bank_id"],
                    unique=True, schema="cts")


def downgrade() -> None:
    op.drop_table("settlement_positions", schema="cts")
    op.drop_table("clearing_batches", schema="cts")
    op.drop_table("clearing_sessions", schema="cts")
