"""Alerting tables: incidents, component state history, deliveries (outbox and delivery log in one), and the per-user notification inbox (the bell).

Design: docs/design/alerting-blueprint.md (sections 3, 16, 17). Additive only; no existing table is touched.

  platform.alert_incidents          one row per incident; at most one OPEN/ACKED incident per (bank_id, dedup_key)
  platform.component_state_history  every component state change, so uptime comes from facts
  platform.alert_deliveries         one row per (incident, escalation level, target, channel): queued, sent, failed; idempotent on idempotency_key
  platform.user_notifications       what the bell shows each user (real data, scoped to the user)

Recipients are stored masked or as an internal user reference, never as the raw address (PII rule).

Revision ID: 20261117_alerting_tables
Revises: 20261029_drop_clearing_zones
Create Date: 2026-11-17
"""
from alembic import op

revision = "20261117_alerting_tables"
down_revision = "20261029_drop_clearing_zones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_incidents (
            incident_id        TEXT PRIMARY KEY,
            bank_id            TEXT NOT NULL,
            dedup_key          TEXT NOT NULL,
            alert_id           TEXT NOT NULL,
            component          TEXT NOT NULL DEFAULT '',
            category           TEXT NOT NULL DEFAULT '',
            severity           TEXT NOT NULL CHECK (severity IN ('P0','P1','P2','P3')),
            state              TEXT NOT NULL CHECK (state IN ('OPEN','ACKED','RESOLVED')),
            scope_level        TEXT NOT NULL DEFAULT 'BANK' CHECK (scope_level IN ('BANK','PU','SMB')),
            pu_id              TEXT,
            smb_id             TEXT,
            summary            TEXT NOT NULL,
            impact             TEXT NOT NULL DEFAULT '',
            root_cause_category TEXT,
            opened_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acked_at           TIMESTAMPTZ,
            acked_by           TEXT,
            resolved_at        TIMESTAMPTZ,
            resolved_by        TEXT,
            last_notified_at   TIMESTAMPTZ,
            notification_count INTEGER NOT NULL DEFAULT 0,
            escalation_level   INTEGER NOT NULL DEFAULT 0,
            linked_change_id   TEXT
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_incidents_open_key ON platform.alert_incidents (bank_id, dedup_key) WHERE state <> 'RESOLVED'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_incidents_bank_opened ON platform.alert_incidents (bank_id, opened_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_incidents_bank_component ON platform.alert_incidents (bank_id, component, opened_at DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.component_state_history (
            id           BIGSERIAL PRIMARY KEY,
            bank_id      TEXT NOT NULL,
            component    TEXT NOT NULL,
            from_status  TEXT NOT NULL,
            to_status    TEXT NOT NULL,
            changed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            latency_ms   DOUBLE PRECISION,
            error        TEXT,
            incident_id  TEXT
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_component_state_history_lookup ON platform.component_state_history (bank_id, component, changed_at DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_deliveries (
            delivery_id        TEXT PRIMARY KEY,
            bank_id            TEXT NOT NULL,
            incident_id        TEXT NOT NULL,
            idempotency_key    TEXT NOT NULL,
            escalation_level   INTEGER NOT NULL DEFAULT 0,
            channel            TEXT NOT NULL CHECK (channel IN ('email','whatsapp','bell','sms','webhook','syslog')),
            recipient_ref      TEXT NOT NULL,
            template_id        TEXT,
            status             TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SENDING','SENT','FAILED','UNDELIVERED','SKIPPED')),
            attempt            INTEGER NOT NULL DEFAULT 0,
            next_attempt_at    TIMESTAMPTZ,
            provider_class     TEXT,
            error              TEXT,
            fallback_of        TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at       TIMESTAMPTZ,
            audit_intent_ref   TEXT,
            audit_outcome_ref  TEXT
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_deliveries_idem ON platform.alert_deliveries (bank_id, idempotency_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_deliveries_incident ON platform.alert_deliveries (bank_id, incident_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_deliveries_due ON platform.alert_deliveries (next_attempt_at) WHERE status IN ('PENDING','FAILED')")

    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.user_notifications (
            notification_id TEXT PRIMARY KEY,
            bank_id         TEXT NOT NULL,
            user_id         TEXT NOT NULL,
            incident_id     TEXT,
            severity        TEXT NOT NULL CHECK (severity IN ('P0','P1','P2','P3')),
            title           TEXT NOT NULL,
            body            TEXT NOT NULL DEFAULT '',
            action_link     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            read_at         TIMESTAMPTZ,
            acked_at        TIMESTAMPTZ
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_notifications_user ON platform.user_notifications (bank_id, user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_notifications_unread ON platform.user_notifications (bank_id, user_id) WHERE read_at IS NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.user_notifications")
    op.execute("DROP TABLE IF EXISTS platform.alert_deliveries")
    op.execute("DROP TABLE IF EXISTS platform.component_state_history")
    op.execute("DROP TABLE IF EXISTS platform.alert_incidents")
