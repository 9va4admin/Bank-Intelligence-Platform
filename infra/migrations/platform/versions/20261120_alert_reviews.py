"""Post-incident reviews and mitigation actions (docs/design/alerting-blueprint.md, section 18).

platform.alert_reviews  one row per resolved P0/P1 incident: a review that becomes due, then is submitted (root cause, narrative, detection gap, impact, a linked risk)
platform.alert_actions  corrective or preventive actions from a review: owner, due date, status, evidence, and who verified it (never the person who did it)

Additive only.

Revision ID: 20261120_alert_reviews
Revises: 20261119_alert_risks
Create Date: 2026-11-20
"""
from alembic import op

revision = "20261120_alert_reviews"
down_revision = "20261119_alert_risks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_reviews (
            review_id            TEXT PRIMARY KEY,
            bank_id              TEXT NOT NULL,
            incident_id          TEXT NOT NULL,
            severity             TEXT NOT NULL,
            component            TEXT NOT NULL DEFAULT '',
            dedup_key            TEXT NOT NULL DEFAULT '',
            resolved_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status               TEXT NOT NULL DEFAULT 'DUE' CHECK (status IN ('DUE','SUBMITTED')),
            root_cause_category  TEXT,
            narrative            TEXT NOT NULL DEFAULT '',
            contributing_factors TEXT NOT NULL DEFAULT '',
            detection_gap        TEXT NOT NULL DEFAULT '',
            impact               TEXT NOT NULL DEFAULT '',
            risk_id              TEXT,
            submitted_by         TEXT,
            submitted_at         TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_reviews_incident ON platform.alert_reviews (bank_id, incident_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_actions (
            action_id      TEXT PRIMARY KEY,
            bank_id        TEXT NOT NULL,
            review_id      TEXT NOT NULL,
            kind           TEXT NOT NULL CHECK (kind IN ('corrective','preventive')),
            description    TEXT NOT NULL,
            owner          TEXT NOT NULL,
            due_on         DATE NOT NULL,
            status         TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','IN_PROGRESS','DONE','VERIFIED','WONT_FIX')),
            evidence       TEXT NOT NULL DEFAULT '',
            note           TEXT NOT NULL DEFAULT '',
            done_by        TEXT,
            done_at        TIMESTAMPTZ,
            verified_by    TEXT,
            verified_at    TIMESTAMPTZ,
            created_by     TEXT NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_actions_review ON platform.alert_actions (bank_id, review_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.alert_actions")
    op.execute("DROP TABLE IF EXISTS platform.alert_reviews")
