"""add cts.scanner_configs table

ScannerConfig — branch-level OEM scanner configuration. Each branch that has a
physical scanner attached has exactly one ScannerConfig (or inherits a bank-level
default where branch_id IS NULL).

The config tells ScannerDropFolderMapper:
  - Which OEM produced the metadata file (scanner_oem)
  - What format the metadata file uses (output_format: CSV_COMMA, CSV_PIPE, XML, …)
  - How to map OEM field names → canonical field names (field_mapping JSONB)
  - How to parse amounts (amount_format: DECIMAL_DOT, DECIMAL_COMMA, INTEGER_PAISE)
  - How to parse dates (date_format: strptime pattern)
  - How to resolve image file paths from the drop folder (image_naming_pattern)
  - What OEM side codes map to canonical sides (image_side_mapping JSONB)

Identical pattern to EJ OEM fingerprinting — explicit per-branch config rather
than dynamic auto-detection, because scanner OEM is a known, administered fact.

Revision ID: 20260705_add_scanner_configs
Revises: 20260705_add_branches
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260705_add_scanner_configs"
down_revision = "20260705_add_branches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "scanner_configs",
        sa.Column("scanner_config_id", sa.Text(), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "branch_id",
            sa.Text(),
            nullable=True,
            comment="NULL = bank-wide default (used when branch has no specific override)",
        ),
        sa.Column(
            "scanner_oem",
            sa.Text(),
            nullable=False,
            comment="PANINI | DIGITAL_CHECK | MAGTEK | RDM | OPEX | CANON | GENERIC",
        ),
        sa.Column("scanner_model", sa.Text(), nullable=False, comment="e.g. Panini My Vision X, DC TS240"),
        sa.Column(
            "output_format",
            sa.Text(),
            nullable=False,
            comment="CSV_COMMA | CSV_PIPE | CSV_TAB | XML | FIXED_WIDTH",
        ),
        sa.Column(
            "date_format",
            sa.Text(),
            nullable=False,
            comment="Python strptime pattern — e.g. %d%m%Y or %Y-%m-%d",
        ),
        sa.Column(
            "amount_format",
            sa.Text(),
            nullable=False,
            comment="DECIMAL_DOT | DECIMAL_COMMA | INTEGER_PAISE",
        ),
        sa.Column(
            "field_mapping",
            JSONB(),
            nullable=False,
            comment=(
                "OEM field name → canonical field name mapping. "
                "Required canonical fields: micr_line, amount_figures, amount_words, "
                "payee_name, cheque_date, batch_id, sequence_in_batch, account_number"
            ),
        ),
        sa.Column(
            "image_naming_pattern",
            sa.Text(),
            nullable=False,
            comment=(
                "Pattern with {batch_id}, {seq}, {side} tokens — OR pipe-separated triple "
                "for OEMs that use positional naming: color_front|grey_front|rear"
            ),
        ),
        sa.Column(
            "image_side_mapping",
            JSONB(),
            nullable=False,
            comment=(
                "OEM side code → canonical side name. "
                "Must map all three: color_front, grey_front, rear. "
                "e.g. {\"F\": \"color_front\", \"G\": \"grey_front\", \"R\": \"rear\"}"
            ),
        ),
        sa.Column(
            "drop_folder_path",
            sa.Text(),
            nullable=False,
            comment="Absolute path on the host where OEM software writes output files",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Inactive configs are ignored by the file watcher",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
        sa.PrimaryKeyConstraint("scanner_config_id"),
        schema="cts",
    )

    # One scanner config per branch (or one bank-level default where branch_id IS NULL).
    # COALESCE so NULL branch_id is treated as '' for uniqueness (same pattern as mcp_connection_configs).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_scanner_configs_bank_branch
        ON cts.scanner_configs (bank_id, COALESCE(branch_id, ''))
        """
    )

    # Fast lookup: all scanner configs for a bank (admin console list view)
    op.create_index(
        "ix_scanner_configs_bank_id",
        "scanner_configs",
        ["bank_id"],
        schema="cts",
    )

    # Fast lookup: by branch (file watcher resolve at runtime)
    op.create_index(
        "ix_scanner_configs_branch_id",
        "scanner_configs",
        ["branch_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_scanner_configs_branch_id", table_name="scanner_configs", schema="cts")
    op.drop_index("ix_scanner_configs_bank_id", table_name="scanner_configs", schema="cts")
    op.execute("DROP INDEX IF EXISTS cts.uq_scanner_configs_bank_branch")
    op.drop_table("scanner_configs", schema="cts")
