"""
cts.postdated_holds — post-dated cheque hold state for PostDatedHoldWorkflow.

One row per cheque instrument held because its cheque_date is in the future.
Written by store_postdated_hold activity on workflow start; updated by
mark_hold_cancelled when a cancel signal arrives before release_date.

Schema derived from the exact INSERT and UPDATE statements in:
  modules/cts/workflows/activities/postdated_hold_activities.py

Revision: 20260903_postdated_holds
"""
from alembic import op
import sqlalchemy as sa

revision = "20260903_postdated_holds"
down_revision = "20260902_lots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "postdated_holds",
        sa.Column("instrument_id",  sa.Text,                            primary_key=True),
        sa.Column("bank_id",        sa.Text,                            nullable=False),
        sa.Column("release_date",   sa.Date,                            nullable=False),
        sa.Column("held_at",        sa.TIMESTAMP(timezone=True),        nullable=False),
        sa.Column("status",         sa.Text,                            nullable=False,
                  server_default="PENDING"),
        sa.Column("cancel_reason",  sa.Text,                            nullable=True),
        sa.Column("cancelled_at",   sa.TIMESTAMP(timezone=True),        nullable=True),
        sa.Column("created_at",     sa.TIMESTAMP(timezone=True),        nullable=False,
                  server_default=sa.text("now()")),
        schema="cts",
    )

    op.create_index(
        "ix_postdated_holds_bank_release",
        "postdated_holds",
        ["bank_id", "release_date"],
        schema="cts",
    )
    op.create_index(
        "ix_postdated_holds_bank_status",
        "postdated_holds",
        ["bank_id", "status"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_postdated_holds_bank_status",  table_name="postdated_holds", schema="cts")
    op.drop_index("ix_postdated_holds_bank_release",  table_name="postdated_holds", schema="cts")
    op.drop_table("postdated_holds", schema="cts")
