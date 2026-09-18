"""Restore platform.user_preferences; add platform.config_values + config_pending_changes.

Real bug found 2026-09-18 while running the first real, DB-backed inward-pipeline
test: config_service.py's Layer 3 reader queried a table
("config.bank_config") that never existed in any migration. The 2026-09-16
schema audit (20260916_drop_dead_schema) took the absence of any real query
against platform.config_entries as proof it was dead code and dropped it --
but the real, live Layer 3 read/write path was never config_entries at all.
It is platform.config_values + platform.config_pending_changes, both of which
apps/api/routers/admin.py already reads and writes today, created only via
raw DDL in apps/api/dev_auth_server.py (a dev-only bootstrap script) -- never
through Alembic, violating this repo's own rule (infra/migrations only).
This migration is the real Alembic source of truth for those two tables,
matching dev_auth_server.py's existing column set exactly.

platform.user_preferences (Layer 5 per-user UI preferences) was also dropped
by the same audit with a similarly wrong premise ("Layer 5 preferences live
in config.user_preferences (different schema)") -- no such schema/table
exists anywhere in this repo. config_service.get_user_preference() is real,
live code with no other backing table; restored here unchanged from its
original definition in 20260618_001_platform_banks_and_users.py.

Revision ID: 20260918_config_restore
Revises: 0d9208784d64
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260918_config_restore"
down_revision = "0d9208784d64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── platform.user_preferences (Layer 5, restored) ─────────────────────────
    op.create_table(
        "user_preferences",
        sa.Column("pref_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=False),
        sa.Column("pref_key", sa.Text, nullable=False),
        sa.Column("pref_value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_user_preferences_user",
                    "user_preferences", ["user_id", "pref_key"], unique=True,
                    schema="platform")

    # ── platform.config_values (Layer 3, real live table per admin.py) ───────
    op.create_table(
        "config_values",
        sa.Column("config_id", sa.Text, primary_key=True,
                  server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("bank_id", sa.Text, nullable=False),
        sa.Column("module", sa.Text, nullable=False, server_default="cts"),
        sa.Column("config_key", sa.Text, nullable=False),
        sa.Column("config_value", sa.Text, nullable=False),
        sa.Column("value_type", sa.Text, nullable=False, server_default="float"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_by", sa.Text, nullable=False, server_default="system"),
        schema="platform",
    )
    op.create_index("uq_config_values_key", "config_values",
                    ["bank_id", "module", "config_key"], unique=True,
                    schema="platform")

    # ── platform.config_pending_changes (Layer 3 maker-checker, real live table) ─
    op.create_table(
        "config_pending_changes",
        sa.Column("change_id", sa.Text, primary_key=True),
        sa.Column("bank_id", sa.Text, nullable=False),
        sa.Column("config_key", sa.Text, nullable=False),
        sa.Column("new_value", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="PENDING_APPROVAL"),
        sa.Column("submitted_by", sa.Text, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("actioned_by", sa.Text, nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
        schema="platform",
    )
    op.create_index("ix_config_pending_bank", "config_pending_changes",
                    ["bank_id", "status"], schema="platform")


def downgrade() -> None:
    op.drop_table("config_pending_changes", schema="platform")
    op.drop_table("config_values", schema="platform")
    op.drop_table("user_preferences", schema="platform")
