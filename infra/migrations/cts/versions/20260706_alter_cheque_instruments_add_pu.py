"""alter cts.cheque_instruments — add PU, branch, session, vision columns

Additive-only migration (backwards-compatible for one release per upgrade policy):
  - All new columns are nullable initially
  - NOT NULL constraint added in next release once backfill is verified
  - No existing data is modified

New columns:
  pu_id                TEXT          — FK to cts.processing_units (outward & inward)
  branch_id            TEXT          — originating branch (outward) or null (inward NGCH delivery)
  clearing_session_id  TEXT          — FK to cts.clearing_sessions (outward only)
  vision_result        JSONB         — cached Vision LLM output for the instrument
  vision_cascade_level TEXT          — L1 | L2 — which cascade tier ran

Revision ID: 20260706_alter_cheque_instruments_add_pu
Revises: 20260705_add_eeh_sessions
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260706_alter_cheque_instruments_add_pu"
down_revision = "20260705_add_eeh_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All nullable — per backwards-compatible migration policy (Section 2.6 of CLAUDE.md)
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "pu_id",
            sa.Text(),
            nullable=True,
            comment="FK to cts.processing_units.pu_id — routing key for PU-scoped Kafka/Temporal",
        ),
        schema="cts",
    )
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "branch_id",
            sa.Text(),
            nullable=True,
            comment="Originating branch (outward instruments only; null for inward from NGCH)",
        ),
        schema="cts",
    )
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "clearing_session_id",
            sa.Text(),
            nullable=True,
            comment="FK to cts.clearing_sessions.session_id — outward instruments only",
        ),
        schema="cts",
    )
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "vision_result",
            JSONB(),
            nullable=True,
            comment=(
                "Cached Vision LLM output: {amount_figures, amount_words, payee_masked, "
                "cheque_date, alteration_detected, confidence, tamper_risk}. "
                "Never store raw account number in this JSONB."
            ),
        ),
        schema="cts",
    )
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "vision_cascade_level",
            sa.Text(),
            nullable=True,
            comment="L1 | L2 — which cascade tier (Qwen2-VL 7B vs 72B) produced the vision_result",
        ),
        schema="cts",
    )

    # Index for PU-scoped queries (ops dashboard: instruments at this PU today)
    op.create_index(
        "ix_cheque_instruments_pu_id",
        "cheque_instruments",
        ["pu_id"],
        schema="cts",
    )

    # Index for session-level reconciliation queries
    op.create_index(
        "ix_cheque_instruments_session_id",
        "cheque_instruments",
        ["clearing_session_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_cheque_instruments_session_id", table_name="cheque_instruments", schema="cts")
    op.drop_index("ix_cheque_instruments_pu_id", table_name="cheque_instruments", schema="cts")
    op.drop_column("cheque_instruments", "vision_cascade_level", schema="cts")
    op.drop_column("cheque_instruments", "vision_result", schema="cts")
    op.drop_column("cheque_instruments", "clearing_session_id", schema="cts")
    op.drop_column("cheque_instruments", "branch_id", schema="cts")
    op.drop_column("cheque_instruments", "pu_id", schema="cts")
