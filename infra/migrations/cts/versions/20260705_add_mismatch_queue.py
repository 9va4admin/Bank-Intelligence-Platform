"""add cts.mismatch_queue table

MismatchQueue — holds instruments where the Vision LLM result (amount, payee, date)
does not match what the scanner OCR reported. In the new Presentment flow, Vision
runs LAST (after lot assignment). A mismatch causes the instrument to be HELD at
the PU level until the originating branch confirms GO_AHEAD or REJECTED.

Lifecycle: HELD → GO_AHEAD (branch confirms → lot stays, instrument proceeds)
           HELD → REJECTED (branch rejects → lot removed, return reason filed)
           HELD → TIMEOUT_REJECTED (4-hour auto-reject via MismatchResolutionWorkflow)

vision_finding and scanner_data are stored as JSONB because the structure varies by
what was mismatched (amount only, amount+payee, date only, etc.).

Revision ID: 20260705_add_mismatch_queue
Revises: 20260705_add_clearing_sessions
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260705_add_mismatch_queue"
down_revision = "20260705_add_clearing_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "mismatch_queue",
        sa.Column("mismatch_id", sa.Text(), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Text(),
            nullable=False,
            comment="FK to cts.cheque_instruments.instrument_id",
        ),
        sa.Column(
            "branch_id",
            sa.Text(),
            nullable=False,
            comment="FK to cts.branches.branch_id — the originating branch",
        ),
        sa.Column(
            "pu_id",
            sa.Text(),
            nullable=False,
            comment="FK to cts.processing_units.pu_id — PU where instrument is HELD",
        ),
        sa.Column(
            "lot_id",
            sa.Text(),
            nullable=True,
            comment="The lot this instrument was assigned to before the hold",
        ),
        sa.Column(
            "vision_finding",
            JSONB(),
            nullable=False,
            comment=(
                "What Vision LLM reported: {amount_figures, amount_words, payee_masked, "
                "cheque_date, alteration_detected, confidence}. Never store raw account number."
            ),
        ),
        sa.Column(
            "scanner_data",
            JSONB(),
            nullable=False,
            comment=(
                "What scanner OCR reported: {amount_figures, amount_words, payee_masked, "
                "cheque_date, micr_line_suffix, oem_confidence}. Masked, never plain PII."
            ),
        ),
        sa.Column(
            "mismatch_fields",
            JSONB(),
            nullable=False,
            comment='Array of field names that mismatched: ["amount_figures", "payee_masked"]',
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="HELD",
            comment="HELD | GO_AHEAD | REJECTED | TIMEOUT_REJECTED",
        ),
        sa.Column(
            "held_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "resolved_by",
            sa.Text(),
            nullable=True,
            comment="operator_id who resolved — null for timeout auto-rejection",
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "workflow_run_id",
            sa.Text(),
            nullable=True,
            comment="Temporal MismatchResolutionWorkflow run ID — for signal delivery",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("mismatch_id"),
        schema="cts",
    )

    # One open mismatch per instrument (cannot be in queue twice simultaneously)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_mismatch_queue_instrument_open
        ON cts.mismatch_queue (instrument_id)
        WHERE status = 'HELD'
        """
    )

    # Fast lookup: all HELD mismatches for a branch (Branch Portal Mismatch Queue screen)
    op.create_index(
        "ix_mismatch_queue_branch_status",
        "mismatch_queue",
        ["branch_id", "status"],
        schema="cts",
    )

    # Fast lookup: all HELD mismatches at a PU (PU admin view)
    op.create_index(
        "ix_mismatch_queue_pu_status",
        "mismatch_queue",
        ["pu_id", "status"],
        schema="cts",
    )

    # Fast lookup: by bank + held_at (for 4-hour timeout watchdog)
    op.create_index(
        "ix_mismatch_queue_held_at",
        "mismatch_queue",
        ["held_at"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_mismatch_queue_held_at", table_name="mismatch_queue", schema="cts")
    op.drop_index("ix_mismatch_queue_pu_status", table_name="mismatch_queue", schema="cts")
    op.drop_index("ix_mismatch_queue_branch_status", table_name="mismatch_queue", schema="cts")
    op.execute("DROP INDEX IF EXISTS cts.uq_mismatch_queue_instrument_open")
    op.drop_table("mismatch_queue", schema="cts")
