"""
Add live-flow columns to cts.cheque_instruments required by the inward batch
ingestion pipeline and the CTSInwardMonitor UI.

Columns added:
  processing_stage   — coarse pipeline stage (RECEIVED | OCR | DECISION | FILED)
  processing_status  — fine-grained status within the stage
  micr_suffix        — last 4 chars of cheque serial (for display, non-PII)
  decision_outcome   — APPROVED | RETURNED | STP_CONFIRMED | HUMAN_REVIEW
  fraud_score        — mirrored from agent_decisions on decision; nullable

Also adds inward_batch_id + direction (INWARD | OUTWARD) to link the instrument
back to the NGCH batch that delivered it.

Revision: 20260913_inward_instrument_live_columns
Revises:  20260909_phantom_columns
"""
from alembic import op
import sqlalchemy as sa

revision = "20260913_inward_instrument_live_columns"
down_revision = "20260909_phantom_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Direction: INWARD (from NGCH to drawee) | OUTWARD (presentee-side scanning)
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "direction",
            sa.Text(),
            nullable=False,
            server_default="OUTWARD",
            comment="INWARD (drawee, from NGCH batch) | OUTWARD (presentee, scanner)",
        ),
        schema="cts",
    )

    # Inward batch reference — links to InwardBatchIngestionWorkflow batch_id
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "inward_batch_id",
            sa.Text(),
            nullable=True,
            comment="Batch ID from NGCH inward delivery (parse_inward_batch)",
        ),
        schema="cts",
    )

    # Coarse pipeline stage — updated by workflow activities as processing proceeds
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "processing_stage",
            sa.Text(),
            nullable=True,
            server_default="RECEIVED",
            comment="RECEIVED | OCR | VISION | FRAUD | DECISION | REVIEW | FILED",
        ),
        schema="cts",
    )

    # Fine-grained status within stage — e.g. PENDING, RUNNING, COMPLETE, FAILED
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "processing_status",
            sa.Text(),
            nullable=True,
            server_default="PENDING",
            comment="Fine-grained status within processing_stage",
        ),
        schema="cts",
    )

    # Last 4 digits of MICR cheque serial — safe for display (non-PII)
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "micr_suffix",
            sa.Text(),
            nullable=True,
            comment="Last 4 chars of cheque serial number from MICR — display only",
        ),
        schema="cts",
    )

    # Decision outcome — mirrored from agent_decisions for single-table reads
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "decision_outcome",
            sa.Text(),
            nullable=True,
            comment="APPROVED | RETURNED | STP_CONFIRMED | HUMAN_REVIEW — set on NGCH filing",
        ),
        schema="cts",
    )

    # Fraud score — mirrored from agent_decisions; nullable until fraud activity runs
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "fraud_score",
            sa.Numeric(5, 4),
            nullable=True,
            comment="XGBoost fraud score [0,1] — mirrored from agent_decisions",
        ),
        schema="cts",
    )

    # Index for live-flow query (recent inward instruments per bank)
    op.create_index(
        "ix_cts_instruments_bank_direction_received",
        "cheque_instruments",
        ["bank_id", "direction", "received_at"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_cts_instruments_bank_direction_received",
                  table_name="cheque_instruments", schema="cts")
    op.drop_column("cheque_instruments", "fraud_score", schema="cts")
    op.drop_column("cheque_instruments", "decision_outcome", schema="cts")
    op.drop_column("cheque_instruments", "micr_suffix", schema="cts")
    op.drop_column("cheque_instruments", "processing_status", schema="cts")
    op.drop_column("cheque_instruments", "processing_stage", schema="cts")
    op.drop_column("cheque_instruments", "inward_batch_id", schema="cts")
    op.drop_column("cheque_instruments", "direction", schema="cts")
