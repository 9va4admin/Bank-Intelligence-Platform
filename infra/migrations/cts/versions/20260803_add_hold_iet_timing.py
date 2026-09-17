"""
Add IET timing columns to cts.instrument_holds

Stores pre-computed timing fields at hold placement and release so the
audit trail and the Admin Allocation Control Panel can show IET impact
without recalculating from raw timestamps at query time.

Revision: 20260803_add_hold_iet_timing
"""
from alembic import op

revision = "20260803_add_hold_iet_timing"
down_revision = "20260803_add_instrument_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cts.instrument_holds
            ADD COLUMN IF NOT EXISTS iet_remaining_at_hold_start  DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS hold_duration_seconds         DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS iet_remaining_at_release      DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS iet_consumed_on_hold          DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS released_by                   TEXT
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE cts.instrument_holds
            DROP COLUMN IF EXISTS iet_remaining_at_hold_start,
            DROP COLUMN IF EXISTS hold_duration_seconds,
            DROP COLUMN IF EXISTS iet_remaining_at_release,
            DROP COLUMN IF EXISTS iet_consumed_on_hold,
            DROP COLUMN IF EXISTS released_by
    """)
