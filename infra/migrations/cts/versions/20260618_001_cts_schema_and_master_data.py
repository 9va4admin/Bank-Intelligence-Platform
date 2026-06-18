"""CTS schema + CTS-specific master data: clearing_zones, processing_centers, branches_master.

Banks registry moved to platform.banks (platform migration 001).
All bank_id FKs in this file point to platform.banks.bank_id.

Depends on: platform migration chain must run first (platform schema + banks table must exist).

Revision ID: 20260618_001
Revises: (base — CTS chain; platform chain is a prerequisite run separately)
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
    # Extensions already created by platform migration — IF NOT EXISTS is safe
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── clearing_zones ─────────────────────────────────────────────────────
    # CTS-specific: NGCH clearing zones (MUMBAI, DELHI, CHENNAI, KOLKATA, etc.)
    # Not in platform schema — clearing zones are a CTS concept only.
    op.create_table(
        "clearing_zones",
        sa.Column("zone_id", sa.Text, primary_key=True),
        # e.g. "NGCH_MUMBAI", "NGCH_DELHI", "NGCH_NATIONAL"
        sa.Column("zone_name", sa.Text, nullable=False),
        sa.Column("ngch_endpoint", sa.Text, nullable=True),
        # NGCH SFTP/API endpoint for this zone — from Vault, not stored plaintext here
        # This field stores the endpoint identifier, not credentials
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        schema="cts",
    )

    # ── processing_centers ─────────────────────────────────────────────────
    # Regional Processing Centers (RPCs) per bank per clearing zone.
    # Large banks have one RPC per zone; smaller banks use a single center.
    op.create_table(
        "processing_centers",
        sa.Column("center_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"),  # → platform schema
                  nullable=False),
        sa.Column("zone_id", sa.Text,
                  sa.ForeignKey("cts.clearing_zones.zone_id"), nullable=False),
        sa.Column("center_name", sa.Text, nullable=False),  # e.g. "MUMBAI_RPC"
        sa.Column("center_code", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        schema="cts",
    )
    op.create_index("ix_cts_processing_centers_bank", "processing_centers",
                    ["bank_id"], schema="cts")

    # ── branches_master ────────────────────────────────────────────────────
    # CTS-specific: branches that participate in cheque clearing.
    # Not all branches present cheques (some are sub-offices under a service branch).
    op.create_table(
        "branches_master",
        sa.Column("branch_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"),  # → platform schema
                  nullable=False),
        sa.Column("center_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.processing_centers.center_id"), nullable=True),
        sa.Column("ifsc", sa.Text, nullable=False, unique=True),
        sa.Column("branch_name", sa.Text, nullable=False),
        sa.Column("micr_code", sa.Text, nullable=True),      # 9-digit MICR city code
        sa.Column("is_service_branch", sa.Boolean, nullable=False,
                  server_default="false"),
        # Service branch submits to NGCH on behalf of sub-branches
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
    op.execute("DROP SCHEMA IF EXISTS cts CASCADE")
