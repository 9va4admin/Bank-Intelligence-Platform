"""Add OCR provenance columns to cts.agent_decisions.

ocr_engines_used            — ordered list of engines that ran (e.g. ["got-ocr2.0:cascade-1"])
indic_ocr_kill_switch_active — True when IndicOCR was bypassed by the kill switch at the time
                               of this decision

For inward (drawee) decisions these fields are always empty / False — no OCR on drawee side.
For outward scan decisions (via outward_scan_workflow) the fields carry OCR engine provenance.

Revision ID: 20260815_017
Revises: 20260730_016
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260815_017"
down_revision = "20260730_016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_decisions",
        sa.Column("ocr_engines_used", JSONB, nullable=True, server_default="'[]'::jsonb"),
        schema="cts",
    )
    op.add_column(
        "agent_decisions",
        sa.Column("indic_ocr_kill_switch_active", sa.Boolean, nullable=False,
                  server_default="false"),
        schema="cts",
    )


def downgrade() -> None:
    op.drop_column("agent_decisions", "indic_ocr_kill_switch_active", schema="cts")
    op.drop_column("agent_decisions", "ocr_engines_used", schema="cts")
