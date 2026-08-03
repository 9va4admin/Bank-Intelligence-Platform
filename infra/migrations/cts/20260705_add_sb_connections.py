"""add cts.sb_connections table (Agency deployment mode)

SBConnection represents the Agency's connection to an upstream Sponsor Bank (SB).
This table is only populated in AGENCY_SB_RELAY deployment mode. In SB_NGCH mode,
the bank files directly to NGCH and this table is empty.

The Agency Command Center (agency-cc-service) reads this table to know which SBs
to route sealed lots to, and which adapter (SFTP_GENERIC, BANCS_API, NELITO_API)
to use per SB.

Revision ID: 20260705_add_sb_connections
Revises: 20260705_add_scanner_configs
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_add_sb_connections"
down_revision = "20260705_add_scanner_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "sb_connections",
        sa.Column("sb_connection_id", sa.Text(), nullable=False),
        sa.Column(
            "agency_id",
            sa.Text(),
            nullable=False,
            comment="The agency bank_id (the deploying entity in AGENCY_SB_RELAY mode)",
        ),
        sa.Column(
            "sb_bank_id",
            sa.Text(),
            nullable=False,
            comment="The Sponsor Bank's bank_id — the NGCH member",
        ),
        sa.Column("sb_name", sa.Text(), nullable=False),
        sa.Column(
            "connector_type",
            sa.Text(),
            nullable=False,
            comment="SFTP_GENERIC | BANCS_API | NELITO_API",
        ),
        sa.Column(
            "endpoint_ref",
            sa.Text(),
            nullable=False,
            comment="Masked reference — actual URL and credentials in Vault at secret/astra/{agency_id}/sb/{sb_bank_id}/",
        ),
        sa.Column(
            "submission_buffer_minutes",
            sa.Integer(),
            nullable=False,
            server_default="30",
            comment="Submit to SB this many minutes before NPCI cut-off (SB processes + re-files)",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("last_tested_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_test_latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
        sa.PrimaryKeyConstraint("sb_connection_id"),
        schema="cts",
    )

    # One connection per agency → SB pair
    op.create_index(
        "uq_sb_connections_agency_sb",
        "sb_connections",
        ["agency_id", "sb_bank_id"],
        unique=True,
        schema="cts",
    )

    # Fast lookup: all SB connections for an agency (CC startup load)
    op.create_index(
        "ix_sb_connections_agency_id",
        "sb_connections",
        ["agency_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_sb_connections_agency_id", table_name="sb_connections", schema="cts")
    op.drop_index("uq_sb_connections_agency_sb", table_name="sb_connections", schema="cts")
    op.drop_table("sb_connections", schema="cts")
