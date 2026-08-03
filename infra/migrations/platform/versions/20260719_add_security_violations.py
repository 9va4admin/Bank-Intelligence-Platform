"""Add platform.security_violations table.

Stores every security isolation violation caught by SecurityViolationMiddleware.
Written by _publish_violation_alert() — fire-and-forget, ON CONFLICT DO NOTHING
so retries never produce duplicates.

Revision ID: 20260719_p_secviol
Revises: 20260717_add_totp_enrolled
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = "20260719_p_secviol"
down_revision = "20260717_add_totp_enrolled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_violations",
        sa.Column("violation_id", sa.Text, primary_key=True),
        sa.Column("bank_id", sa.Text, nullable=False),
        sa.Column("sb_bank_id", sa.Text, nullable=False, server_default=""),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("bank_type", sa.Text, nullable=False),
        sa.Column("violation_type", sa.Text, nullable=False),
        sa.Column("suspended", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("client_ip", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("request_id", sa.Text, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index(
        "ix_platform_security_violations_bank",
        "security_violations", ["bank_id", "occurred_at"],
        schema="platform",
    )
    op.create_index(
        "ix_platform_security_violations_user",
        "security_violations", ["user_id", "occurred_at"],
        schema="platform",
    )
    op.create_index(
        "ix_platform_security_violations_suspended",
        "security_violations", ["suspended", "occurred_at"],
        postgresql_where=sa.text("suspended = true"),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_table("security_violations", schema="platform")
