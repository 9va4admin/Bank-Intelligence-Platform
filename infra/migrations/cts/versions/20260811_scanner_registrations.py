"""Add cts.scanner_registrations — SDK_PUSH scanner lifecycle tracking.

Each branch configured for SDK_PUSH mode has one active registration row.
The SDK authenticates heartbeat calls with a registration_token; only its
SHA-256 hash is stored here — the plaintext is shown once at provisioning.

Status lifecycle:
  PENDING  → registered by admin, SDK not yet connected
  ONLINE   → heartbeat received within 2 × heartbeat_interval_seconds
  DEGRADED → heartbeat stale (2× < stale ≤ 5× interval) — PlatformHealthCheckWorkflow alerts
  OFFLINE  → stale > 5× interval OR explicitly deactivated by admin

Revision ID: 20260811_scanner_registrations
Revises:     20260811_branches_add_scanner_input_mode
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_scanner_registrations"
down_revision = "20260811_branches_add_scanner_input_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scanner_registrations",
        sa.Column("registration_id", sa.Text(), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("branch_id", sa.Text(), nullable=False),
        sa.Column("branch_ifsc", sa.Text(), nullable=False),
        sa.Column("scanner_config_id", sa.Text(), nullable=True,
                  comment="Optional link to cts.scanner_configs (OEM config for FOLDER_DROP)"),
        sa.Column("sdk_version", sa.Text(), nullable=True),
        sa.Column("registration_token_hash", sa.Text(), nullable=False,
                  comment="SHA-256 of the registration token; plaintext never stored"),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING",
                  comment="PENDING | ONLINE | DEGRADED | OFFLINE"),
        sa.Column("last_heartbeat_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_scan_submitted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("heartbeat_interval_seconds", sa.Integer(), nullable=False, server_default="60",
                  comment="Expected SDK heartbeat cadence; PlatformHealthCheck uses 5× as OFFLINE threshold"),
        sa.Column("scans_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("registered_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("registered_by", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("registration_id"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ONLINE', 'DEGRADED', 'OFFLINE')",
            name="ck_scanner_reg_status",
        ),
        schema="cts",
    )
    # One active registration per branch — prevents duplicate provisioning
    op.execute(
        """
        CREATE UNIQUE INDEX uq_scanner_registrations_active_branch
        ON cts.scanner_registrations (bank_id, branch_ifsc)
        WHERE is_active = true
        """
    )
    op.create_index(
        "ix_scanner_registrations_bank_id",
        "scanner_registrations",
        ["bank_id"],
        schema="cts",
    )
    op.create_index(
        "ix_scanner_registrations_branch_ifsc",
        "scanner_registrations",
        ["branch_ifsc"],
        schema="cts",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cts.uq_scanner_registrations_active_branch")
    op.drop_index("ix_scanner_registrations_branch_ifsc", table_name="scanner_registrations", schema="cts")
    op.drop_index("ix_scanner_registrations_bank_id", table_name="scanner_registrations", schema="cts")
    op.drop_table("scanner_registrations", schema="cts")
