"""cts.agent_decisions + cts.outward_scan_events: add instrument_category
(CHEQUE | DEMAND_DRAFT). These are the tables the live Inward/Outward queue,
Reports, and Reconciliation screens actually read from -- cheque_instruments
(20261012_028) is the NGCH-batch-presentment table, a separate write path.

Revision ID: 20261012_029
Revises: 20261012_028
Create Date: 2026-10-12
"""
from alembic import op

revision = "20261012_029"
down_revision = "20261012_028"
branch_labels = None
depends_on = None

_TABLES = ("cts.agent_decisions", "cts.outward_scan_events")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN IF NOT EXISTS instrument_category TEXT NOT NULL DEFAULT 'CHEQUE'"
        )
        constraint = f"ck_{table.split('.')[1]}_instrument_category"
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{constraint}') THEN
                    ALTER TABLE {table}
                    ADD CONSTRAINT {constraint}
                    CHECK (instrument_category IN ('CHEQUE', 'DEMAND_DRAFT'));
                END IF;
            END $$;
            """
        )
        index = f"ix_{table.split('.')[1]}_instrument_category"
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index} ON {table} (bank_id, instrument_category)"
        )


def downgrade() -> None:
    for table in _TABLES:
        index = f"ix_{table.split('.')[1]}_instrument_category"
        constraint = f"ck_{table.split('.')[1]}_instrument_category"
        op.execute(f"DROP INDEX IF EXISTS cts.{index}")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS instrument_category")
