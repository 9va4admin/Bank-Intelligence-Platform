"""Add cts.revoked_sessions table for Redis-restart-safe JTI blocklist.

When Redis restarts all revoked:session:* keys are lost, briefly allowing
replay of logged-out tokens. This table is the persistent fallback —
written on every logout alongside Redis, checked by the auth middleware
only when Redis is unavailable.

Auto-expires via a YugabyteDB row with revoked_at + TTL matching the JWT
expiry. A background cleanup query removes rows older than 24h.

Revision ID: 20260902_018
Revises: 20260815_017
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260902_018"
down_revision = "20260815_017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_sessions",
        sa.Column("session_id", sa.Text, primary_key=True),
        sa.Column("bank_id",    sa.Text, nullable=False),
        sa.Column("user_id",    sa.Text, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="cts",
    )
    op.create_index(
        "ix_revoked_sessions_expires_at",
        "revoked_sessions",
        ["expires_at"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_revoked_sessions_expires_at", table_name="revoked_sessions", schema="cts")
    op.drop_table("revoked_sessions", schema="cts")
