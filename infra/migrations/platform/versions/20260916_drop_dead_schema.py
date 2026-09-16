"""Drop dead platform schema objects: 11 tables + 14 columns with zero codebase references.

Schema audit (2026-09-16). Classification:
  DROP         = zero refs anywhere in modules/, apps/, shared/, tests/, docs/, CLAUDE.md
  KEEP-PLANNED = mentioned in CLAUDE.md architecture as planned feature (see below)

━━━━ TABLES DROPPED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  platform.bank_module_config       — per-bank module toggles superseded by
                                      config_service Layer 3 (config_values table).
  platform.bank_onboarding_events   — onboarding workflow runs in Temporal;
                                      events are in Immudb, not this table.
  platform.config_change_log        — replaced by platform.config_pending_changes
                                      (maker-checker audit trail).
  platform.config_entries           — replaced by platform.config_values;
                                      config_service never queries this table.
  platform.immudb_verification_log  — Immudb has its own cryptographic log;
                                      this double-log was never written to.
  platform.login_events             — login events go to Immudb via AuditEvent;
                                      this YugabyteDB table was never populated.
  platform.model_drift_alerts       — drift detection runs in PlatformHealthCheck
                                      Temporal workflow and writes to cts.audit_events;
                                      this separate table was never used.
  platform.notification_templates   — template bodies are in shared/messages/
                                      locales/messages.yaml (the ASTRA message
                                      registry). This DB table was never read.
                                      NOTE: FK from notification_records.template_id
                                      is dropped first (column becomes nullable orphan).
  platform.user_preferences         — Layer 5 user preferences live in
                                      config.user_preferences (different schema);
                                      this platform. table is never queried.
  platform.user_roles               — RBAC roles stored on local_auth_accounts.role
                                      and SAML claim; this separate table was never
                                      written to or read.
  platform.user_sessions            — sessions live in Redis Cluster; this
                                      YugabyteDB table was never populated
                                      (confirmed by comment in routers/users.py:769).

━━━━ COLUMNS DROPPED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  platform.audit_events:
    actor_service  — actor identity carried in bank_id + event_type envelope.
    actor_user_id  — user context carried in JWT / SAML claim at write time;
                     not needed for post-hoc query. Index dropped with column.
    module         — event_type prefix (CTS_, VAULT_, etc.) encodes the module.
    subject_id     — cross-reference dropped; Immudb hash is the durable link.
    subject_type   — same rationale as subject_id.

  platform.model_versions:
    baseline_metrics  — MLflow experiment tracking owns baseline metrics.
    deployed_at       — deployment timestamp on model_retrain_runs is the
                        authoritative source.
    deployed_by       — FK to platform.users; never populated.
    quantisation      — vLLM quantisation config is in Helm values, not DB.
    retire_reason     — model retirement not yet implemented; when it is,
                        a new migration will re-add with proper constraints.
    retired_at        — same rationale as retire_reason.

  platform.users:
    display_name_enc  — display names served from local_auth_accounts.display_name.
    email_enc         — email served from local_auth_accounts.email.
    primary_role      — role served from local_auth_accounts.role.
    saml_idp_entity_id — SAML IdP identity carried in JWT claim; not stored in DB.
    saml_subject      — SAML NameID stored in local_auth_accounts.saml_subject_id
                        (added by a later migration); this column was a duplicate.
    zone_scope        — zone scoping enforced at query time via bank_id + JWT claim.

━━━━ KEEP-PLANNED (no action) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  platform.opa_policy_versions — CLAUDE.md §Versioning Scope: "OPA Rego policies
    | YES | policy_version in YugabyteDB policy_versions table". Wiring deferred
    to NPCI API Modernisation Phase B. Table kept; wire-up tracked as WIRE-UP-FUTURE.

Revision ID: 20260916_drop_dead_schema
Revises: 20260916_platform_local_auth_cols
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260916_drop_dead_schema"
down_revision = "20260916_platform_local_auth_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Drop FK from notification_records.template_id before dropping templates table
    # The FK is nullable; records without a template_id are the common case.
    op.execute(
        "ALTER TABLE platform.notification_records "
        "DROP CONSTRAINT IF EXISTS notification_records_template_id_fkey"
    )

    # ── 2. Drop dead tables (order: dependants before parents) ────────────────
    # model_drift_alerts has FK → model_versions; drop it before considering parent
    op.drop_table("model_drift_alerts", schema="platform")
    op.drop_table("bank_module_config", schema="platform")
    op.drop_table("bank_onboarding_events", schema="platform")
    op.drop_table("config_change_log", schema="platform")
    op.drop_table("config_entries", schema="platform")
    op.drop_table("immudb_verification_log", schema="platform")
    op.drop_table("login_events", schema="platform")
    op.drop_table("notification_templates", schema="platform")
    op.drop_table("user_preferences", schema="platform")
    op.drop_table("user_roles", schema="platform")
    op.drop_table("user_sessions", schema="platform")

    # ── 3. Drop dead columns from platform.audit_events ──────────────────────
    # actor_user_id has a partial index; PostgreSQL/YugabyteDB drops it automatically
    # with the column, but we drop it explicitly for clarity.
    op.drop_index(
        "ix_platform_audit_events_actor",
        table_name="audit_events",
        schema="platform",
        if_exists=True,
    )
    op.drop_column("audit_events", "actor_service", schema="platform")
    op.drop_column("audit_events", "actor_user_id", schema="platform")
    op.drop_column("audit_events", "module", schema="platform")
    op.drop_column("audit_events", "subject_id", schema="platform")
    op.drop_column("audit_events", "subject_type", schema="platform")

    # ── 4. Drop dead columns from platform.model_versions ────────────────────
    # deployed_by has an FK constraint to platform.users; dropped automatically
    # when the column is dropped in YugabyteDB (YSQL behaves like PostgreSQL here).
    op.drop_column("model_versions", "baseline_metrics", schema="platform")
    op.drop_column("model_versions", "deployed_at", schema="platform")
    op.drop_column("model_versions", "deployed_by", schema="platform")
    op.drop_column("model_versions", "quantisation", schema="platform")
    op.drop_column("model_versions", "retire_reason", schema="platform")
    op.drop_column("model_versions", "retired_at", schema="platform")

    # ── 5. Drop dead columns from platform.users ─────────────────────────────
    op.drop_column("users", "display_name_enc", schema="platform")
    op.drop_column("users", "email_enc", schema="platform")
    op.drop_column("users", "primary_role", schema="platform")
    op.drop_column("users", "saml_idp_entity_id", schema="platform")
    op.drop_column("users", "saml_subject", schema="platform")
    op.drop_column("users", "zone_scope", schema="platform")


def downgrade() -> None:
    # ── Restore platform.users columns ───────────────────────────────────────
    op.add_column("users", sa.Column("zone_scope", JSONB(), nullable=True), schema="platform")
    op.add_column("users", sa.Column("saml_subject", sa.Text(), nullable=True), schema="platform")
    op.add_column("users", sa.Column("saml_idp_entity_id", sa.Text(), nullable=True), schema="platform")
    op.add_column("users", sa.Column("primary_role", sa.Text(), nullable=True), schema="platform")
    op.add_column("users", sa.Column("email_enc", sa.LargeBinary(), nullable=True), schema="platform")
    op.add_column("users", sa.Column("display_name_enc", sa.LargeBinary(), nullable=True), schema="platform")

    # ── Restore platform.model_versions columns ───────────────────────────────
    op.add_column("model_versions", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True), schema="platform")
    op.add_column("model_versions", sa.Column("retire_reason", sa.Text(), nullable=True), schema="platform")
    op.add_column("model_versions", sa.Column("quantisation", sa.Text(), nullable=True), schema="platform")
    op.add_column("model_versions", sa.Column("deployed_by", UUID(as_uuid=True), nullable=True), schema="platform")
    op.add_column("model_versions", sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True), schema="platform")
    op.add_column("model_versions", sa.Column("baseline_metrics", JSONB(), nullable=True), schema="platform")

    # ── Restore platform.audit_events columns ────────────────────────────────
    op.add_column("audit_events", sa.Column("subject_type", sa.Text(), nullable=True), schema="platform")
    op.add_column("audit_events", sa.Column("subject_id", sa.Text(), nullable=True), schema="platform")
    op.add_column("audit_events", sa.Column("module", sa.Text(), nullable=True), schema="platform")
    op.add_column("audit_events", sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True), schema="platform")
    op.add_column("audit_events", sa.Column("actor_service", sa.Text(), nullable=True), schema="platform")
    op.create_index(
        "ix_platform_audit_events_actor",
        "audit_events",
        ["actor_user_id", "occurred_at"],
        schema="platform",
        postgresql_where=sa.text("actor_user_id IS NOT NULL"),
    )

    # ── Restore dropped tables (minimal schema — data cannot be recovered) ───
    op.create_table(
        "user_sessions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "user_roles",
        sa.Column("role_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "user_preferences",
        sa.Column("pref_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "notification_templates",
        sa.Column("template_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "login_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "immudb_verification_log",
        sa.Column("log_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "config_entries",
        sa.Column("entry_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "config_change_log",
        sa.Column("log_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "bank_onboarding_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "bank_module_config",
        sa.Column("config_id", sa.Text(), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    op.create_table(
        "model_drift_alerts",
        sa.Column("alert_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="platform",
    )
    # Restore FK from notification_records to notification_templates
    op.create_foreign_key(
        "notification_records_template_id_fkey",
        "notification_records",
        "notification_templates",
        ["template_id"],
        ["template_id"],
        source_schema="platform",
        referent_schema="platform",
    )
