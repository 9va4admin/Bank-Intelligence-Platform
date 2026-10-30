"""Custody of original instruments: kept at the branch, handed over in batches, received at central storage, retained, disposed of.

Revision ID: 20261029_036
Revises: 20261029_035
Create Date: 2026-10-29
"""
from alembic import op

revision = "20261029_036"
down_revision = "20261029_035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS cts.custody_handovers (
            bank_id      TEXT NOT NULL,
            handover_id  TEXT NOT NULL,
            branch_id    TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'IN_TRANSIT' CHECK (status IN ('IN_TRANSIT','RECEIVED','DISCREPANCY')),
            courier_ref  TEXT,
            notes        TEXT,
            item_count   INTEGER NOT NULL,
            created_by   TEXT NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            received_by  TEXT,
            received_at  TIMESTAMPTZ,
            PRIMARY KEY (bank_id, handover_id)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS cts.instrument_custody (
            bank_id          TEXT NOT NULL,
            instrument_id    TEXT NOT NULL,
            branch_id        TEXT NOT NULL,
            status           TEXT NOT NULL CHECK (status IN ('IN_TRANSIT','STORED','MISSING','DISPOSED')),
            handover_id      TEXT,
            location         TEXT,
            received_by      TEXT,
            received_at      TIMESTAMPTZ,
            retention_until  DATE,
            disposed_by      TEXT,
            disposed_at      TIMESTAMPTZ,
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (bank_id, instrument_id)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_custody_handover ON cts.instrument_custody (bank_id, handover_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_custody_retention ON cts.instrument_custody (bank_id, status, retention_until)")
    # Append-only history of every step; nothing here is ever updated or deleted.
    op.execute("""
        CREATE TABLE IF NOT EXISTS cts.custody_events (
            event_id       UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
            bank_id        TEXT NOT NULL,
            instrument_id  TEXT NOT NULL,
            handover_id    TEXT,
            event          TEXT NOT NULL,
            actor          TEXT NOT NULL,
            detail         TEXT,
            at             TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_custody_events_instrument ON cts.custody_events (bank_id, instrument_id, at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.custody_events")
    op.execute("DROP TABLE IF EXISTS cts.instrument_custody")
    op.execute("DROP TABLE IF EXISTS cts.custody_handovers")
