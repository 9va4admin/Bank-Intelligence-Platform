"""cts.lots: endorsement result columns (update_lot_status wrote columns that never existed).

Revision ID: 20260921_027
Revises: 20260921_026
Create Date: 2026-09-21
"""
from alembic import op

revision = "20260921_027"
down_revision = "20260921_026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cts.lots ADD COLUMN IF NOT EXISTS endorsed_count INTEGER")
    op.execute("ALTER TABLE cts.lots ADD COLUMN IF NOT EXISTS endorsement_failed_count INTEGER")
    op.execute("ALTER TABLE cts.lots ADD COLUMN IF NOT EXISTS endorsed_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE cts.lots DROP COLUMN IF EXISTS endorsed_at")
    op.execute("ALTER TABLE cts.lots DROP COLUMN IF EXISTS endorsement_failed_count")
    op.execute("ALTER TABLE cts.lots DROP COLUMN IF EXISTS endorsed_count")
