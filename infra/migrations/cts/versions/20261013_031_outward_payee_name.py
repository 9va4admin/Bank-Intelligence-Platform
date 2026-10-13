"""cts.outward_payee_name: payee (account holder) name per outward instrument, from CBS.

Plain text by decision of the bank owner (2026-10-13), same exemption as inward_drawee_name.

Revision ID: 20261013_031
Revises: 20261013_030
Create Date: 2026-10-13
"""
from alembic import op

revision = "20261013_031"
down_revision = "20261013_030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cts.outward_payee_name (
            bank_id       TEXT NOT NULL,
            instrument_id TEXT NOT NULL,
            payee_name    TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (bank_id, instrument_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.outward_payee_name")
