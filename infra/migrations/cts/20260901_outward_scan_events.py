"""
cts.outward_scan_session_events — per-instrument event log for outward scanning sessions.

Tracks every cheque position in a scanning session: submitted instruments,
double-feed detections, and imprinter faults. Drives the Branch Scan Dashboard.

NOTE: This is a DIFFERENT table from cts.outward_scan_events (20260803_add_outward_scan_events.py).
  cts.outward_scan_events  — one row per OutwardScanWorkflow completion (outcome-level)
  cts.outward_scan_session_events — one row per scanner event within a session (position-level)

Renamed from `outward_scan_events` to `outward_scan_session_events` to avoid conflict
with the pre-existing 20260803 table of the same name.

Revision: 20260901_outward_scan_events
"""
from alembic import op
import sqlalchemy as sa

revision = "20260901_outward_scan_events"
down_revision = "20260819_vault_batch_error_file"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "outward_scan_session_events",
        sa.Column("event_id",          sa.Text,        primary_key=True),
        sa.Column("bank_id",           sa.Text,        nullable=False),
        sa.Column("branch_id",         sa.Text,        nullable=True),
        sa.Column("session_id",        sa.Text,        nullable=False),
        sa.Column("scan_id",           sa.Text,        nullable=False),
        sa.Column("instrument_id",     sa.Text,        nullable=True),
        sa.Column("workflow_id",       sa.Text,        nullable=True),
        # SUBMITTED | DOUBLE_FEED_DETECTED | IMPRINTER_FAULT | UPLOAD_FAILED
        sa.Column("event_type",        sa.Text,        nullable=False),
        sa.Column("position_in_batch", sa.Integer,     nullable=True),
        sa.Column("cheque_number",     sa.Text,        nullable=True),
        sa.Column("micr_suffix",       sa.Text,        nullable=True),
        sa.Column("imprinter_stamped", sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("micr_source",       sa.Text,        nullable=True),
        sa.Column("created_at",        sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="cts",
    )

    op.create_index(
        "ix_outward_scan_session_events_session",
        "outward_scan_session_events",
        ["bank_id", "session_id", "created_at"],
        schema="cts",
    )
    op.create_index(
        "ix_outward_scan_session_events_branch_session",
        "outward_scan_session_events",
        ["branch_id", "session_id", "created_at"],
        schema="cts",
    )
    op.create_index(
        "ix_outward_scan_session_events_type",
        "outward_scan_session_events",
        ["bank_id", "event_type", "created_at"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_outward_scan_session_events_type",           table_name="outward_scan_session_events", schema="cts")
    op.drop_index("ix_outward_scan_session_events_branch_session", table_name="outward_scan_session_events", schema="cts")
    op.drop_index("ix_outward_scan_session_events_session",        table_name="outward_scan_session_events", schema="cts")
    op.drop_table("outward_scan_session_events", schema="cts")
