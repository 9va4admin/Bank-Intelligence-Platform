"""add cts.mcp_connection_configs table

MCP connection configuration for SB CBS, SMB CBS, Signature Vault,
PPS Vault, and Cancelled Leaf micro-DBs.

Unique constraint: (bank_id, connection_type, smb_id) — implemented as
a functional unique index using COALESCE(smb_id, '') so NULL values
are treated as distinct-but-comparable for uniqueness purposes.

Revision ID: 20260701_add_mcp_connection_configs
Revises: <previous_revision>
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260701_add_mcp_connection_configs"
down_revision = None   # set to previous migration revision in real chain
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "mcp_connection_configs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "connection_type",
            sa.Text(),
            nullable=False,
            comment="SB_CBS | SMB_CBS | SIGNATURE_VAULT | PPS_VAULT | CANCELLED_LEAF",
        ),
        sa.Column("smb_id", sa.Text(), nullable=True, comment="Null for non-SMB connection types"),
        sa.Column("smb_name", sa.Text(), nullable=True),
        sa.Column("cbs_vendor", sa.Text(), nullable=True, comment="finacle | bancs | flexcube"),
        sa.Column(
            "endpoint_url_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="AES-256 encrypted via bank PII cipher — never stored plaintext",
        ),
        sa.Column(
            "vault_secret_ref",
            sa.Text(),
            nullable=True,
            comment="Vault path: secret/astra/{bank_id}/...",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="PENDING",
            comment="PENDING | ACTIVE | ERROR | UNCONFIGURED",
        ),
        sa.Column("last_tested_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_test_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_sync_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("vault_record_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="cts",
    )

    # Functional unique index: one row per (bank_id, connection_type, smb_id)
    # COALESCE so that NULL smb_id is treated as '' (not as "unlimited NULLs")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_mcp_connection_configs_bank_type_smb
        ON cts.mcp_connection_configs (bank_id, connection_type, COALESCE(smb_id, ''))
        """
    )

    # Fast lookup by bank + status (pre-flight gate query)
    op.create_index(
        "ix_mcp_connection_configs_bank_status",
        "mcp_connection_configs",
        ["bank_id", "status"],
        schema="cts",
    )

    # Fast lookup by bank + SMB (SMB admin scoped list)
    op.create_index(
        "ix_mcp_connection_configs_bank_smb",
        "mcp_connection_configs",
        ["bank_id", "smb_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_connection_configs_bank_smb", table_name="mcp_connection_configs", schema="cts")
    op.drop_index("ix_mcp_connection_configs_bank_status", table_name="mcp_connection_configs", schema="cts")
    op.execute("DROP INDEX IF EXISTS cts.uq_mcp_connection_configs_bank_type_smb")
    op.drop_table("mcp_connection_configs", schema="cts")
