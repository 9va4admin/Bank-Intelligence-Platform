"""SMB forwarding log table and per-SMB vault config.

Tracks every cheque forwarded from a Sponsor Bank to a Sub-Member Bank's
vault namespace, and stores SMB-specific vault configuration (key prefixes,
sync schedules, custom thresholds).

Revision ID: 20260626_014
Revises: 20260619_013
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = "20260626_014"
down_revision = "20260619_013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── smb_forwarding_log ────────────────────────────────────────────────────
    # Every cheque that arrives at a Sponsor Bank and is identified as belonging
    # to a Sub-Member is written here. Provides full audit trail of the sponsor
    # routing hop: inward arrival → SMB identification → forwarded to SMB workflow.
    op.execute("""
        CREATE TABLE cts.smb_forwarding_log (
            forwarding_id           UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            bank_id                 TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            sponsor_bank_id         TEXT            NOT NULL,
            sub_member_id           TEXT            NOT NULL REFERENCES cts.sub_member_banks(sub_member_id),
            instrument_id           TEXT            NOT NULL,

            -- MICR routing decision
            micr_prefix_matched     VARCHAR(6)      NOT NULL,
            routing_confidence      NUMERIC(5,4)    NOT NULL DEFAULT 1.0,

            -- Forwarding state machine
            -- RECEIVED: arrived at sponsor, identified as SMB instrument
            -- FORWARDING: SMBForwardingWorkflow started
            -- FORWARDED: SMBChequeProcessingWorkflow accepted
            -- COMPLETED: terminal decision filed to NGCH by SMB workflow
            -- FAILED: forwarding failed (IET risk too high to retry safely)
            forwarding_status       TEXT            NOT NULL DEFAULT 'RECEIVED'
                CONSTRAINT flog_status_values CHECK (
                    forwarding_status IN ('RECEIVED','FORWARDING','FORWARDED','COMPLETED','FAILED')
                ),

            -- IET lifecycle timestamps
            iet_deadline_utc        TIMESTAMPTZ     NOT NULL,
            received_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            forwarded_at            TIMESTAMPTZ,
            completed_at            TIMESTAMPTZ,
            failed_at               TIMESTAMPTZ,

            -- SMB workflow reference (filled once FORWARDED state reached)
            smb_workflow_id         TEXT,
            smb_temporal_run_id     TEXT,

            -- Terminal decision from SMB side (filled on COMPLETED)
            terminal_decision       TEXT
                CONSTRAINT flog_decision_values CHECK (
                    terminal_decision IS NULL OR
                    terminal_decision IN ('STP_CONFIRM','STP_RETURN','HUMAN_REVIEW','IET_EMERGENCY')
                ),

            failure_reason          TEXT,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX idx_smb_flog_instrument
            ON cts.smb_forwarding_log (bank_id, instrument_id)
    """)

    op.execute("""
        CREATE INDEX idx_smb_flog_sub_member_date
            ON cts.smb_forwarding_log (bank_id, sub_member_id, received_at DESC)
    """)

    op.execute("""
        CREATE INDEX idx_smb_flog_status
            ON cts.smb_forwarding_log (bank_id, forwarding_status)
            WHERE forwarding_status IN ('RECEIVED', 'FORWARDING')
    """)

    # ── smb_vault_config ──────────────────────────────────────────────────────
    # Per-SMB vault configuration. A Sub-Member's signature specimens and PPS
    # entries are stored in the Sponsor Bank's Redis vault but under a namespaced
    # key prefix so they stay logically isolated. This table records the vault
    # configuration and sync parameters for each SMB.
    op.execute("""
        CREATE TABLE cts.smb_vault_config (
            config_id               UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            bank_id                 TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            sub_member_id           TEXT            NOT NULL REFERENCES cts.sub_member_banks(sub_member_id),

            -- Redis key namespace prefix for this SMB's vault entries
            -- Format: sig:{smb_bank_id}:{hash} and pps:{smb_bank_id}:{hash}
            -- smb_vault_prefix is derived from sub_member_id but stored for auditability
            smb_vault_prefix        TEXT            NOT NULL,

            -- CBS connector type used to sync this SMB's specimens into sponsor vault
            cbs_connector_type      TEXT            NOT NULL DEFAULT 'finacle'
                CONSTRAINT smb_vault_cbs_values CHECK (
                    cbs_connector_type IN ('finacle','bancs','flexcube','manual_upload')
                ),

            -- Vault sync schedule (cron expression — default 6AM daily, same as sponsor)
            vault_sync_cron         TEXT            NOT NULL DEFAULT '0 6 * * *',

            -- Separate threshold overrides for SMB (can differ from sponsor bank defaults)
            -- NULL means use sponsor bank's threshold (Layer 3 config)
            ocr_min_confidence_override         NUMERIC(5,4),
            signature_min_score_override        NUMERIC(5,4),
            fraud_threshold_override            NUMERIC(5,4),

            last_vault_sync_at      TIMESTAMPTZ,
            last_sync_status        TEXT            DEFAULT 'NEVER_SYNCED'
                CONSTRAINT smb_vault_sync_status CHECK (
                    last_sync_status IN ('NEVER_SYNCED','SYNC_OK','SYNC_PARTIAL','SYNC_FAILED')
                ),
            signature_count         INTEGER         NOT NULL DEFAULT 0,
            pps_entry_count         INTEGER         NOT NULL DEFAULT 0,

            is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

            CONSTRAINT smb_vault_config_unique
                UNIQUE (bank_id, sub_member_id)
        )
    """)

    op.execute("""
        CREATE INDEX idx_smb_vault_config_lookup
            ON cts.smb_vault_config (bank_id, sub_member_id)
            WHERE is_active = TRUE
    """)

    # ── smb_kafka_topics ──────────────────────────────────────────────────────
    # Registry of per-SMB Kafka topic assignments. Topic names follow the
    # cts.smb.inward.{sb_id}.{smb_id} pattern established in CLAUDE.md.
    # This table is informational — actual topic creation is a Helm/Strimzi concern.
    op.execute("""
        CREATE TABLE cts.smb_kafka_topics (
            topic_id                UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            bank_id                 TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            sub_member_id           TEXT            NOT NULL REFERENCES cts.sub_member_banks(sub_member_id),

            inward_topic            TEXT            NOT NULL,
            decisions_topic         TEXT            NOT NULL,
            notifications_topic     TEXT            NOT NULL,

            -- KEDA ScaledObject name for this SMB's worker scaling
            keda_scaled_object_name TEXT            NOT NULL,

            is_provisioned          BOOLEAN         NOT NULL DEFAULT FALSE,
            provisioned_at          TIMESTAMPTZ,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

            CONSTRAINT smb_topics_unique UNIQUE (bank_id, sub_member_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.smb_kafka_topics")
    op.execute("DROP TABLE IF EXISTS cts.smb_vault_config")
    op.execute("DROP TABLE IF EXISTS cts.smb_forwarding_log")
