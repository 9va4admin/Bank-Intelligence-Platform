"""platform.user_directory: every user who has signed in, with their role, whatever the identity source.

Users who sign in through the bank's identity provider (SAML, LDAP) have no row in platform.local_auth_accounts, and platform.users has no role, so
role-based lookups (who is on the alert bell) could not find them. The authentication service records each successful sign-in here. last_seen lets a
lookup ignore people who have not signed in for a long time. Additive only.

Revision ID: 20261117_user_directory
Revises: 20261117_alert_outbox_cols
Create Date: 2026-11-17
"""
from alembic import op

revision = "20261117_user_directory"
down_revision = "20261117_alert_outbox_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.user_directory (
            bank_id    TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            role       TEXT NOT NULL,
            is_active  BOOLEAN NOT NULL DEFAULT TRUE,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (bank_id, user_id)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_directory_role ON platform.user_directory (bank_id, role, last_seen DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.user_directory")
