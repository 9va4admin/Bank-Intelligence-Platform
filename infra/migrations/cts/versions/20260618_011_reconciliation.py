"""Reconciliation sessions and discrepancies.

reconciliation_sessions      — end-of-day/cycle reconciliation run metadata
reconciliation_discrepancies — mismatches detected between ASTRA records and NGCH/CBS

RBI requires daily reconciliation of clearing positions.
Any discrepancy must be investigated and resolved within 24 hours.

Revision ID: 20260618_011
Revises: 20260618_010
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_011"
down_revision = "20260618_010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── reconciliation_sessions ────────────────────────────────────────────
    # One row per reconciliation run (typically daily, per bank).
    # Triggered by: end-of-clearing-day, manual trigger by ops_manager.
    op.create_table(
        "reconciliation_sessions",
        sa.Column("recon_session_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("clearing_session_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_sessions.session_id"), nullable=True),

        # Reconciliation scope
        sa.Column("recon_date", sa.Date, nullable=False),
        sa.Column("recon_type", sa.Text, nullable=False),
        # DAILY_CLEARING | INTRA_DAY | SETTLEMENT | MANUAL

        # Totals as per ASTRA records
        sa.Column("astra_instrument_count", sa.Integer, nullable=True),
        sa.Column("astra_confirm_count", sa.Integer, nullable=True),
        sa.Column("astra_return_count", sa.Integer, nullable=True),
        sa.Column("astra_total_amount_paise", sa.BigInteger, nullable=True),

        # Totals as per NGCH acknowledgement files
        sa.Column("ngch_instrument_count", sa.Integer, nullable=True),
        sa.Column("ngch_confirm_count", sa.Integer, nullable=True),
        sa.Column("ngch_return_count", sa.Integer, nullable=True),
        sa.Column("ngch_total_amount_paise", sa.BigInteger, nullable=True),

        # Reconciliation outcome
        sa.Column("status", sa.Text, nullable=False, server_default="RUNNING"),
        # RUNNING | RECONCILED | DISCREPANCY_FOUND | FAILED

        sa.Column("discrepancy_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("triggered_by", sa.Text, nullable=True),
        # SCHEDULED | ops_manager user ID | SYSTEM

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_recon_sessions_bank_date",
                    "reconciliation_sessions", ["bank_id", "recon_date"], schema="cts")
    op.create_index("ix_cts_recon_sessions_status",
                    "reconciliation_sessions", ["bank_id", "status"],
                    postgresql_where=sa.text("status IN ('RUNNING', 'DISCREPANCY_FOUND')"),
                    schema="cts")

    # ── reconciliation_discrepancies ───────────────────────────────────────
    # Each mismatch found during a reconciliation session.
    # One row per instrument/amount/count discrepancy.
    op.create_table(
        "reconciliation_discrepancies",
        sa.Column("discrepancy_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("recon_session_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.reconciliation_sessions.recon_session_id"), nullable=False),
        sa.Column("bank_id", sa.Text, nullable=False),

        # Discrepancy type
        sa.Column("discrepancy_type", sa.Text, nullable=False),
        # MISSING_IN_NGCH | EXTRA_IN_NGCH | AMOUNT_MISMATCH |
        # STATUS_MISMATCH | DUPLICATE_FILING | SETTLEMENT_MISMATCH

        # Related records
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ngch_instrument_ref", sa.Text, nullable=True),
        sa.Column("cheque_number", sa.String(6), nullable=True),

        # Values that don't match (amount as range bucket for audit safety)
        sa.Column("astra_value", JSONB, nullable=True),   # what ASTRA recorded
        sa.Column("ngch_value", JSONB, nullable=True),    # what NGCH shows
        # Example: {"status": "STP_CONFIRM"} vs {"status": "RETURNED"}
        # Note: amount discrepancies stored as amount_range, not paise

        # Resolution
        sa.Column("status", sa.Text, nullable=False, server_default="OPEN"),
        # OPEN | UNDER_INVESTIGATION | RESOLVED | ESCALATED_TO_RBI

        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("resolved_by", sa.Text, nullable=True),   # user ID of resolver
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_type", sa.Text, nullable=True),
        # ASTRA_CORRECT | NGCH_CORRECT | BILATERAL_ADJUSTMENT | WRITE_OFF

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_recon_discrepancies_session",
                    "reconciliation_discrepancies", ["recon_session_id"], schema="cts")
    op.create_index("ix_cts_recon_discrepancies_bank_open",
                    "reconciliation_discrepancies", ["bank_id", "status"],
                    postgresql_where=sa.text("status IN ('OPEN', 'UNDER_INVESTIGATION')"),
                    schema="cts")
    op.create_index("ix_cts_recon_discrepancies_instrument",
                    "reconciliation_discrepancies", ["instrument_id"],
                    postgresql_where=sa.text("instrument_id IS NOT NULL"), schema="cts")


def downgrade() -> None:
    op.drop_table("reconciliation_discrepancies", schema="cts")
    op.drop_table("reconciliation_sessions", schema="cts")
