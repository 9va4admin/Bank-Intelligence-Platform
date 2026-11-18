"""Alert risk register: the risks to alerting itself, seeded from a shipped template, each with an owner. Only a person declares a risk mitigated and a different person verifies it.

platform.alert_risks  one row per (bank, template risk): category, title, description, likelihood and impact (1 to 5), owner, status, the mitigation text, who declared and who verified, next review date

Additive only.

Revision ID: 20261119_alert_risks
Revises: 20261119_alert_silences
Create Date: 2026-11-19
"""
from alembic import op

revision = "20261119_alert_risks"
down_revision = "20261119_alert_silences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_risks (
            risk_id        TEXT PRIMARY KEY,
            bank_id        TEXT NOT NULL,
            template_key   TEXT NOT NULL,
            category       TEXT NOT NULL CHECK (category IN ('availability','capacity','security','vendor','process')),
            title          TEXT NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            likelihood     INTEGER NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
            impact         INTEGER NOT NULL CHECK (impact BETWEEN 1 AND 5),
            owner          TEXT,
            status         TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','MITIGATED','VERIFIED')),
            mitigation     TEXT NOT NULL DEFAULT '',
            declared_by    TEXT,
            verified_by    TEXT,
            next_review_on DATE,
            updated_by     TEXT NOT NULL,
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_risks_template ON platform.alert_risks (bank_id, template_key)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.alert_risks")
