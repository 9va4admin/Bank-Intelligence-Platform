"""Restore platform.user_sessions and platform.login_events — wrongly dropped.

20260916_drop_dead_schema incorrectly dropped two tables that serve critical
durable-storage roles and cannot be replaced by Redis or Immudb alone:

  platform.user_sessions
    Source of truth for active sessions and revocation. Redis is cache-aside
    (60s TTL). Without this table: forced-logout only clears Redis — the JWT
    remains valid until its own TTL. Revocation is completely broken.

  platform.login_events
    Append-only audit trail for every login lifecycle event (LOGIN_SUCCESS,
    LOGIN_FAILED, LOGOUT, FORCE_LOGOUT, TOTP_FAILED, etc.). Written by auth
    handlers; Immudb copy is authoritative but YugabyteDB copy is queryable
    from Admin UI. A migration test (test_006_bank_type_permission_level.py)
    also asserts this table exists.

Both tables have zero application queries in the catalog because their INSERT
path was in auth code that the query audit did not scan (it scanned only the
query catalog, not every Python write path). That was the audit's blind spot —
not evidence that the tables are unused.

Revision ID: 20260916_restore_sessions_login
Revises: 20260916_drop_dead_schema
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260916_restore_sessions_login"
down_revision = "20260916_drop_dead_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── platform.user_sessions ────────────────────────────────────────────
    # Durable session store. Redis is a 60s read-cache in front of this table.
    # On login  : INSERT here first, then SET Redis key.
    # On logout : UPDATE revoked_at here first, then DEL Redis key.
    # On validate: GET Redis → miss → SELECT here → repopulate Redis 60s.
    op.create_table(
        "user_sessions",
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "bank_id",
            sa.Text,
            sa.ForeignKey("platform.banks.bank_id"),
            nullable=False,
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text, nullable=True),
        # LOGOUT | ADMIN_REVOKE | PASSWORD_CHANGE | SESSION_TIMEOUT | BANK_DEACTIVATED
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip_hash", sa.Text, nullable=True),
        # SHA-256 of IP — never raw IP
        schema="platform",
    )

    op.create_index(
        "ix_platform_user_sessions_user_active",
        "user_sessions",
        ["user_id", "expires_at"],
        schema="platform",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_platform_user_sessions_bank",
        "user_sessions",
        ["bank_id"],
        schema="platform",
    )

    # ── platform.login_events ─────────────────────────────────────────────
    # Append-only audit trail. Written by auth handlers on every login lifecycle
    # event. Immudb copy is authoritative for tamper-evidence; this table is
    # queryable from the Admin UI. No UPDATE or DELETE ever issued.
    op.create_table(
        "login_events",
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "bank_id",
            sa.Text,
            sa.ForeignKey("platform.banks.bank_id"),
            nullable=False,
        ),
        sa.Column("bank_type", sa.Text, nullable=False),
        # SB | SMB — denormalised for fast tenant-scoped queries
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("platform.users.user_id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        # LOGIN_SUCCESS | LOGIN_FAILED | LOGOUT | SESSION_TIMEOUT |
        # FORCE_LOGOUT | TOTP_FAILED | TOTP_SUCCESS | PASSWORD_RESET_INITIATED
        sa.Column("ip_hash", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        # FK to user_sessions omitted — login_events is append-only and must
        # not be constrained by session lifecycle
        sa.Column("failure_reason", sa.Text, nullable=True),
        # INVALID_SAML_ASSERTION | TOTP_MISMATCH | USER_INACTIVE |
        # BANK_DEACTIVATED | SESSION_LIMIT_EXCEEDED — null on success
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("immudb_tx_id", sa.Text, nullable=True),
        sa.Column(
            "immudb_verified",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        schema="platform",
    )

    op.create_index(
        "ix_platform_login_events_bank_occurred",
        "login_events",
        ["bank_id", "occurred_at"],
        schema="platform",
    )
    op.create_index(
        "ix_platform_login_events_user",
        "login_events",
        ["user_id", "occurred_at"],
        schema="platform",
    )


def downgrade() -> None:
    op.drop_index("ix_platform_login_events_user", table_name="login_events", schema="platform")
    op.drop_index("ix_platform_login_events_bank_occurred", table_name="login_events", schema="platform")
    op.drop_table("login_events", schema="platform")

    op.drop_index("ix_platform_user_sessions_bank", table_name="user_sessions", schema="platform")
    op.drop_index("ix_platform_user_sessions_user_active", table_name="user_sessions", schema="platform")
    op.drop_table("user_sessions", schema="platform")
