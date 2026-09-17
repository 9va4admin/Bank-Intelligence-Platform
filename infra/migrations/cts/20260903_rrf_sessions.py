"""
cts.rrf_sessions — Return Reason File (RRF) generation sessions.

One row per clearing session that generates an RRF file. Written by the
generate_rrf activity in SessionReconciliationWorkflow using INSERT … ON CONFLICT
(session_id, bank_id) DO UPDATE — making it idempotent on Temporal retries.

Schema derived from the exact INSERT statement in:
  modules/cts/workflows/activities/session_reconciliation_activities.py:202-215

Revision: 20260903_rrf_sessions
"""
from alembic import op
import sqlalchemy as sa

revision = "20260903_rrf_sessions"
down_revision = "20260903_postdated_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "rrf_sessions",
        sa.Column("session_id",       sa.Text,                         nullable=False),
        sa.Column("bank_id",          sa.Text,                         nullable=False),
        sa.Column("clearing_date",    sa.Date,                         nullable=False),
        sa.Column("bank_ifsc",        sa.Text,                         nullable=False),
        sa.Column("rrf_path",         sa.Text,                         nullable=False),
        sa.Column("exception_count",  sa.Integer,                      nullable=False,
                  server_default="0"),
        sa.Column("created_at",       sa.TIMESTAMP(timezone=True),     nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at",       sa.TIMESTAMP(timezone=True),     nullable=True),
        sa.PrimaryKeyConstraint("session_id", "bank_id"),
        schema="cts",
    )

    op.create_index(
        "ix_rrf_sessions_bank_date",
        "rrf_sessions",
        ["bank_id", "clearing_date"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_rrf_sessions_bank_date", table_name="rrf_sessions", schema="cts")
    op.drop_table("rrf_sessions", schema="cts")
