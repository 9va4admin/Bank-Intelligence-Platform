"""
Add account_status and holder_name_display columns to cts.account_vault.

account_status: ACTIVE | FROZEN | CLOSED | DORMANT | NPA — synced from CBS
holder_name_display: "R***" — first initial only; for UI and audit trail, NOT for name matching

Both columns are additive-only (no existing column changed).
Safe for rolling deploy: old pods read account_status as NULL → default "ACTIVE" in Python.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_account_vault_add_status_and_name"
down_revision = "20260803_add_outward_scan_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_vault",
        sa.Column("account_status", sa.Text(), nullable=False,
                  server_default="ACTIVE"),
        schema="cts",
    )
    op.add_column(
        "account_vault",
        sa.Column("holder_name_display", sa.Text(), nullable=False,
                  server_default="***"),
        schema="cts",
    )


def downgrade() -> None:
    op.drop_column("account_vault", "holder_name_display", schema="cts")
    op.drop_column("account_vault", "account_status", schema="cts")
