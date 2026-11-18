"""Alert silences: a planned quiet period for one component (or all) so maintenance does not page people. Incidents are still recorded; only the notifications are held back.

platform.alert_silences  one row per silence: bank, component ('' = every component), the priorities it covers, when it starts and ends, why, who made it, and whether it was cancelled early

Additive only.

Revision ID: 20261119_alert_silences
Revises: 20261119_alert_contacts
Create Date: 2026-11-19
"""
from alembic import op

revision = "20261119_alert_silences"
down_revision = "20261119_alert_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_silences (
            silence_id    TEXT PRIMARY KEY,
            bank_id       TEXT NOT NULL,
            component     TEXT NOT NULL DEFAULT '',
            priorities    TEXT[] NOT NULL,
            starts_at     TIMESTAMPTZ NOT NULL,
            ends_at       TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
            reason        TEXT NOT NULL,
            created_by    TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            cancelled_at  TIMESTAMPTZ,
            cancelled_by  TEXT
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_silences_lookup ON platform.alert_silences (bank_id, ends_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.alert_silences")
