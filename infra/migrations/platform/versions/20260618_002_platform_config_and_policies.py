"""Platform config store and OPA policy version history.

Tables:
  platform.config_entries     — Layer 3 business rules (hot-reloadable, maker-checker)
  platform.config_change_log  — every Layer 3 change with full maker-checker audit trail
  platform.opa_policy_versions — Layer 4 Rego policies with diff history

Both CTS and EJ modules read config from here via config_service.
Key namespace convention:
  cts.*   → CTS-specific thresholds (iet_minutes, stp_auto_confirm_threshold, ...)
  ej.*    → EJ-specific thresholds (field_extraction.min_confidence, ...)
  platform.* → shared settings (session_timeout_minutes, notification_retry_count, ...)

Revision ID: 20260618_p_002
Revises: 20260618_p_001
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_p_002"
down_revision = "20260618_p_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── platform.config_entries ────────────────────────────────────────────
    # Layer 3 business rules and operational thresholds.
    # config_service reads this table, caches in Redis (30-second TTL),
    # and invalidates on Kafka platform.config.changed event.
    # Changes require maker (ops_manager) + checker (bank_it_admin) approval.
    op.create_table(
        "config_entries",
        sa.Column("config_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("module", sa.Text, nullable=False),
        # CTS | EJ | PLATFORM

        sa.Column("config_key", sa.Text, nullable=False),
        # e.g. "iet_minutes", "stp_auto_confirm_threshold", "ej.field_extraction.min_confidence"
        sa.Column("config_value", sa.Text, nullable=False),
        # Always stored as text — config_service coerces to correct type on read
        sa.Column("value_type", sa.Text, nullable=False),
        # INT | FLOAT | BOOL | TEXT | JSON
        # Used by config_service to cast correctly (never return wrong type)

        sa.Column("description", sa.Text, nullable=True),
        # Human-readable description for Admin UI

        # Approval state
        sa.Column("status", sa.Text, nullable=False, server_default="'ACTIVE'"),
        # PENDING_APPROVAL | ACTIVE | SUPERSEDED | REVERTED
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    # Only one ACTIVE entry per key per bank per module
    op.create_index("ix_platform_config_entries_lookup",
                    "config_entries", ["bank_id", "module", "config_key"],
                    postgresql_where=sa.text("status = 'ACTIVE'"),
                    unique=True, schema="platform")
    op.create_index("ix_platform_config_entries_bank_module",
                    "config_entries", ["bank_id", "module"], schema="platform")

    # ── platform.config_change_log ─────────────────────────────────────────
    # Append-only audit trail for every Layer 3 config change.
    # Written BEFORE the change takes effect (Immudb gets tamper-proof copy).
    # Enables compliance_officer to run SQL audit reports on config history.
    op.create_table(
        "config_change_log",
        sa.Column("change_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("module", sa.Text, nullable=False),
        sa.Column("config_key", sa.Text, nullable=False),

        sa.Column("old_value", sa.Text, nullable=True),     # NULL on first set
        sa.Column("new_value", sa.Text, nullable=False),
        sa.Column("change_reason", sa.Text, nullable=True),

        # Maker-checker (both required before change is applied)
        sa.Column("submitted_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("approved_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),

        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | APPROVED | APPLIED | REJECTED | REVERTED

        # Immudb reference (tamper-evident proof this change was recorded)
        sa.Column("immudb_tx_id", sa.BigInteger, nullable=True),

        schema="platform",
    )
    op.create_index("ix_platform_config_change_log_bank_key",
                    "config_change_log", ["bank_id", "config_key", "submitted_at"],
                    schema="platform")
    op.create_index("ix_platform_config_change_log_pending",
                    "config_change_log", ["bank_id", "status"],
                    postgresql_where=sa.text("status = 'PENDING'"), schema="platform")

    # ── platform.opa_policy_versions ──────────────────────────────────────
    # Layer 4 Rego policy version history.
    # OPA config watcher polls this table for new versions (polls every 30s).
    # On new ACTIVE version: OPA hot-reloads the bundle — no pod restart needed.
    # Full Rego diff stored for compliance audit (who changed what policy and when).
    op.create_table(
        "opa_policy_versions",
        sa.Column("policy_version_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        sa.Column("policy_name", sa.Text, nullable=False),
        # cts_routing | cts_auto_return | ej_dispute | diagnostic_access
        # Matches filename in infra/opa/policies/

        sa.Column("version_number", sa.Integer, nullable=False),
        # Auto-incremented per policy_name per bank

        sa.Column("rego_content", sa.Text, nullable=False),
        # Full Rego policy text — compliance requires full history retention
        sa.Column("rego_diff", sa.Text, nullable=True),
        # Unified diff vs previous version (NULL for first version)

        sa.Column("version_hash", sa.Text, nullable=False),
        # SHA-256 of rego_content — OPA watcher compares hash to detect changes

        # Approval state (compliance_officer authors, bank_it_admin approves)
        sa.Column("authored_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=False),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("approved_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("status", sa.Text, nullable=False, server_default="'DRAFT'"),
        # DRAFT | PENDING_APPROVAL | ACTIVE | SUPERSEDED | REVERTED
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),

        # Immudb reference
        sa.Column("immudb_tx_id", sa.BigInteger, nullable=True),

        schema="platform",
    )
    op.create_index("ix_platform_opa_policy_versions_active",
                    "opa_policy_versions", ["bank_id", "policy_name"],
                    postgresql_where=sa.text("status = 'ACTIVE'"),
                    unique=True, schema="platform")
    op.create_index("ix_platform_opa_policy_versions_bank_policy",
                    "opa_policy_versions", ["bank_id", "policy_name", "version_number"],
                    schema="platform")
    # OPA watcher polls this — partial index for efficiency
    op.create_index("ix_platform_opa_policy_versions_pending",
                    "opa_policy_versions", ["bank_id", "approved_at"],
                    postgresql_where=sa.text("status = 'PENDING_APPROVAL'"),
                    schema="platform")


def downgrade() -> None:
    op.drop_table("opa_policy_versions", schema="platform")
    op.drop_table("config_change_log", schema="platform")
    op.drop_table("config_entries", schema="platform")
