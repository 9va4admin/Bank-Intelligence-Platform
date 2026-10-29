"""Remove the zone concept from processing units and review assignment.

A bank files to a single NGCH grid; a branch maps to a processing unit (PU) and a bank may have several PUs. So a PU is
no longer tied to a clearing zone: the one-PU-per-zone unique index goes, clearing_zone and ngch_participant_code become
optional, and review assignment records a PU instead of a zone. Nothing is dropped (deprecation pattern: the old
columns stay, unused, until a later release).

Revision ID: 20261029_034
Revises: 20261028_033
Create Date: 2026-10-29
"""
from alembic import op

revision = "20261029_034"
down_revision = "20261028_033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cts.uq_processing_units_bank_zone")
    op.execute("ALTER TABLE cts.processing_units ALTER COLUMN clearing_zone DROP NOT NULL")
    op.execute("ALTER TABLE cts.processing_units ALTER COLUMN ngch_participant_code DROP NOT NULL")
    op.execute("ALTER TABLE cts.human_review_items ADD COLUMN IF NOT EXISTS assigned_pu_id TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE cts.human_review_items DROP COLUMN IF EXISTS assigned_pu_id")
