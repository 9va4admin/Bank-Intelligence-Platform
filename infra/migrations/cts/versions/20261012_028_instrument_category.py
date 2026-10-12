"""cts.cheque_instruments: add instrument_category (CHEQUE | DEMAND_DRAFT).

Distinct from the existing `instrument_type` column, which encodes the
CTS-2010/MICR/NON_MICR clearing-grade classification -- not instrument kind.
Reusing that column would silently collide with its existing semantics.

Revision ID: 20261012_028
Revises: 20260921_027
Create Date: 2026-10-12
"""
from alembic import op

revision = "20261012_028"
down_revision = "20260921_027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cts.cheque_instruments "
        "ADD COLUMN IF NOT EXISTS instrument_category TEXT NOT NULL DEFAULT 'CHEQUE'"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_cheque_instruments_instrument_category'
            ) THEN
                ALTER TABLE cts.cheque_instruments
                ADD CONSTRAINT ck_cheque_instruments_instrument_category
                CHECK (instrument_category IN ('CHEQUE', 'DEMAND_DRAFT'));
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cheque_instruments_instrument_category "
        "ON cts.cheque_instruments (bank_id, instrument_category)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cts.ix_cheque_instruments_instrument_category")
    op.execute(
        "ALTER TABLE cts.cheque_instruments "
        "DROP CONSTRAINT IF EXISTS ck_cheque_instruments_instrument_category"
    )
    op.execute("ALTER TABLE cts.cheque_instruments DROP COLUMN IF EXISTS instrument_category")
