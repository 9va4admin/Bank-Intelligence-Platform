"""
cts.eeh_sessions — add total_held column.

total_held tracks instruments that entered MISMATCH_HELD state during this
scanning session (UV anomaly, payee mismatch, etc.). Incremented by
OutwardScanWorkflow when a cheque is routed to MismatchResolutionWorkflow.

Revision: 20260902_eeh_sessions_add_total_held
Revises:  20260902_lots
"""
from alembic import op
import sqlalchemy as sa

revision = "20260902_eeh_sessions_add_total_held"
down_revision = "20260902_lots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eeh_sessions",
        sa.Column(
            "total_held",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Instruments routed to MISMATCH_HELD in this session",
        ),
        schema="cts",
    )


def downgrade() -> None:
    op.drop_column("eeh_sessions", "total_held", schema="cts")
