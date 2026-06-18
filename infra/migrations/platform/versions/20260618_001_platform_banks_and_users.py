"""Platform schema — banks registry and user identity.

Tables:
  platform.banks            — canonical bank registry (replaces cts.banks_master)
  platform.bank_module_config — which modules are active per bank (Layer 2 mirror)
  platform.users            — all bank staff across all modules
  platform.user_roles       — role assignments (user × role × module × zone)
  platform.user_sessions    — JWT session tracking and revocation
  platform.user_preferences — Layer 5 per-user UI preferences

This is the FIRST migration that runs for any bank, any module configuration.
CTS and EJ migrations both depend on platform.banks existing before they run.

Revision ID: 20260618_p_001
Revises: (base — platform chain)
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_p_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create platform schema and shared extensions ────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS platform")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── platform.banks ─────────────────────────────────────────────────────
    # Canonical bank registry. This is the single source of truth for bank_id.
    # Every FK to bank_id in CTS and EJ schemas points here.
    # Moved from cts.banks_master — now module-agnostic.
    op.create_table(
        "banks",
        sa.Column("bank_id", sa.Text, primary_key=True),
        # e.g. "kotak-mah", "hdfc-bank", "sbi" — slug format, immutable after creation

        sa.Column("bank_name", sa.Text, nullable=False),
        sa.Column("bank_code", sa.Text, nullable=False, unique=True),   # NPCI bank code
        sa.Column("ifsc_prefix", sa.Text, nullable=False),              # first 4 chars of IFSC
        sa.Column("ngch_member_code", sa.Text, nullable=True),          # NGCH clearing member code

        # Bank type (governs which NPCI rules apply)
        sa.Column("bank_type", sa.Text, nullable=False, server_default="'PRIVATE'"),
        # PRIVATE | PUBLIC | RRB | UCB | COOPERATIVE | PAYMENTS | SMALL_FINANCE

        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),

        schema="platform",
    )
    op.create_index("ix_platform_banks_bank_code",
                    "banks", ["bank_code"], unique=True, schema="platform")
    op.create_index("ix_platform_banks_active",
                    "banks", ["is_active"],
                    postgresql_where=sa.text("is_active = true"), schema="platform")

    # ── platform.bank_module_config ────────────────────────────────────────
    # Layer 2 mirror: which modules are deployed for each bank.
    # Populated by BankOnboardingWorkflow from Helm values.
    # Read by config_service and admin UI — not by application hot path.
    op.create_table(
        "bank_module_config",
        sa.Column("config_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("module", sa.Text, nullable=False),
        # CTS | EJ

        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("gpu_profile", sa.Text, nullable=True),
        # PILOT (4×RTX4090) | PRODUCTION (4×A100)
        sa.Column("max_agent_swarm_size", sa.Integer, nullable=True),
        sa.Column("cbs_connector_type", sa.Text, nullable=True),
        # FINACLE | BANCS | FLEXCUBE (CTS-relevant; null for EJ)
        sa.Column("clearing_zones", JSONB, nullable=True),
        # ["MUMBAI", "DELHI"] — CTS only

        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_bank_module_config_bank",
                    "bank_module_config", ["bank_id", "module"], unique=True,
                    schema="platform")
    op.create_index("ix_platform_bank_module_config_enabled",
                    "bank_module_config", ["module", "is_enabled"],
                    postgresql_where=sa.text("is_enabled = true"), schema="platform")

    # ── platform.users ─────────────────────────────────────────────────────
    # All bank staff across all modules. ASTRA never stores passwords —
    # identity comes from bank's IdP via SAML 2.0. This table is the
    # post-authentication profile: roles, zones, active status.
    op.create_table(
        "users",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        # SAML identity (bank's IdP is authoritative — no password stored here)
        sa.Column("saml_subject", sa.Text, nullable=False),
        # SAML NameID — unique per bank IdP
        sa.Column("saml_idp_entity_id", sa.Text, nullable=True),

        # Display info (from SAML attributes — refreshed on each login)
        sa.Column("display_name_enc", sa.LargeBinary, nullable=True),
        # pgp_sym_encrypt — name is PII; encrypted at rest
        sa.Column("email_enc", sa.LargeBinary, nullable=True),
        # pgp_sym_encrypt — email is PII; encrypted at rest

        # Primary role (RBAC — see user_roles for full multi-role support)
        sa.Column("primary_role", sa.Text, nullable=False),
        # ops_reviewer | fraud_analyst | ops_manager | bank_it_admin |
        # compliance_officer | rbi_examiner | ml_engineer

        # Zone scope (ops_reviewer is further scoped to clearing zones)
        sa.Column("zone_scope", JSONB, nullable=True),
        # ["MUMBAI", "DELHI"] — null means no zone restriction (all zones)

        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    # SAML subject must be unique per bank (same person can't have two accounts)
    op.create_index("ix_platform_users_bank_saml",
                    "users", ["bank_id", "saml_subject"], unique=True, schema="platform")
    op.create_index("ix_platform_users_bank_active",
                    "users", ["bank_id", "is_active"],
                    postgresql_where=sa.text("is_active = true"), schema="platform")
    op.create_index("ix_platform_users_role",
                    "users", ["bank_id", "primary_role"], schema="platform")

    # ── platform.user_roles ────────────────────────────────────────────────
    # A user can have multiple roles across modules.
    # e.g. ops_manager for CTS + compliance_officer for EJ at same bank.
    # RBAC enforcement reads this table at request time (cached in Redis, 15-min TTL).
    op.create_table(
        "user_roles",
        sa.Column("role_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=False),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("module", sa.Text, nullable=False),
        # CTS | EJ | PLATFORM (platform roles: bank_it_admin, compliance_officer, rbi_examiner)

        sa.Column("role", sa.Text, nullable=False),
        sa.Column("zone_scope", JSONB, nullable=True),
        # Role-level zone restriction (overrides user-level if more restrictive)

        sa.Column("granted_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # For time-scoped roles (rbi_examiner access per audit engagement)
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),

        schema="platform",
    )
    op.create_index("ix_platform_user_roles_user",
                    "user_roles", ["user_id", "module"],
                    postgresql_where=sa.text("is_active = true"), schema="platform")
    op.create_index("ix_platform_user_roles_bank_role",
                    "user_roles", ["bank_id", "role"],
                    postgresql_where=sa.text("is_active = true"), schema="platform")

    # ── platform.user_sessions ─────────────────────────────────────────────
    # JWT session tracking. Every login creates a row; logout/revocation updates it.
    # Middleware validates session_id from JWT against this table (via Redis cache).
    op.create_table(
        "user_sessions",
        sa.Column("session_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=False),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text, nullable=True),
        # LOGOUT | ADMIN_REVOKE | PASSWORD_CHANGE | SESSION_TIMEOUT | BANK_DEACTIVATED

        sa.Column("user_agent", sa.Text, nullable=True),   # browser/client info
        sa.Column("ip_hash", sa.Text, nullable=True),      # SHA-256 of IP — never raw IP

        schema="platform",
    )
    op.create_index("ix_platform_user_sessions_user_active",
                    "user_sessions", ["user_id", "expires_at"],
                    postgresql_where=sa.text("revoked_at IS NULL"), schema="platform")
    op.create_index("ix_platform_user_sessions_bank",
                    "user_sessions", ["bank_id"], schema="platform")

    # ── platform.user_preferences ──────────────────────────────────────────
    # Layer 5 — per-user UI preferences. No approval required, no audit trail.
    # Stored as key-value; each key is namespaced by module.
    op.create_table(
        "user_preferences",
        sa.Column("pref_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=False),
        sa.Column("pref_key", sa.Text, nullable=False),
        # e.g. "cts.dashboard_layout", "ej.fleet_map_zoom", "platform.locale"
        sa.Column("pref_value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_user_preferences_user",
                    "user_preferences", ["user_id", "pref_key"], unique=True,
                    schema="platform")

    # ── platform.bank_onboarding_events ───────────────────────────────────
    # Step-by-step audit trail of BankOnboardingWorkflow execution.
    op.create_table(
        "bank_onboarding_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("module", sa.Text, nullable=True),
        # NULL = platform-level step; "CTS" or "EJ" for module-specific steps

        sa.Column("event_type", sa.Text, nullable=False),
        # BANK_REGISTERED | NAMESPACE_PROVISIONED | DB_SCHEMA_MIGRATED |
        # VAULT_SEEDED | REDIS_WARMED | CBS_CONNECTION_VERIFIED |
        # NGCH_CONNECTION_VERIFIED | SMOKE_TEST_PASSED | MODULE_ACTIVATED

        sa.Column("workflow_id", sa.Text, nullable=True),   # BankOnboardingWorkflow ID
        sa.Column("status", sa.Text, nullable=False),
        # SUCCESS | FAILED | SKIPPED
        sa.Column("detail", JSONB, nullable=True),

        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_onboarding_events_bank",
                    "bank_onboarding_events", ["bank_id", "occurred_at"], schema="platform")


def downgrade() -> None:
    op.drop_table("bank_onboarding_events", schema="platform")
    op.drop_table("user_preferences", schema="platform")
    op.drop_table("user_sessions", schema="platform")
    op.drop_table("user_roles", schema="platform")
    op.drop_table("users", schema="platform")
    op.drop_table("bank_module_config", schema="platform")
    op.drop_table("banks", schema="platform")
    op.execute("DROP SCHEMA IF EXISTS platform CASCADE")
