"""EJ schema + ATM master tables: atm_master, atm_oem_profiles.

Revision ID: 20260618_ej_001
Revises: (base)
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_ej_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create EJ schema ───────────────────────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS ej")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # pgvector for BGE-M3 embeddings (1024-dim) used in dispute matching
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── atm_master ─────────────────────────────────────────────────────────
    # One row per ATM deployed by the bank.
    # ATM ID is the bank's own identifier (typically from ATM management system).
    op.create_table(
        "atm_master",
        sa.Column("atm_id", sa.Text, primary_key=True),
        # Bank-assigned ATM ID (e.g. "ATM-MUM-0042") — NOT a UUID for query clarity
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        # FK to platform.banks — shared bank registry (platform schema is always deployed)

        sa.Column("atm_name", sa.Text, nullable=True),      # branch/location label
        sa.Column("branch_ifsc", sa.Text, nullable=True),   # branch where ATM is installed
        sa.Column("city", sa.Text, nullable=True),
        sa.Column("state", sa.Text, nullable=True),
        sa.Column("zone", sa.Text, nullable=True),           # bank's geographic zone

        # OEM information (set on onboarding; fingerprint validates at ingest)
        sa.Column("oem", sa.Text, nullable=True),
        # NCR_SELFSERV | DIEBOLD_NIXDORF | WINCOR_NIXDORF | HYOSUNG | GRG_BANKING | UNKNOWN

        sa.Column("model", sa.Text, nullable=True),          # e.g. "NCR SelfServ 84"
        sa.Column("firmware_version", sa.Text, nullable=True),
        sa.Column("software_version", sa.Text, nullable=True),

        # Connectivity (edge agent deployment)
        sa.Column("edge_agent_installed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("edge_agent_version", sa.Text, nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),

        # ATM health status (updated by ATMHealthWorkflow)
        sa.Column("health_status", sa.Text, nullable=False, server_default="'UNKNOWN'"),
        # HEALTHY | DEGRADED | CRITICAL | OFFLINE | UNKNOWN
        sa.Column("health_updated_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("commissioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decommissioned_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_atm_master_bank_id",
                    "atm_master", ["bank_id"], schema="ej")
    op.create_index("ix_ej_atm_master_bank_health",
                    "atm_master", ["bank_id", "health_status"],
                    postgresql_where=sa.text("is_active = true"), schema="ej")
    op.create_index("ix_ej_atm_master_branch_ifsc",
                    "atm_master", ["branch_ifsc"],
                    postgresql_where=sa.text("branch_ifsc IS NOT NULL"), schema="ej")

    # ── atm_oem_profiles ───────────────────────────────────────────────────
    # OEM fingerprint signatures used by the Go edge agent and Python validator.
    # The Go edge agent detects OEM at the source and sends the fingerprint label.
    # The Python fingerprint activity validates the received label against this table.
    # Banks add new OEM profiles here when deploying new ATM models.
    op.create_table(
        "atm_oem_profiles",
        sa.Column("profile_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("oem", sa.Text, nullable=False),
        # NCR_SELFSERV | DIEBOLD_NIXDORF | WINCOR_NIXDORF | HYOSUNG | GRG_BANKING

        sa.Column("model_pattern", sa.Text, nullable=False),
        # Regex or substring pattern matched against EJ header line

        sa.Column("software_version_pattern", sa.Text, nullable=True),
        # Optional version constraint (e.g. "NDC+" matches only NDC+ software)

        # EJ format characteristics for this OEM+model combination
        sa.Column("ej_format", JSONB, nullable=False),
        # {
        #   "line_delimiter": "\n",
        #   "transaction_start_marker": "***",
        #   "date_format": "DDMMYYYY",
        #   "amount_field": "AMOUNT",
        #   "currency_position": "prefix",
        #   "encoding": "ASCII"
        # }

        # Canonical field mapping (how to extract canonical fields from this OEM's EJ)
        sa.Column("field_mapping", JSONB, nullable=False),
        # {
        #   "transaction_type": {"path": "line[3].split(':')[1]", "type": "text"},
        #   "amount": {"path": "line[5].split('=')[1].strip()", "type": "paise"},
        #   "timestamp": {"path": "line[0][4:20]", "format": "DDMMYYYY HHMMSS"}
        # }

        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_oem_profiles_oem",
                    "atm_oem_profiles", ["oem"],
                    postgresql_where=sa.text("is_active = true"), schema="ej")


def downgrade() -> None:
    op.drop_table("atm_oem_profiles", schema="ej")
    op.drop_table("atm_master", schema="ej")
    op.execute("DROP SCHEMA IF EXISTS ej CASCADE")
