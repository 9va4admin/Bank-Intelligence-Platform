"""
cts.lots — scanning batch lot table.

Tracks physical scanning batches (up to max_instruments cheques each).
One OPEN lot per branch per clearing day. Auto-sealed when full; Hub Manager
can also manually seal via PATCH /v1/cts/outward/lots/{lot_id}/seal.

Distinct from clearing session lots (managed by ClearingSessionWorkflow).
This table is the real-time view for CTSHubDashboard.

Revision: 20260902_lots
Revises:  20260901_scanner_tokens_add_session
"""
from alembic import op
import sqlalchemy as sa

revision = "20260902_lots"
down_revision = "20260901_scanner_tokens_add_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "lots",
        sa.Column("lot_id",           sa.Text,    nullable=False),
        sa.Column("bank_id",          sa.Text,    nullable=False),
        sa.Column("branch_id",        sa.Text,    nullable=False,
                  comment="FK cts.branches.branch_id"),
        sa.Column("session_id",       sa.Text,    nullable=False,
                  comment="FK cts.eeh_sessions.session_id"),
        sa.Column("clearing_date",    sa.Date,    nullable=False),
        sa.Column("sequence_number",  sa.Integer, nullable=False,
                  comment="Lot # within branch+day (1-based)"),
        sa.Column("status",           sa.Text,    nullable=False, server_default="OPEN",
                  comment="OPEN | SEALED"),
        sa.Column("instrument_count", sa.Integer, nullable=False, server_default="0",
                  comment="Number of instruments in this lot"),
        sa.Column("max_instruments",  sa.Integer, nullable=False, server_default="25",
                  comment="Auto-seal threshold (default CTS standard = 25)"),
        sa.Column("created_at",       sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("sealed_at",        sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("lot_id"),
        schema="cts",
    )

    # Only one OPEN lot per branch per day (partial unique index)
    op.execute("""
        CREATE UNIQUE INDEX uq_lots_branch_date_open
        ON cts.lots (branch_id, clearing_date)
        WHERE status = 'OPEN'
    """)

    op.create_index(
        "ix_lots_bank_date_status",
        "lots",
        ["bank_id", "clearing_date", "status"],
        schema="cts",
    )

    op.create_index(
        "ix_lots_session",
        "lots",
        ["session_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_table("lots", schema="cts")
