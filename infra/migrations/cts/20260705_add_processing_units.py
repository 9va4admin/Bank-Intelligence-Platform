"""add cts.processing_units table

Processing Unit (PU) — the clearing-zone level grouping. Each PU is associated
with one NGCH grid zone and runs its own KEDA-scaled Temporal task queue
(cts-processing-{bank_id}-{pu_id}). Branches are mapped administratively to a PU;
the mapping is not geographic (a Pune branch can map to the MUMBAI PU if the bank
configured it that way).

A bank always has at least one PU. Large banks may have one PU per clearing zone
(MUMBAI, DELHI, CHENNAI, KOLKATA, etc.).

Revision ID: 20260705_add_processing_units
Revises: 20260701_add_mcp_connection_configs
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_add_processing_units"
down_revision = "20260701_add_mcp_connection_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "processing_units",
        sa.Column("pu_id", sa.Text(), nullable=False, comment="PU identifier — e.g. MUMBAI-PU-01"),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("pu_name", sa.Text(), nullable=False, comment="Human-readable name for Admin UI"),
        sa.Column(
            "clearing_zone",
            sa.Text(),
            nullable=False,
            comment="NGCH clearing zone: MUMBAI | DELHI | CHENNAI | KOLKATA | HYDERABAD | AHMEDABAD",
        ),
        sa.Column(
            "ngch_participant_code",
            sa.Text(),
            nullable=False,
            comment="NGCH participant code for this PU — used in NGCH file headers",
        ),
        sa.Column(
            "temporal_task_queue",
            sa.Text(),
            nullable=False,
            comment="Computed: cts-processing-{bank_id}-{pu_id} — stored for fast worker lookup",
        ),
        sa.Column(
            "kafka_inward_topic",
            sa.Text(),
            nullable=False,
            comment="Computed: cts.inward.{bank_id}.{pu_id}",
        ),
        sa.Column(
            "max_agent_swarm_size",
            sa.Integer(),
            nullable=False,
            server_default="200",
            comment="KEDA max replicas for this PU — overrides bank-level default if set",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Inactive PUs accept no new instruments — used for decommissioning",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
        sa.PrimaryKeyConstraint("pu_id"),
        schema="cts",
    )

    # A bank cannot have two PUs with the same clearing zone (one PU per zone per bank)
    op.create_index(
        "uq_processing_units_bank_zone",
        "processing_units",
        ["bank_id", "clearing_zone"],
        unique=True,
        schema="cts",
    )

    # Fast lookup: all PUs for a bank
    op.create_index(
        "ix_processing_units_bank_id",
        "processing_units",
        ["bank_id"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_processing_units_bank_id", table_name="processing_units", schema="cts")
    op.drop_index("uq_processing_units_bank_zone", table_name="processing_units", schema="cts")
    op.drop_table("processing_units", schema="cts")
