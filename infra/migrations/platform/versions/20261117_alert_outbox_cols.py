"""Outbox columns on platform.alert_deliveries.

A retry or a fallback needs the real address, but the table must never hold it in the clear: recipient_enc is the address encrypted with the bank's
PII key (pgcrypto, shared/utils/pii_crypto.py); recipient_ref stays the masked form for display and audit. payload is the message content (no customer
data), priority is the alert's P0..P3, and claimed_until is the lease a delivery worker holds while it sends (an expired lease is reclaimed).
Additive only.

Revision ID: 20261117_alert_outbox_cols
Revises: 20261117_alerting_tables
Create Date: 2026-11-17
"""
from alembic import op

revision = "20261117_alert_outbox_cols"
down_revision = "20261117_alerting_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE platform.alert_deliveries ADD COLUMN IF NOT EXISTS recipient_enc BYTEA")
    op.execute("ALTER TABLE platform.alert_deliveries ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE platform.alert_deliveries ADD COLUMN IF NOT EXISTS priority TEXT")
    op.execute("ALTER TABLE platform.alert_deliveries ADD COLUMN IF NOT EXISTS claimed_until TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE platform.alert_deliveries DROP COLUMN IF EXISTS claimed_until")
    op.execute("ALTER TABLE platform.alert_deliveries DROP COLUMN IF EXISTS priority")
    op.execute("ALTER TABLE platform.alert_deliveries DROP COLUMN IF EXISTS payload")
    op.execute("ALTER TABLE platform.alert_deliveries DROP COLUMN IF EXISTS recipient_enc")
