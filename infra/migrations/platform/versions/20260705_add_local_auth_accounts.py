"""Add platform.local_auth_accounts — for entities with no SAML/LDAP directory.

Regression: this file previously lived directly in infra/migrations/platform/
(not platform/versions/, which is what alembic.ini's version_locations
actually points at) with down_revision=None. Both mistakes made it an orphan
that `alembic upgrade head` silently never picked up — confirmed via
`alembic history` against the real chain, which stopped at 20260627_p_006
with no trace of this revision at all. Moved into versions/ and chained onto
the real head below.

Revision ID: 20260705_local_auth
Revises: 20260627_p_006
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

revision = "20260705_local_auth"
down_revision = "20260627_p_006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")

    op.create_table(
        "local_auth_accounts",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),   # sb | smb | branch | pu
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),  # argon2id hash
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("clearing_zones", ARRAY(TEXT), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.Float(), nullable=True),   # Unix timestamp; NULL = not locked
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )

    # Unique username per bank
    op.create_unique_constraint(
        "uq_local_auth_accounts_bank_username",
        "local_auth_accounts",
        ["bank_id", "username"],
        schema="platform",
    )

    # Fast lookup by bank + username
    op.create_index(
        "ix_local_auth_accounts_bank_username",
        "local_auth_accounts",
        ["bank_id", "username"],
        schema="platform",
    )

    # Fast lookup by entity
    op.create_index(
        "ix_local_auth_accounts_entity",
        "local_auth_accounts",
        ["bank_id", "entity_type", "entity_id"],
        schema="platform",
    )


def downgrade() -> None:
    op.drop_index("ix_local_auth_accounts_entity", table_name="local_auth_accounts", schema="platform")
    op.drop_index("ix_local_auth_accounts_bank_username", table_name="local_auth_accounts", schema="platform")
    op.drop_table("local_auth_accounts", schema="platform")
