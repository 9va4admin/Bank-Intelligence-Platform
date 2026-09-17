"""alter cts.ngch_submissions + cts.agent_decisions — add PU and session columns

Additive-only migration (backwards-compatible for one release):
  - All new columns nullable initially
  - NOT NULL constraint added in next release once backfill is complete

cts.ngch_submissions new columns:
  pu_id             TEXT   — which PU submitted this filing
  sb_connection_id  TEXT   — Agency mode: which SB connection was used for relay
  session_id        TEXT   — FK to cts.clearing_sessions

cts.agent_decisions new columns:
  pu_id                   TEXT   — PU that ran this agent (inward)
  smb_id                  TEXT   — SMB whose instrument was processed
  human_review_routed_to  TEXT   — which SMB branch the human review queue item went to

Revision ID: 20260706_alter_ngch_submissions_add_pu
Revises: 20260706_alter_cheque_instruments_add_pu
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa

revision = "20260706_alter_ngch_submissions_add_pu"
down_revision = "20260706_alter_cheque_instruments_add_pu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cts.ngch_submissions ──────────────────────────────────────────────────
    op.add_column(
        "ngch_submissions",
        sa.Column(
            "pu_id",
            sa.Text(),
            nullable=True,
            comment="FK to cts.processing_units.pu_id — which PU generated this filing",
        ),
        schema="cts",
    )
    op.add_column(
        "ngch_submissions",
        sa.Column(
            "sb_connection_id",
            sa.Text(),
            nullable=True,
            comment="FK to cts.sb_connections.sb_connection_id — null in SB_NGCH mode",
        ),
        schema="cts",
    )
    op.add_column(
        "ngch_submissions",
        sa.Column(
            "session_id",
            sa.Text(),
            nullable=True,
            comment="FK to cts.clearing_sessions.session_id — the session this filing belongs to",
        ),
        schema="cts",
    )

    op.create_index(
        "ix_ngch_submissions_pu_id",
        "ngch_submissions",
        ["pu_id"],
        schema="cts",
    )
    op.create_index(
        "ix_ngch_submissions_session_id",
        "ngch_submissions",
        ["session_id"],
        schema="cts",
    )

    # ── cts.agent_decisions ───────────────────────────────────────────────────
    op.add_column(
        "agent_decisions",
        sa.Column(
            "pu_id",
            sa.Text(),
            nullable=True,
            comment="FK to cts.processing_units.pu_id — PU that ran the inward processing agent",
        ),
        schema="cts",
    )
    op.add_column(
        "agent_decisions",
        sa.Column(
            "smb_id",
            sa.Text(),
            nullable=True,
            comment="SMB whose instrument was processed — null for SB's own instruments",
        ),
        schema="cts",
    )
    op.add_column(
        "agent_decisions",
        sa.Column(
            "human_review_routed_to",
            sa.Text(),
            nullable=True,
            comment=(
                "SMB branch_id where the human review queue item was sent. "
                "Human review always at SMB — never at SB — per architecture decision."
            ),
        ),
        schema="cts",
    )

    op.create_index(
        "ix_agent_decisions_pu_id",
        "agent_decisions",
        ["pu_id"],
        schema="cts",
    )
    op.create_index(
        "ix_agent_decisions_smb_id",
        "agent_decisions",
        ["smb_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_agent_decisions_smb_id", table_name="agent_decisions", schema="cts")
    op.drop_index("ix_agent_decisions_pu_id", table_name="agent_decisions", schema="cts")
    op.drop_column("agent_decisions", "human_review_routed_to", schema="cts")
    op.drop_column("agent_decisions", "smb_id", schema="cts")
    op.drop_column("agent_decisions", "pu_id", schema="cts")

    op.drop_index("ix_ngch_submissions_session_id", table_name="ngch_submissions", schema="cts")
    op.drop_index("ix_ngch_submissions_pu_id", table_name="ngch_submissions", schema="cts")
    op.drop_column("ngch_submissions", "session_id", schema="cts")
    op.drop_column("ngch_submissions", "sb_connection_id", schema="cts")
    op.drop_column("ngch_submissions", "pu_id", schema="cts")
