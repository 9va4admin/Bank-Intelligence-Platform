"""Human-review queue: which tier and which LEVEL an item is at.

queue_tier   standard | high_value | very_high   (same tiers as the review task queues)
review_level 1 = first reviewer, 2+ = escalated approver
status       PENDING -> ASSIGNED -> IN_REVIEW -> DECIDED   (escalation: level+1 and back to PENDING)

Revision ID: 20260921_024
Revises: 20260921_023
Create Date: 2026-09-21
"""
from alembic import op

revision = "20260921_024"
down_revision = "20260921_023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cts.human_review_items ADD COLUMN IF NOT EXISTS queue_tier TEXT NOT NULL DEFAULT 'standard'")
    op.execute("ALTER TABLE cts.human_review_items ADD COLUMN IF NOT EXISTS review_level SMALLINT NOT NULL DEFAULT 1")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'human_review_items_level_chk') THEN
                ALTER TABLE cts.human_review_items ADD CONSTRAINT human_review_items_level_chk CHECK (review_level >= 1);
            END IF;
        END $$;
    """)
    op.execute("DROP INDEX IF EXISTS cts.ix_human_review_items_open")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_human_review_items_open
        ON cts.human_review_items (bank_id, direction, queue_tier, review_level, created_at)
        WHERE status IN ('PENDING','ASSIGNED','IN_REVIEW')
    """)


def downgrade() -> None:
    pass
