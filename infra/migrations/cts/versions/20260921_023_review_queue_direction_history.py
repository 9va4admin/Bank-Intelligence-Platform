"""Durable human-review queue: one table with a direction flag + append-only history.

cts.human_review_items was designed for inward only (decision_id and iet_deadline_at NOT NULL,
assigned_reviewer_id uuid although user ids are text) and no code ever wrote it, so the review queue
lived only in Redis/Kafka. Reshaped so inward AND outward share one table:
  * direction INWARD|OUTWARD
  * decision_id / iet_deadline_at nullable (outward has no IET)
  * assigned_reviewer_id TEXT
  * unique (bank_id, workflow_id) -> idempotent upsert
  * partial index over OPEN items (PENDING/ASSIGNED) -> decided items never slow the live queue
  * cts.human_review_history: append-only, one row per state change (CREATED/ASSIGNED/DECIDED/...)

Revision ID: 20260921_023
Revises: 20260921_022
Create Date: 2026-09-21
"""
from alembic import op

revision = "20260921_023"
down_revision = "20260921_022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cts.human_review_items ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'INWARD'")
    op.execute("ALTER TABLE cts.human_review_items ADD COLUMN IF NOT EXISTS instrument_ref TEXT")
    op.execute("ALTER TABLE cts.human_review_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE cts.human_review_items ALTER COLUMN decision_id DROP NOT NULL")
    op.execute("ALTER TABLE cts.human_review_items ALTER COLUMN iet_deadline_at DROP NOT NULL")
    op.execute("ALTER TABLE cts.human_review_items ALTER COLUMN assigned_reviewer_id TYPE TEXT USING assigned_reviewer_id::text")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'human_review_items_direction_chk') THEN
                ALTER TABLE cts.human_review_items
                    ADD CONSTRAINT human_review_items_direction_chk CHECK (direction IN ('INWARD','OUTWARD'));
            END IF;
        END $$;
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_human_review_items_bank_workflow ON cts.human_review_items (bank_id, workflow_id)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_human_review_items_open
        ON cts.human_review_items (bank_id, direction, created_at)
        WHERE status IN ('PENDING','ASSIGNED')
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS cts.human_review_history (
            history_id  UUID        NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
            review_id   UUID        NOT NULL,
            bank_id     TEXT        NOT NULL,
            event       TEXT        NOT NULL,
            actor       TEXT,
            detail      JSONB       NOT NULL DEFAULT '{}'::jsonb,
            at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_human_review_history_review ON cts.human_review_history (review_id, at)")


def downgrade() -> None:
    # history rows are audit data; a routine downgrade must not destroy them
    pass
