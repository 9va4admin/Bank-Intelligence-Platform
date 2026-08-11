"""
add cts.instrument_holds table

Stores hold records placed by ops_reviewers on inward instruments.
CRITICAL: IET deadline (iet_deadline) is immutable — the IET clock never
pauses during a hold. The IETWatchdogWorkflow continues to run regardless.

Revision: 20260803_add_instrument_holds
"""
from alembic import op

revision = "20260803_add_instrument_holds"
down_revision = "20260803_add_layer2_change_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS cts.instrument_holds (
            hold_id                 TEXT        NOT NULL DEFAULT gen_random_uuid()::TEXT,
            instrument_id           TEXT        NOT NULL,
            bank_id                 TEXT        NOT NULL,
            held_by                 TEXT        NOT NULL,
            held_at                 DOUBLE PRECISION NOT NULL,
            iet_deadline            DOUBLE PRECISION NOT NULL,
            hold_reason             TEXT        NOT NULL,
            branch_notified_at      DOUBLE PRECISION,
            released_at             DOUBLE PRECISION,
            released_by             TEXT,
            branch_note             TEXT,
            branch_recommendation   TEXT,
            PRIMARY KEY (hold_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_instrument_holds_bank_active
            ON cts.instrument_holds (bank_id, released_at)
            WHERE released_at IS NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_instrument_holds_instrument
            ON cts.instrument_holds (instrument_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_instrument_holds_instrument")
    op.execute("DROP INDEX IF EXISTS idx_instrument_holds_bank_active")
    op.execute("DROP TABLE IF EXISTS cts.instrument_holds")
