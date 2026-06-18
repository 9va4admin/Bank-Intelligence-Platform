"""EJ ingestion sessions and raw log files (monthly range-partitioned).

ej_ingestion_sessions — metadata for each pull from an ATM/branch MCP server
ej_raw_logs           — one row per raw EJ file (immutable after ingestion)

ej_raw_logs is range-partitioned by received_at (monthly) — same pattern as
cheque_instruments in the CTS schema. EJ log volumes are lower than cheques
but files are larger; partitioning ensures pruning and VACUUM efficiency.

Revision ID: 20260618_ej_002
Revises: 20260618_ej_001
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_ej_002"
down_revision = "20260618_ej_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ej_ingestion_sessions ──────────────────────────────────────────────
    # One row per pull from the branch MCP server (edge agent or ATM mgmt API).
    # Each session can fetch multiple EJ files from one or more ATMs.
    op.create_table(
        "ej_ingestion_sessions",
        sa.Column("session_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("branch_ifsc", sa.Text, nullable=True),   # NULL if fetching by zone
        sa.Column("zone", sa.Text, nullable=True),

        # Source type
        sa.Column("source_type", sa.Text, nullable=False),
        # EDGE_AGENT_MCP | ATM_MGMT_API | SFTP_PULL | MANUAL_UPLOAD

        sa.Column("triggered_by", sa.Text, nullable=False),
        # SCHEDULE | WEBHOOK | MANUAL | CBS_EVENT

        # Session outcome
        sa.Column("status", sa.Text, nullable=False, server_default="'RUNNING'"),
        # RUNNING | COMPLETE | PARTIAL | FAILED

        sa.Column("atm_count", sa.Integer, nullable=True),
        sa.Column("files_fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("files_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bytes_fetched", sa.BigInteger, nullable=False, server_default="0"),

        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_ingestion_sessions_bank_date",
                    "ej_ingestion_sessions", ["bank_id", "started_at"], schema="ej")
    op.create_index("ix_ej_ingestion_sessions_branch",
                    "ej_ingestion_sessions", ["branch_ifsc"],
                    postgresql_where=sa.text("branch_ifsc IS NOT NULL"), schema="ej")

    # ── ej_raw_logs (range-partitioned by received_at) ─────────────────────
    # Immutable after ingestion — no UPDATE ever on this table.
    # MinIO holds the actual file; this row holds metadata + hash.
    # Partitioned monthly for efficient VACUUM, ILM coordination, and partition pruning.
    op.execute("""
        CREATE TABLE ej.ej_raw_logs (
            log_id          UUID            NOT NULL DEFAULT uuid_generate_v4(),
            bank_id         TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            atm_id          TEXT            NOT NULL REFERENCES ej.atm_master(atm_id),
            session_id      UUID            REFERENCES ej.ej_ingestion_sessions(session_id),

            -- File identity
            raw_log_hash    TEXT            NOT NULL,   -- SHA-256 of file content
            file_name       TEXT,                       -- original filename from edge agent
            log_date        DATE,                       -- date of EJ activity (from filename/header)

            -- MinIO storage (ej/{bank_id}/{atm_id}/{raw_log_hash}.log)
            minio_key       TEXT            NOT NULL,
            file_size_bytes BIGINT,

            -- OEM fingerprint (detected by Go edge agent, validated by Python activity)
            oem_fingerprint TEXT            NOT NULL,
            -- NCR_SELFSERV | DIEBOLD_NIXDORF | WINCOR_NIXDORF | HYOSUNG | GRG_BANKING | UNKNOWN

            -- Processing status (EJNormalisationWorkflow updates this)
            status          TEXT            NOT NULL DEFAULT 'RECEIVED',
            -- RECEIVED | NORMALISING | NORMALISED | PARSE_FAILED | INVALID

            -- Workflow reference
            workflow_id     TEXT,           -- ej-normalise-{bank_id}-{raw_log_hash}

            received_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            processed_at    TIMESTAMPTZ,

            PRIMARY KEY (log_id, received_at)
        ) PARTITION BY RANGE (received_at)
    """)

    # First 3 monthly partitions
    op.execute("""
        CREATE TABLE ej.ej_raw_logs_2026_06
            PARTITION OF ej.ej_raw_logs
            FOR VALUES FROM ('2026-06-01') TO ('2026-07-01')
    """)
    op.execute("""
        CREATE TABLE ej.ej_raw_logs_2026_07
            PARTITION OF ej.ej_raw_logs
            FOR VALUES FROM ('2026-07-01') TO ('2026-08-01')
    """)
    op.execute("""
        CREATE TABLE ej.ej_raw_logs_2026_08
            PARTITION OF ej.ej_raw_logs
            FOR VALUES FROM ('2026-08-01') TO ('2026-09-01')
    """)

    op.create_index("ix_ej_raw_logs_bank_received",
                    "ej_raw_logs", ["bank_id", "received_at"], schema="ej")
    op.create_index("ix_ej_raw_logs_atm_id",
                    "ej_raw_logs", ["atm_id"], schema="ej")
    op.create_index("ix_ej_raw_logs_hash",
                    "ej_raw_logs", ["raw_log_hash"], unique=True, schema="ej")
    op.create_index("ix_ej_raw_logs_status",
                    "ej_raw_logs", ["bank_id", "status"],
                    postgresql_where=sa.text("status IN ('RECEIVED', 'NORMALISING', 'PARSE_FAILED')"),
                    schema="ej")
    op.create_index("ix_ej_raw_logs_workflow",
                    "ej_raw_logs", ["workflow_id"],
                    postgresql_where=sa.text("workflow_id IS NOT NULL"), schema="ej")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ej.ej_raw_logs CASCADE")
    op.drop_table("ej_ingestion_sessions", schema="ej")
