"""Platform schema — bank_type, permission_level on users + login_events table.

Changes:
  platform.users
    + bank_type       TEXT NOT NULL DEFAULT 'SB'
        SB  = Sponsor Bank (direct NGCH member running ASTRA)
        SMB = Sub-Member Bank (routes through sponsor)
        Existing rows backfilled to 'SB' — backwards compatible.
        Immutable after user creation (enforced at application layer).

    + permission_level TEXT NOT NULL DEFAULT 'EDIT'
        ADMIN     = full control within own tenant (incl. user management)
        EDIT      = read + modify/action (HR queue, config submits)
        READ_ONLY = view only
        Existing rows backfilled to 'EDIT' — backwards compatible.

  platform.login_events  (NEW — append-only; immutability via Immudb + application)
    Records every login lifecycle event for every user (SB and SMB).
    Written by saml_handler on auth success/failure; logged to Immudb for tamper-evidence.
    YugabyteDB copy is queryable from Admin UI; Immudb copy is the authoritative record.

    SB users can query ALL events (no bank_id filter).
    SMB users can query ONLY their own bank's events (bank_id = own).
    No UPDATE or DELETE ever issued by application code — Immudb enforces final immutability.

Revision ID: 20260627_p_006
Revises: 20260618_p_005
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260627_p_006"
down_revision = "20260618_p_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── platform.users: add bank_type ──────────────────────────────────────
    # Additive only — existing rows default to 'SB' (all pre-existing users are SB staff).
    op.add_column(
        "users",
        sa.Column(
            "bank_type",
            sa.Text,
            nullable=False,
            server_default="SB",
        ),
        schema="platform",
    )
    op.create_index(
        "ix_platform_users_bank_type",
        "users",
        ["bank_id", "bank_type"],
        schema="platform",
    )

    # ── platform.users: add permission_level ───────────────────────────────
    # Additive only — existing rows default to 'EDIT' (preserves current behaviour).
    op.add_column(
        "users",
        sa.Column(
            "permission_level",
            sa.Text,
            nullable=False,
            server_default="EDIT",
        ),
        schema="platform",
    )
    op.create_index(
        "ix_platform_users_permission_level",
        "users",
        ["bank_id", "permission_level"],
        schema="platform",
    )

    # ── platform.login_events ──────────────────────────────────────────────
    # Append-only login audit table. Application NEVER issues UPDATE or DELETE.
    # Immudb is the authoritative immutable store; this table is the queryable mirror.
    op.create_table(
        "login_events",
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("bank_type", sa.Text, nullable=False),
        # SB | SMB — denormalised for fast tenant-scoped queries without join

        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=False),

        sa.Column("event_type", sa.Text, nullable=False),
        # LOGIN_SUCCESS | LOGIN_FAILED | LOGOUT | SESSION_TIMEOUT |
        # FORCE_LOGOUT | TOTP_FAILED | TOTP_SUCCESS | PASSWORD_RESET_INITIATED

        sa.Column("ip_hash", sa.Text, nullable=True),
        # SHA-256(ip_address + daily_pepper) — never raw IP; PII rules apply

        sa.Column("user_agent", sa.Text, nullable=True),
        # Browser/client string; truncated to 512 chars at write time

        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        # FK to user_sessions omitted intentionally — login_events is append-only
        # and must not be constrained by session lifecycle

        sa.Column("failure_reason", sa.Text, nullable=True),
        # INVALID_SAML_ASSERTION | TOTP_MISMATCH | USER_INACTIVE |
        # BANK_DEACTIVATED | SESSION_LIMIT_EXCEEDED — null on success

        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),

        # Immudb tamper-evidence fields — written after successful Immudb append
        sa.Column("immudb_tx_id", sa.Text, nullable=True),
        # Immudb transaction ID — null until Immudb write confirmed
        sa.Column("immudb_verified", sa.Boolean, nullable=False, server_default="false"),
        # True once Merkle proof verified by audit-service

        schema="platform",
    )

    # Tenant-scoped query index — SMB scope adds WHERE bank_id = $1
    op.create_index(
        "ix_platform_login_events_bank_occurred",
        "login_events",
        ["bank_id", "occurred_at"],
        schema="platform",
    )
    # SB "see all" query index — by occurred_at descending
    op.create_index(
        "ix_platform_login_events_occurred",
        "login_events",
        ["occurred_at"],
        schema="platform",
    )
    # User-level query (admin viewing one user's login history)
    op.create_index(
        "ix_platform_login_events_user",
        "login_events",
        ["user_id", "occurred_at"],
        schema="platform",
    )
    # Unverified Immudb records (background job polls for these and re-verifies)
    op.create_index(
        "ix_platform_login_events_unverified",
        "login_events",
        ["immudb_verified"],
        postgresql_where=sa.text("immudb_verified = false"),
        schema="platform",
    )


def downgrade() -> None:
    # Drop login_events table and all its indexes
    op.drop_index("ix_platform_login_events_unverified",
                  table_name="login_events", schema="platform")
    op.drop_index("ix_platform_login_events_user",
                  table_name="login_events", schema="platform")
    op.drop_index("ix_platform_login_events_occurred",
                  table_name="login_events", schema="platform")
    op.drop_index("ix_platform_login_events_bank_occurred",
                  table_name="login_events", schema="platform")
    op.drop_table("login_events", schema="platform")

    # Remove permission_level column and index
    op.drop_index("ix_platform_users_permission_level",
                  table_name="users", schema="platform")
    op.drop_column("users", "permission_level", schema="platform")

    # Remove bank_type column and index
    op.drop_index("ix_platform_users_bank_type",
                  table_name="users", schema="platform")
    op.drop_column("users", "bank_type", schema="platform")
