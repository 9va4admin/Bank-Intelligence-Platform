"""Add totp_enrolled to platform.local_auth_accounts.

The AccountEnrollmentStore protocol (shared/auth/auth_service.py) requires
is_totp_enrolled() and set_totp_enrolled() backed by this column.

All existing rows default to false — every local-auth user must complete
MFA enrollment on their first login after this migration runs.

Additive, NOT NULL DEFAULT FALSE — matches CLAUDE.md migration strategy.

Revision ID: 20260717_totp_enrolled
Revises: 20260716_local_auth_contact
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "20260717_totp_enrolled"
down_revision = "20260716_local_auth_contact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "local_auth_accounts",
        sa.Column(
            "totp_enrolled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("local_auth_accounts", "totp_enrolled", schema="platform")
