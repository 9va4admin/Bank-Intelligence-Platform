"""Platform audit trail — cross-module events and Immudb verification log.

Tables:
  platform.audit_events            — platform-level events (login, config, onboarding)
  platform.immudb_verification_log — periodic Merkle root verification proofs

Design principle:
  - Module-domain events (cheque filed, EJ parsed) stay in their own schema:
    cts.cts_audit_events, and an ej equivalent.
  - Platform events that are NOT owned by a single module live here:
    user login, config change approval, policy activation, bank onboarding,
    diagnostic session access, RBAC grant/revoke.
  - Immudb is the tamper-evident primary store for ALL events (both platform
    and module-level). These YugabyteDB tables are secondary copies for SQL
    querying by compliance_officer without accessing Immudb directly.

Revision ID: 20260618_p_004
Revises: 20260618_p_003
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_p_004"
down_revision = "20260618_p_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── platform.audit_events ──────────────────────────────────────────────
    # Platform-level events shared across modules.
    # Every row has a corresponding Immudb entry (verified by immudb_tx_id).
    op.create_table(
        "audit_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        # Event classification
        sa.Column("module", sa.Text, nullable=False),
        # CTS | EJ | PLATFORM
        sa.Column("event_type", sa.Text, nullable=False),
        # PLATFORM: USER_LOGIN | USER_LOGOUT | USER_LOGIN_FAILED |
        #           SESSION_REVOKED | ROLE_GRANTED | ROLE_REVOKED |
        #           CONFIG_CHANGE_SUBMITTED | CONFIG_CHANGE_APPROVED | CONFIG_CHANGE_APPLIED |
        #           POLICY_AUTHORED | POLICY_APPROVED | POLICY_ACTIVATED |
        #           DIAGNOSTIC_SESSION_OPENED | DIAGNOSTIC_TOOL_CALLED |
        #           BANK_ONBOARDING_STEP | MODULE_ACTIVATED | MODULE_DEACTIVATED
        # CTS/EJ: cross-links to module audit tables via subject_id

        sa.Column("severity", sa.Text, nullable=False, server_default="'INFO'"),
        # INFO | WARN | CRITICAL

        # Actor
        sa.Column("actor_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        # NULL for system-initiated events (VaultSyncWorkflow, scheduled jobs)
        sa.Column("actor_service", sa.Text, nullable=True),
        # Service name for system events: "vault-sync-service", "config-service"

        # Subject (what the event is about)
        sa.Column("subject_type", sa.Text, nullable=True),
        # USER | BANK | CONFIG_KEY | POLICY | SESSION | MODULE | DIAGNOSTIC_SESSION
        sa.Column("subject_id", sa.Text, nullable=True),
        # The relevant ID (user_id, config_key, policy_name, etc.) as TEXT

        # Event payload (non-PII)
        sa.Column("event_data", JSONB, nullable=False, server_default="'{}'"),
        # Example for USER_LOGIN: {"ip_hash": "abc123", "user_agent": "Chrome/..."}
        # Example for CONFIG_CHANGE_APPLIED: {"key": "iet_minutes", "old": "180", "new": "165"}
        # NEVER include: account numbers, names, amounts, JWT tokens, Vault tokens

        # Immudb cross-reference
        sa.Column("immudb_tx_id", sa.BigInteger, nullable=True),
        sa.Column("immudb_verified", sa.Boolean, nullable=False, server_default="false"),

        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_audit_events_bank_occurred",
                    "audit_events", ["bank_id", "occurred_at"], schema="platform")
    op.create_index("ix_platform_audit_events_actor",
                    "audit_events", ["actor_user_id", "occurred_at"],
                    postgresql_where=sa.text("actor_user_id IS NOT NULL"),
                    schema="platform")
    op.create_index("ix_platform_audit_events_type",
                    "audit_events", ["bank_id", "event_type", "occurred_at"],
                    schema="platform")
    op.create_index("ix_platform_audit_events_critical",
                    "audit_events", ["bank_id", "occurred_at"],
                    postgresql_where=sa.text("severity = 'CRITICAL'"),
                    schema="platform")

    # ── platform.immudb_verification_log ───────────────────────────────────
    # Periodic Merkle root verification proofs.
    # AuditWriteWorkflow verifies the Immudb chain every 6 hours.
    # A FAIL status triggers an immediate CRITICAL alert to bank_it_admin.
    # This table itself is not in Immudb (that would be circular) — it is
    # a YugabyteDB record of what was verified and when.
    op.create_table(
        "immudb_verification_log",
        sa.Column("verification_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        sa.Column("collection", sa.Text, nullable=False),
        # "platform" | "cts" | "ej" — which Immudb collection was verified

        # What was verified
        sa.Column("verified_up_to_tx_id", sa.BigInteger, nullable=False),
        sa.Column("merkle_root_hash", sa.Text, nullable=False),
        sa.Column("block_height", sa.BigInteger, nullable=False),

        sa.Column("verification_status", sa.Text, nullable=False),
        # PASS | FAIL | PARTIAL (some entries could not be verified)
        sa.Column("fail_detail", sa.Text, nullable=True),
        # Only populated on FAIL — describes what hash didn't match

        sa.Column("verified_by_service", sa.Text, nullable=False),
        # "audit-service" — service name that ran the verification

        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_immudb_verification_bank_collection",
                    "immudb_verification_log",
                    ["bank_id", "collection", "verified_at"],
                    schema="platform")
    op.create_index("ix_platform_immudb_verification_failures",
                    "immudb_verification_log", ["bank_id", "verified_at"],
                    postgresql_where=sa.text("verification_status = 'FAIL'"),
                    schema="platform")


def downgrade() -> None:
    op.drop_table("immudb_verification_log", schema="platform")
    op.drop_table("audit_events", schema="platform")
