"""add cts.clearing_sessions table

ClearingSession — one per SB per clearing day per session type.

In SB_NGCH mode: the SB bank_id directly maps to one or more clearing sessions
(one per clearing type if the bank runs MORNING + AFTERNOON sessions).

In AGENCY_SB_RELAY mode: the agency creates a clearing session per upstream SB.
The sb_connection_id ties the session to the Agency's SB connector.

Session lifecycle: OPEN → SEALED → SUBMITTED → RECONCILED
  OPEN:         Accepting new instrument lot assignments
  SEALED:       No more lots accepted; endorsement / NGCH file build starts
  SUBMITTED:    NGCH file transmitted; awaiting acknowledgement
  RECONCILED:   Settlement report received, matched, RRF generated

total_amount_range stores a bucket (STANDARD / HIGH_VALUE / VERY_HIGH_VALUE) for
reporting purposes — never the exact total per RBI data minimisation requirements.

Revision ID: 20260705_add_clearing_sessions
Revises: 20260705_add_sb_connections
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_add_clearing_sessions"
down_revision = "20260705_add_sb_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "clearing_sessions",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False, comment="SB bank_id — always the NGCH member"),
        sa.Column(
            "sb_connection_id",
            sa.Text(),
            nullable=True,
            comment="FK to cts.sb_connections — populated in AGENCY_SB_RELAY mode only",
        ),
        sa.Column("clearing_date", sa.Date(), nullable=False),
        sa.Column(
            "session_type",
            sa.Text(),
            nullable=False,
            comment="MORNING | AFTERNOON | EVENING — NPCI clearing session designation",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="OPEN",
            comment="OPEN | SEALED | SUBMITTED | RECONCILED | EXCEPTION",
        ),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sealed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "npci_ack_ref",
            sa.Text(),
            nullable=True,
            comment="NGCH acknowledgement reference number",
        ),
        sa.Column(
            "total_instruments",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_amount_range",
            sa.Text(),
            nullable=True,
            comment="STANDARD | HIGH_VALUE | VERY_HIGH_VALUE — bucketed, never exact amount",
        ),
        sa.Column(
            "rrf_generated",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Return Reason File generated and filed to NGCH",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
        sa.PrimaryKeyConstraint("session_id"),
        schema="cts",
    )

    # One session per bank per clearing date per session type (NPCI enforces this)
    op.create_index(
        "uq_clearing_sessions_bank_date_type",
        "clearing_sessions",
        ["bank_id", "clearing_date", "session_type"],
        unique=True,
        schema="cts",
    )

    # Fast lookup: open sessions for a bank (lot assignment checks this)
    op.create_index(
        "ix_clearing_sessions_bank_status",
        "clearing_sessions",
        ["bank_id", "status"],
        schema="cts",
    )

    # Fast lookup: sessions for a specific SB connection (Agency mode reconciliation)
    op.create_index(
        "ix_clearing_sessions_sb_connection",
        "clearing_sessions",
        ["sb_connection_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_clearing_sessions_sb_connection", table_name="clearing_sessions", schema="cts")
    op.drop_index("ix_clearing_sessions_bank_status", table_name="clearing_sessions", schema="cts")
    op.drop_index("uq_clearing_sessions_bank_date_type", table_name="clearing_sessions", schema="cts")
    op.drop_table("clearing_sessions", schema="cts")
