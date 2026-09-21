"""Outward instrument record: lot assignment, image keys and CHI-spec fields on cts.cheque_instruments.

Until now the outward scan path stored only a masked cts.outward_scan_events row, so endorsement and the
NGCH file builder (which read these columns) had no data. Outward rows use direction='OUTWARD'.

Revision ID: 20260921_025
Revises: 20260921_024
Create Date: 2026-09-21
"""
from alembic import op

revision = "20260921_025"
down_revision = "20260921_024"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("lot_id", "TEXT"),
    ("image_front_bw_key", "TEXT"),
    ("image_back_bw_key", "TEXT"),
    ("image_front_gray_key", "TEXT"),
    ("image_back_endorsed_key", "TEXT"),
    ("width_px", "INTEGER"),
    ("height_px", "INTEGER"),
    ("dpi", "INTEGER"),
    ("bit_depth", "INTEGER"),
    ("cycle_no", "TEXT"),
    ("payor_bank_rout_no", "TEXT"),
    ("presenting_bank_rout_no", "TEXT"),
    ("trans_code", "TEXT"),
    ("doc_type", "TEXT"),
)


def upgrade() -> None:
    for name, typ in _COLUMNS:
        op.execute(f"ALTER TABLE cts.cheque_instruments ADD COLUMN IF NOT EXISTS {name} {typ}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cheque_instruments_lot ON cts.cheque_instruments (bank_id, lot_id) "
               "WHERE lot_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cts.ix_cheque_instruments_lot")
    for name, _ in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE cts.cheque_instruments DROP COLUMN IF EXISTS {name}")
