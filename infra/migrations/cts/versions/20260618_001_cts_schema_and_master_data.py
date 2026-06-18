"""CTS schema + master data tables: banks, branches, processing_centers, clearing_zones.

Revision ID: 20260618_001
Revises: (base)
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create CTS schema ──────────────────────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── banks_master ───────────────────────────────────────────────────────
    op.create_table(
        "banks_master",
        sa.Column("bank_id", sa.Text, primary_key=True),
        sa.Column("bank_name", sa.Text, nullable=False),
        sa.Column("bank_code", sa.Text, nullable=False, unique=True),   # NPCI bank code
        sa.Column("ifsc_prefix", sa.Text, nullable=False),              # first 4 chars of IFSC
        sa.Column("ngch_member_code", sa.Text, nullable=True),          # NGCH clearing member code
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_banks_master_bank_code", "banks_master",
                    ["bank_code"], schema="cts")

    # ── clearing_zones ─────────────────────────────────────────────────────
    op.create_table(
        "clearing_zones",
        sa.Column("zone_id", sa.Text, primary_key=True),               # e.g. "NGCH_NATIONAL"
        sa.Column("zone_name", sa.Text, nullable=False),
        sa.Column("ngch_endpoint", sa.Text, nullable=True),            # NGCH SFTP/API endpoint
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        schema="cts",
    )

    # ── processing_centers ─────────────────────────────────────────────────
    op.create_table(
        "processing_centers",
        sa.Column("center_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("zone_id", sa.Text, sa.ForeignKey("cts.clearing_zones.zone_id"),
                  nullable=False),
        sa.Column("center_name", sa.Text, nullable=False),             # e.g. "MUMBAI_RPC"
        sa.Column("center_code", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        schema="cts",
    )
    op.create_index("ix_cts_processing_centers_bank", "processing_centers",
                    ["bank_id"], schema="cts")

    # ── branches_master ────────────────────────────────────────────────────
    op.create_table(
        "branches_master",
        sa.Column("branch_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("center_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.processing_centers.center_id"), nullable=True),
        sa.Column("ifsc", sa.Text, nullable=False, unique=True),
        sa.Column("branch_name", sa.Text, nullable=False),
        sa.Column("micr_code", sa.Text, nullable=True),                # 9-digit MICR city code
        sa.Column("is_service_branch", sa.Boolean, nullable=False,
                  server_default="false"),                             # submits to NGCH on behalf of others
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        schema="cts",
    )
    op.create_index("ix_cts_branches_bank_id", "branches_master",
                    ["bank_id"], schema="cts")
    op.create_index("ix_cts_branches_ifsc", "branches_master",
                    ["ifsc"], unique=True, schema="cts")
    op.create_index("ix_cts_branches_micr", "branches_master",
                    ["micr_code"], schema="cts")


def downgrade() -> None:
    op.drop_table("branches_master", schema="cts")
    op.drop_table("processing_centers", schema="cts")
    op.drop_table("clearing_zones", schema="cts")
    op.drop_table("banks_master", schema="cts")
    op.execute("DROP SCHEMA IF EXISTS cts CASCADE")
