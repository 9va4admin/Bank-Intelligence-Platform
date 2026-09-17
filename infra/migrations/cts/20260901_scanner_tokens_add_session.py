"""
cts.scanner_tokens — add active_session_id for heartbeat state tracking.

The Go scanner agent posts its current active_session_id on every heartbeat.
NULL / empty string means the scanner is idle (no session open).
Non-empty means a scan session is actively running on that machine.

Revision: 20260901_scanner_tokens_add_session
"""
from alembic import op
import sqlalchemy as sa

revision = "20260901_scanner_tokens_add_session"
down_revision = "20260901_scanner_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scanner_tokens",
        sa.Column("active_session_id", sa.Text, nullable=True),
        schema="cts",
    )


def downgrade() -> None:
    op.drop_column("scanner_tokens", "active_session_id", schema="cts")
