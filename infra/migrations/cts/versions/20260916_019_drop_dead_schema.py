"""Drop dead CTS schema objects: 1 table + 2 columns with zero codebase references.

Schema audit (2026-09-16) identified the following as having no SQL queries,
no Python references, no workflow references, and no mention in any roadmap doc:

Tables dropped:
  cts.sb_connections  — superseded by Istio mTLS for service identity; SB→SB
                        communication goes through NGCH adapter, not this table.

Columns dropped:
  cts.agent_decisions.human_review_routed_to  — never populated; routing target
        is tracked in Temporal workflow state, not in the decisions row.
  cts.cheque_instruments.vision_cascade_level — replaced by the ocr_engines_used
        JSON array on agent_decisions; cascade level is implicit in the list.

Classification methodology:
  DROP   = zero refs in modules/, apps/, shared/, tests/, docs/, CLAUDE.md
  WIRE UP = code has SQL but no catalog entry → Q-numbers added in query-catalog.html
  KEEP-PLANNED = mentioned in CLAUDE.md/roadmap as future feature

Revision ID: 20260916_019
Revises: 20260916_018
Create Date: 2026-09-16
"""
from alembic import op

revision = "20260916_019"
down_revision = "20260916_018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── DROP TABLE cts.sb_connections ─────────────────────────────────────────
    # Zero Python / SQL refs. SB-to-SB routing handled by NGCH adapter + Istio.
    op.drop_table("sb_connections", schema="cts")

    # ── DROP COLUMN cts.agent_decisions.human_review_routed_to ───────────────
    # Routing target captured in Temporal workflow state; never written to DB.
    op.drop_column("agent_decisions", "human_review_routed_to", schema="cts")

    # ── DROP COLUMN cts.cheque_instruments.vision_cascade_level ──────────────
    # Replaced by ocr_engines_used[] on agent_decisions row.
    op.drop_column("cheque_instruments", "vision_cascade_level", schema="cts")


def downgrade() -> None:
    import sqlalchemy as sa

    op.add_column(
        "cheque_instruments",
        sa.Column("vision_cascade_level", sa.Text(), nullable=True),
        schema="cts",
    )
    op.add_column(
        "agent_decisions",
        sa.Column("human_review_routed_to", sa.Text(), nullable=True),
        schema="cts",
    )
    op.create_table(
        "sb_connections",
        sa.Column("connection_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="cts",
    )
