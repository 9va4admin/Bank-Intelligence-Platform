"""
cts.scanner_tokens — machine-bound API tokens for scanner agents.

Each row represents one physical scanner PC registered to a specific branch.
The token_hash (SHA-256 of the raw token) is stored — raw token is never stored.
The raw token is returned once at registration and written to token.dat by the installer.

Revision: 20260901_scanner_tokens
"""
from alembic import op
import sqlalchemy as sa

revision = "20260901_scanner_tokens"
down_revision = "20260901_outward_scan_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "scanner_tokens",
        sa.Column("token_id",   sa.Text,    primary_key=True),
        sa.Column("bank_id",    sa.Text,    nullable=False),
        sa.Column("branch_id",  sa.Text,    nullable=False),
        sa.Column("machine_id", sa.Text,    nullable=False),  # Windows machine name / UUID
        sa.Column("token_hash", sa.Text,    nullable=False),  # SHA-256 hex of raw token
        sa.Column("issued_at",  sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen",  sa.TIMESTAMP(timezone=True), nullable=True),   # updated on each API call
        sa.Column("revoked",    sa.Boolean, nullable=False,  server_default="false"),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Text,    nullable=True),  # user_id of admin who revoked
        schema="cts",
    )

    # Auth check: look up token by hash — must be fast
    op.create_index(
        "ix_scanner_tokens_hash",
        "scanner_tokens",
        ["token_hash"],
        unique=True,
        schema="cts",
    )
    # Admin UI: list all scanners for a bank
    op.create_index(
        "ix_scanner_tokens_bank",
        "scanner_tokens",
        ["bank_id", "branch_id"],
        schema="cts",
    )
    # Uniqueness: one active token per (branch_id, machine_id)
    # Partial unique index — allows re-registration on same machine (revokes old token)
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
