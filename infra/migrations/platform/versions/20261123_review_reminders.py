"""Reminders for overdue post-incident reviews and actions: remember when each was last reminded, so a reminder is sent at most once per reminder interval.

Additive only: one nullable column on each of platform.alert_reviews and platform.alert_actions.

Revision ID: 20261123_review_reminders
Revises: 20261120_alert_reviews
Create Date: 2026-11-23
"""
from alembic import op

revision = "20261123_review_reminders"
down_revision = "20261120_alert_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE platform.alert_reviews ADD COLUMN IF NOT EXISTS last_reminded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE platform.alert_actions ADD COLUMN IF NOT EXISTS last_reminded_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE platform.alert_actions DROP COLUMN IF EXISTS last_reminded_at")
    op.execute("ALTER TABLE platform.alert_reviews DROP COLUMN IF EXISTS last_reminded_at")
