"""branches: add scanner_input_mode column

Adds branch-level scanner input mode configuration.

  scanner_input_mode TEXT NOT NULL DEFAULT 'UI_UPLOAD'
    UI_UPLOAD   — operator uploads cheque images via web UI (POC default)
    FOLDER_DROP — scanner writes images to drop_folder_base_path; ASTRA watcher picks up
    SDK_PUSH    — scanner SDK calls POST /v1/cts/outward/scan/submit directly

The drop_folder_base_path column (added in 20260705_add_branches) is reused as
the watched folder path when scanner_input_mode = 'FOLDER_DROP'.
For SDK_PUSH, the existing API endpoint handles everything — no folder needed.

Revision ID: 20260811_branches_add_scanner_input_mode
Revises: 20260806_branches_add_contact_fields
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_branches_add_scanner_input_mode"
down_revision = "20260806_branches_add_contact_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column(
            "scanner_input_mode",
            sa.Text(),
            nullable=False,
            server_default="UI_UPLOAD",
        ),
        schema="cts",
    )
    op.create_check_constraint(
        "ck_branches_scanner_input_mode",
        "branches",
        "scanner_input_mode IN ('UI_UPLOAD', 'FOLDER_DROP', 'SDK_PUSH')",
        schema="cts",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_branches_scanner_input_mode",
        "branches",
        type_="check",
        schema="cts",
    )
    op.drop_column("branches", "scanner_input_mode", schema="cts")
