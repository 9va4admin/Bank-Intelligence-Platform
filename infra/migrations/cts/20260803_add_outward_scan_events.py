"""add cts.outward_scan_events table

Stores one row per OutwardScanWorkflow completion so the BranchScanMonitor
SSE/polling endpoint can serve real-time scan results to the branch portal.

Written by the record_outward_scan_event activity at the end of every
OutwardScanWorkflow.run() — regardless of outcome (ACCEPTED / CTS_REJECTED /
MISMATCH_HELD).

Revision ID: 20260803_add_outward_scan_events
Revises: 20260803_add_instrument_holds
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa

revision = "20260803_add_outward_scan_events"
down_revision = "20260803_add_instrument_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")
    op.execute("""
        CREATE TABLE cts.outward_scan_events (
            event_id        UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
            bank_id         TEXT        NOT NULL,
            branch_id       TEXT,
            session_id      TEXT,
            scan_id         TEXT        NOT NULL,
            instrument_id   TEXT,
            micr_suffix     VARCHAR(4),
            payee_display   TEXT,
            amount_range    TEXT,
            outcome         TEXT        NOT NULL,
            lot_id          TEXT,
            mismatch_id     TEXT,
            mismatch_fields TEXT[],
            reject_reason   TEXT,
            scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX idx_outward_scan_events_bank_ts
            ON cts.outward_scan_events (bank_id, scanned_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_outward_scan_events_session
            ON cts.outward_scan_events (session_id, scanned_at DESC)
        WHERE session_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_outward_scan_events_session")
    op.execute("DROP INDEX IF EXISTS idx_outward_scan_events_bank_ts")
    op.execute("DROP TABLE IF EXISTS cts.outward_scan_events")
