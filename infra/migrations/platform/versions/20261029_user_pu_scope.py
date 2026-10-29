"""Reviewers are scoped to processing units, not clearing zones; users may be assigned to branches.

Adds platform.local_auth_accounts.pu_ids (empty = unrestricted, as clearing_zones was) and branch_ids (empty = central staff). The old clearing_zones column is
left in place, unused, until a later release.

Revision ID: 20261029_user_pu
Revises: 20260918_config_restore
Create Date: 2026-10-29
"""
from alembic import op

revision = "20261029_user_pu"
down_revision = "20260918_config_restore"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE platform.local_auth_accounts ADD COLUMN IF NOT EXISTS pu_ids TEXT[] NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE platform.local_auth_accounts ADD COLUMN IF NOT EXISTS branch_ids TEXT[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE platform.local_auth_accounts DROP COLUMN IF EXISTS branch_ids")
    op.execute("ALTER TABLE platform.local_auth_accounts DROP COLUMN IF EXISTS pu_ids")
