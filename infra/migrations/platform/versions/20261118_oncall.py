"""On-call rotas and overrides: who is on duty, for alert routing (docs/design/alerting-1b-plan.md).

platform.alert_oncall_rotas      one row per (bank, rota name): the shifts and the fallback as JSON (user ids only, no personal data), versioned by update
platform.alert_oncall_overrides  a swap or a cover: this person replaces the rota between two times

Additive only.

Revision ID: 20261118_oncall
Revises: 20261118_routing_policies
Create Date: 2026-11-18
"""
from alembic import op

revision = "20261118_oncall"
down_revision = "20261118_routing_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_oncall_rotas (
            bank_id     TEXT NOT NULL,
            name        TEXT NOT NULL,
            rota        JSONB NOT NULL,
            version     INTEGER NOT NULL DEFAULT 1,
            updated_by  TEXT NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (bank_id, name)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_oncall_overrides (
            override_id TEXT PRIMARY KEY,
            bank_id     TEXT NOT NULL,
            rota_name   TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            starts_at   TIMESTAMPTZ NOT NULL,
            ends_at     TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
            reason      TEXT NOT NULL DEFAULT '',
            created_by  TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_oncall_overrides_lookup ON platform.alert_oncall_overrides (bank_id, rota_name, ends_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.alert_oncall_overrides")
    op.execute("DROP TABLE IF EXISTS platform.alert_oncall_rotas")
