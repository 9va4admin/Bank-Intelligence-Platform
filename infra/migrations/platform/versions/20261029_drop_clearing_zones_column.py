"""Drop platform.local_auth_accounts.clearing_zones: reviewers are scoped by pu_ids (added in 20261029_user_pu).

Revision ID: 20261029_drop_clearing_zones
Revises: 20261029_user_pu
Create Date: 2026-10-29
"""
from alembic import op

revision = "20261029_drop_clearing_zones"
down_revision = "20261029_user_pu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE platform.local_auth_accounts DROP COLUMN IF EXISTS clearing_zones")


def downgrade() -> None:
    op.execute("ALTER TABLE platform.local_auth_accounts ADD COLUMN IF NOT EXISTS clearing_zones TEXT[] NOT NULL DEFAULT '{}'")
