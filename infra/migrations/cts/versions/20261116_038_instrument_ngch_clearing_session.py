"""Link an instrument to the clearing session it was filed in.

cheque_instruments.clearing_session_id holds the SCANNER (hub) session id the cheque was captured in, as text. The clearing session
NGCH knows about is a different thing (cts.clearing_sessions.session_id, a UUID), and nothing linked an instrument to it, so a
session's figures could only be scoped by clearing date. This adds the link: nullable, set when the session's lots are sealed for filing.
Additive only (no data moved, nothing dropped).

Revision ID: 20261116_038
Revises: 20261029_037
Create Date: 2026-11-16
"""
from alembic import op

revision = "20261116_038"
down_revision = "20261029_037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cts.cheque_instruments ADD COLUMN IF NOT EXISTS ngch_clearing_session_id UUID")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cts_instruments_ngch_session ON cts.cheque_instruments (bank_id, ngch_clearing_session_id) "
               "WHERE ngch_clearing_session_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cts.ix_cts_instruments_ngch_session")
    op.execute("ALTER TABLE cts.cheque_instruments DROP COLUMN IF EXISTS ngch_clearing_session_id")
