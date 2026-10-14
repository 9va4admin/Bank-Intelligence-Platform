"""cts.cheque_instruments: monthly partitions through 2028-12 plus a DEFAULT partition.

Migration 003 created only 2026-06..2026-08. From 2026-09-01 every INSERT (inward and outward) failed with
"no partition of relation cheque_instruments found for row" — found live by the outward clearing run.
The DEFAULT partition is a safety net so a missed month can never reject a cheque; a scheduled partition
maintenance job should still create the next months before they are needed.

Revision ID: 20260921_026
Revises: 20260921_025
Create Date: 2026-09-21
"""
from alembic import op

revision = "20260921_026"
down_revision = "20260921_025"
branch_labels = None
depends_on = None


def _months(start_year: int, start_month: int, end_year: int, end_month: int):
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield y, m, ny, nm
        y, m = ny, nm


def upgrade() -> None:
    for y, m, ny, nm in _months(2026, 9, 2028, 12):
        op.execute(
            f"CREATE TABLE IF NOT EXISTS cts.cheque_instruments_{y}_{m:02d} "
            f"PARTITION OF cts.cheque_instruments "
            f"FOR VALUES FROM ('{y}-{m:02d}-01 00:00:00+00') TO ('{ny}-{nm:02d}-01 00:00:00+00')"
        )
    op.execute("CREATE TABLE IF NOT EXISTS cts.cheque_instruments_default PARTITION OF cts.cheque_instruments DEFAULT")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.cheque_instruments_default")
    for y, m, _, _ in _months(2026, 9, 2028, 12):
        op.execute(f"DROP TABLE IF EXISTS cts.cheque_instruments_{y}_{m:02d}")
