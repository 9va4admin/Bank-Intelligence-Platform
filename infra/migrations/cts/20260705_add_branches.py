"""add cts.branches table

Branch — the physical location where cheque scanning happens. Each branch is
administratively mapped to exactly one Processing Unit (PU). The branch→PU
mapping is stored here; the assignment is done by the bank IT admin in the
Admin UI and does not need to follow geographic conventions.

A bank always has at least one branch. The SMB (Sub-Member Bank) may have
its own branches in the context of the Agency deployment scenario, where the
Agency CC acts as sponsor; in that case, smb_id is populated.

Revision ID: 20260705_add_branches
Revises: 20260705_add_processing_units
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_add_branches"
down_revision = "20260705_add_processing_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "branches",
        sa.Column("branch_id", sa.Text(), nullable=False, comment="Internal branch identifier"),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "smb_id",
            sa.Text(),
            nullable=True,
            comment="Populated only for SMB branches in Agency deployment scenario",
        ),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column("branch_ifsc", sa.Text(), nullable=False, comment="RBI-assigned 11-character IFSC code"),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column(
            "pu_id",
            sa.Text(),
            nullable=False,
            comment="FK to cts.processing_units.pu_id — administrative mapping, not geographic",
        ),
        sa.Column(
            "drop_folder_base_path",
            sa.Text(),
            nullable=True,
            comment=(
                "Base path of the scanner drop folder for this branch. "
                "Scans land here; ASTRA file watcher monitors it."
            ),
        ),
        sa.Column(
            "is_scanning_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="False = branch is a presentment-only branch (no scanner attached)",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
        sa.PrimaryKeyConstraint("branch_id"),
        schema="cts",
    )

    # IFSC must be globally unique across the platform (two banks cannot share an IFSC)
    op.create_index(
        "uq_branches_ifsc",
        "branches",
        ["branch_ifsc"],
        unique=True,
        schema="cts",
    )

    # Fast lookup: all branches for a bank
    op.create_index(
        "ix_branches_bank_id",
        "branches",
        ["bank_id"],
        schema="cts",
    )

    # Fast lookup: all branches mapped to a given PU (for PU admin console)
    op.create_index(
        "ix_branches_pu_id",
        "branches",
        ["pu_id"],
        schema="cts",
    )

    # Fast lookup: SMB-scoped branch list
    op.create_index(
        "ix_branches_bank_smb",
        "branches",
        ["bank_id", "smb_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_branches_bank_smb", table_name="branches", schema="cts")
    op.drop_index("ix_branches_pu_id", table_name="branches", schema="cts")
    op.drop_index("ix_branches_bank_id", table_name="branches", schema="cts")
    op.drop_index("uq_branches_ifsc", table_name="branches", schema="cts")
    op.drop_table("branches", schema="cts")
