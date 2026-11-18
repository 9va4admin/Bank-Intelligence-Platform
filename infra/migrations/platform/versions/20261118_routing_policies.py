"""platform.alert_routing_policies: versioned alert routing policies per bank and scope (Bank, PU, SMB), with maker-checker.

A policy can name external email addresses (personal data), so the body is stored encrypted (pgcrypto, the bank's PII key); rule_ids is the only readable
summary. One ACTIVE policy per (bank, scope); every change is a new version (PENDING until a different person approves it), and old versions stay as
SUPERSEDED history. Additive only. docs/design/alerting-1b-plan.md

Revision ID: 20261118_routing_policies
Revises: 20261117_user_directory
Create Date: 2026-11-18
"""
from alembic import op

revision = "20261118_routing_policies"
down_revision = "20261117_user_directory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_routing_policies (
            policy_id    TEXT PRIMARY KEY,
            bank_id      TEXT NOT NULL,
            scope_level  TEXT NOT NULL CHECK (scope_level IN ('BANK','PU','SMB')),
            scope_id     TEXT NOT NULL DEFAULT '',
            version      INTEGER NOT NULL,
            status       TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','SUPERSEDED','REJECTED')),
            policy_enc   BYTEA NOT NULL,
            rule_ids     TEXT[] NOT NULL DEFAULT '{}',
            note         TEXT,
            created_by   TEXT NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            approved_by  TEXT,
            approved_at  TIMESTAMPTZ
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_routing_policies_version ON platform.alert_routing_policies (bank_id, scope_level, scope_id, version)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_routing_policies_active ON platform.alert_routing_policies (bank_id, scope_level, scope_id) WHERE status = 'ACTIVE'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_routing_policies_pending ON platform.alert_routing_policies (bank_id, created_at DESC) WHERE status = 'PENDING'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.alert_routing_policies")
