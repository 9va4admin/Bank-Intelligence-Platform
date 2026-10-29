"""Held outward items get review buckets (OUT_HV, OUT_MISMATCH, OUT_COMPLIANCE, OUT_REVIEW): a reviewer can be connected to them.

Revision ID: 20261029_035
Revises: 20261029_034
Create Date: 2026-10-29
"""
from alembic import op

revision = "20261029_035"
down_revision = "20261029_034"
branch_labels = None
depends_on = None

_OLD = "'HVC','CA','IP','LVC','FCC','SIP_SUCCESS','SIP_REJECT','HR','VAL'"
_NEW = _OLD + ",'OUT_HV','OUT_MISMATCH','OUT_COMPLIANCE','OUT_REVIEW'"


def _set(allowed: str) -> None:
    op.execute("ALTER TABLE cts.reviewer_bucket_subscriptions DROP CONSTRAINT IF EXISTS reviewer_bucket_subscriptions_bucket_check")
    op.execute(f"ALTER TABLE cts.reviewer_bucket_subscriptions ADD CONSTRAINT reviewer_bucket_subscriptions_bucket_check "
               f"CHECK (bucket IN ({allowed}))")


def upgrade() -> None:
    _set(_NEW)


def downgrade() -> None:
    op.execute(r"DELETE FROM cts.reviewer_bucket_subscriptions WHERE bucket LIKE 'OUT\_%'")
    _set(_OLD)
