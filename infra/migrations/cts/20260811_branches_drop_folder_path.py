"""branches: drop drop_folder_base_path column.

This column duplicated cts.scanner_configs.drop_folder_path, which is the
canonical location for the OEM drop folder (along with field_mapping, output
format, and image naming pattern that the file watcher needs).

For FOLDER_DROP mode, the admin configures a scanner_config row (via the
Scanner Config admin page); the branch row carries only scanner_input_mode.

Revision ID: 20260811_branches_drop_folder_path
Revises:     20260811_scanner_registrations
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_branches_drop_folder_path"
down_revision = "20260811_scanner_registrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("branches", "drop_folder_base_path", schema="cts")


def downgrade() -> None:
    op.add_column(
        "branches",
        sa.Column("drop_folder_base_path", sa.Text(), nullable=True),
        schema="cts",
    )
