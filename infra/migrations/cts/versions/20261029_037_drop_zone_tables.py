"""Drop the zone concept from the schema: clearing zones, processing centres, RPC zones and every column that pointed at them.

A bank files to one grid and a branch maps to a processing unit (CLAUDE.md section 2.12). Nothing reads or writes these
any more: clearing sessions carry no centre, instruments no centre or zone, reviewers are scoped by PU.

This drops columns in one migration, which the database rules normally forbid (rename -> keep -> drop). The bank owner asked for
it explicitly and the columns have been unused since 20261029_034; the downgrade restores them empty and nullable.

Revision ID: 20261029_037
Revises: 20261029_036
Create Date: 2026-10-29
"""
from alembic import op

revision = "20261029_037"
down_revision = "20261029_036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Foreign keys to the centre/zone tables go with the tables; the center_id columns are then plain UUIDs, so drop them.
    op.execute("DROP TABLE IF EXISTS cts.rpc_zones CASCADE")
    op.execute("DROP TABLE IF EXISTS cts.processing_centers CASCADE")
    op.execute("DROP TABLE IF EXISTS cts.clearing_zones CASCADE")
    op.execute("ALTER TABLE cts.clearing_sessions DROP COLUMN IF EXISTS center_id")
    op.execute("ALTER TABLE cts.cheque_instruments DROP COLUMN IF EXISTS center_id")
    op.execute("ALTER TABLE cts.branches_master DROP COLUMN IF EXISTS center_id")
    op.execute("ALTER TABLE cts.processing_units DROP COLUMN IF EXISTS clearing_zone")
    op.execute("DROP INDEX IF EXISTS cts.ix_cts_human_review_zone_pending")
    op.execute("ALTER TABLE cts.human_review_items DROP COLUMN IF EXISTS assigned_zone")
    for table in ("cheque_instruments", "micr_routing_rules"):
        op.execute(f"ALTER TABLE IF EXISTS cts.{table} DROP COLUMN IF EXISTS clearing_zone")


def downgrade() -> None:
    # Structure only, empty and nullable: the old data is not recoverable and nothing needs it.
    op.execute("CREATE TABLE IF NOT EXISTS cts.clearing_zones (zone_id TEXT PRIMARY KEY, zone_name TEXT, is_active BOOLEAN DEFAULT TRUE)")
    op.execute("CREATE TABLE IF NOT EXISTS cts.processing_centers (center_id UUID PRIMARY KEY, bank_id TEXT, zone_id TEXT, "
               "center_name TEXT, center_code TEXT, is_active BOOLEAN DEFAULT TRUE)")
    op.execute("ALTER TABLE cts.clearing_sessions ADD COLUMN IF NOT EXISTS center_id UUID")
    op.execute("ALTER TABLE cts.cheque_instruments ADD COLUMN IF NOT EXISTS center_id UUID")
    op.execute("ALTER TABLE cts.branches_master ADD COLUMN IF NOT EXISTS center_id UUID")
    op.execute("ALTER TABLE cts.processing_units ADD COLUMN IF NOT EXISTS clearing_zone TEXT")
    op.execute("ALTER TABLE cts.human_review_items ADD COLUMN IF NOT EXISTS assigned_zone TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cts_human_review_zone_pending ON cts.human_review_items (assigned_zone, status)")
    op.execute("ALTER TABLE cts.cheque_instruments ADD COLUMN IF NOT EXISTS clearing_zone TEXT")
    op.execute("ALTER TABLE IF EXISTS cts.micr_routing_rules ADD COLUMN IF NOT EXISTS clearing_zone TEXT")
