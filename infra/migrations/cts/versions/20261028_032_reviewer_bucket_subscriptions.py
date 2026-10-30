"""cts.reviewer_bucket_subscriptions and cts.bucket_account_lists.

Which review buckets each reviewer is connected to (admin-controlled), and the bank-maintained account lists that put an
account in the CA (corporate) or IP (institution) bucket. MISC needs no subscription: anyone may self-claim from it.

Revision ID: 20261028_032
Revises: 20261013_031
Create Date: 2026-10-28
"""
from alembic import op

revision = "20261028_032"
down_revision = "20261013_031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cts.reviewer_bucket_subscriptions (
            bank_id     TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            bucket      TEXT NOT NULL CHECK (bucket IN ('HVC','CA','IP','LVC','FCC','SIP_SUCCESS','SIP_REJECT','HR','VAL')),
            created_by  TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (bank_id, reviewer_id, bucket)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviewer_bucket_subs_bucket ON cts.reviewer_bucket_subscriptions (bank_id, bucket)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cts.bucket_account_lists (
            bank_id      TEXT NOT NULL,
            bucket       TEXT NOT NULL CHECK (bucket IN ('CA','IP')),
            account_hash TEXT NOT NULL,
            account_last4 TEXT NOT NULL DEFAULT '',   -- display only; the number itself is never stored
            added_by     TEXT NOT NULL,
            added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (bank_id, bucket, account_hash)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.bucket_account_lists")
    op.execute("DROP TABLE IF EXISTS cts.reviewer_bucket_subscriptions")
