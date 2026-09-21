"""Add permission_level and bank_type to platform.local_auth_accounts.

Migration 20260627_006 added these columns to platform.users (for SAML/LDAP
accounts). platform.local_auth_accounts was created later (20260705_local_auth)
but did not include them — schema mismatch caught by query audit.

The LocalAuthConnector (shared/auth/connectors/local.py) selects both columns
in its _COLS constant. Without this migration, any bank using local-auth login
gets a PostgreSQL column-not-found error at runtime.

Revision ID: 20260916_platform_local_auth
Revises: 20260719_p_secviol
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260916_platform_local_auth"
down_revision = "20260719_p_secviol"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # permission_level controls UI edit vs read-only access within the assigned role
    op.add_column(
        "local_auth_accounts",
        sa.Column(
            "permission_level",
            sa.Text(),
            nullable=False,
            server_default="READ_ONLY",
        ),
        schema="platform",
    )

    # bank_type distinguishes Sponsor Bank (SB) vs Sub-Member Bank (SMB) accounts
    op.add_column(
        "local_auth_accounts",
        sa.Column(
            "bank_type",
            sa.Text(),
            nullable=False,
            server_default="SB",
        ),
        schema="platform",
    )

    op.create_index(
        "ix_local_auth_accounts_bank_type",
        "local_auth_accounts",
        ["bank_id", "bank_type"],
        schema="platform",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_local_auth_accounts_bank_type",
        table_name="local_auth_accounts",
        schema="platform",
    )
    op.drop_column("local_auth_accounts", "bank_type", schema="platform")
    op.drop_column("local_auth_accounts", "permission_level", schema="platform")
