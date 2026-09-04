"""Add cts.scanner_tokens — machine-bound API tokens for scanner agents.

Each row represents one physical scanner PC registered to a specific branch.
token_hash (SHA-256 of the raw token) is stored — raw token is never persisted.
The raw token is returned once at registration and written to token.dat by the agent.

Revision ID: 20260904_019
Revises: 20260902_018
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa

revision = "20260904_019"
down_revision = "20260902_018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scanner_tokens",
        sa.Column("token_id",          sa.Text, primary_key=True),
        sa.Column("bank_id",           sa.Text, nullable=False),
        sa.Column("branch_id",         sa.Text, nullable=False),
        sa.Column("machine_id",        sa.Text, nullable=False),
        sa.Column("token_hash",        sa.Text, nullable=False),
        sa.Column("issued_at",         sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("expires_at",        sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen",         sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("active_session_id", sa.Text, nullable=True),
        sa.Column("revoked",           sa.Boolean, nullable=False, server_default="false"),
        sa.Column("revoked_at",        sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_by",        sa.Text, nullable=True),
        schema="cts",
    )

    op.create_index(
        "ix_scanner_tokens_hash",
        "scanner_tokens", ["token_hash"],
        unique=True, schema="cts",
    )
    op.create_index(
        "ix_scanner_tokens_bank",
        "scanner_tokens", ["bank_id", "branch_id"],
        schema="cts",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_scanner_tokens_active_machine
        ON cts.scanner_tokens (bank_id, branch_id, machine_id)
        WHERE revoked = false
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cts.uq_scanner_tokens_active_machine")
    op.drop_index("ix_scanner_tokens_bank", table_name="scanner_tokens", schema="cts")
    op.drop_index("ix_scanner_tokens_hash", table_name="scanner_tokens", schema="cts")
    op.drop_table("scanner_tokens", schema="cts")
