"""Sub-member bank registry, MICR prefix routing table, batch ledgers,
and principal_tag column on cheque_instruments.

Revision ID: 20260619_013
Revises: 20260618_012
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = "20260619_013"
down_revision = "20260618_012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sub_member_banks ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cts.sub_member_banks (
            sub_member_id           TEXT            PRIMARY KEY,
            bank_id                 TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            bank_name               TEXT            NOT NULL,
            sponsor_bank_id         TEXT            NOT NULL,
            micr_prefix             VARCHAR(6)      NOT NULL,
            ifsc_prefix             VARCHAR(11)     NOT NULL,

            -- PII: email addresses stored pgcrypto-encrypted
            branch_manager_email_enc  BYTEA         NOT NULL,
            ops_head_email_enc        BYTEA         NOT NULL,
            gm_email_enc              BYTEA         NOT NULL,

            return_rate_threshold   NUMERIC(5,4)    NOT NULL DEFAULT 0.1500,
            soft_hold_threshold     NUMERIC(5,4)    NOT NULL DEFAULT 0.2500,
            is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

            CONSTRAINT smb_return_threshold_range CHECK (return_rate_threshold BETWEEN 0 AND 1),
            CONSTRAINT smb_soft_hold_range CHECK (soft_hold_threshold BETWEEN 0 AND 1),
            CONSTRAINT smb_threshold_order CHECK (soft_hold_threshold > return_rate_threshold)
        )
    """)

    op.execute("""
        CREATE INDEX idx_sub_member_banks_bank_id
            ON cts.sub_member_banks (bank_id)
    """)

    op.execute("""
        CREATE INDEX idx_sub_member_banks_micr_prefix
            ON cts.sub_member_banks (micr_prefix)
    """)

    # ── micr_prefix_routing ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cts.micr_prefix_routing (
            prefix_id       UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            bank_id         TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            micr_prefix     VARCHAR(6)      NOT NULL,
            sub_member_id   TEXT            NOT NULL REFERENCES cts.sub_member_banks(sub_member_id),
            effective_from  DATE            NOT NULL DEFAULT CURRENT_DATE,
            effective_to    DATE,
            created_by      TEXT            NOT NULL,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

            CONSTRAINT micr_routing_unique_prefix_per_bank
                UNIQUE (bank_id, micr_prefix, effective_from),
            CONSTRAINT micr_routing_date_order
                CHECK (effective_to IS NULL OR effective_to > effective_from)
        )
    """)

    op.execute("""
        CREATE INDEX idx_micr_prefix_routing_lookup
            ON cts.micr_prefix_routing (bank_id, micr_prefix, effective_from)
    """)

    # ── sub_member_batch_ledgers ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cts.sub_member_batch_ledgers (
            ledger_id               UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            bank_id                 TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            sub_member_id           TEXT            NOT NULL REFERENCES cts.sub_member_banks(sub_member_id),
            session_date            DATE            NOT NULL,
            clearing_session        TEXT            NOT NULL,

            total_received          INTEGER         NOT NULL DEFAULT 0,
            stp_pass                INTEGER         NOT NULL DEFAULT 0,
            stp_return              INTEGER         NOT NULL DEFAULT 0,
            eyeball                 INTEGER         NOT NULL DEFAULT 0,
            fraud_hold              INTEGER         NOT NULL DEFAULT 0,
            iet_emergency           INTEGER         NOT NULL DEFAULT 0,

            soft_hold_active        BOOLEAN         NOT NULL DEFAULT FALSE,
            risk_event_emitted      BOOLEAN         NOT NULL DEFAULT FALSE,
            tier2_notification_sent BOOLEAN         NOT NULL DEFAULT FALSE,

            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

            CONSTRAINT smb_ledger_unique_session
                UNIQUE (bank_id, sub_member_id, session_date, clearing_session),
            CONSTRAINT smb_ledger_bucket_totals
                CHECK (stp_pass + stp_return + eyeball + fraud_hold + iet_emergency <= total_received),
            CONSTRAINT smb_ledger_valid_session
                CHECK (clearing_session IN ('MORNING', 'AFTERNOON', 'SPECIAL'))
        )
    """)

    op.execute("""
        CREATE INDEX idx_smb_ledger_lookup
            ON cts.sub_member_batch_ledgers (bank_id, sub_member_id, session_date)
    """)

    # ── alter cheque_instruments: add principal_tag + sub_member_id ──────────
    op.execute("""
        ALTER TABLE cts.cheque_instruments
            ADD COLUMN IF NOT EXISTS principal_tag  TEXT NOT NULL DEFAULT 'DIRECT'
                CONSTRAINT ci_principal_tag_values CHECK (principal_tag IN ('DIRECT', 'SUB_MEMBER')),
            ADD COLUMN IF NOT EXISTS sub_member_id  TEXT
                REFERENCES cts.sub_member_banks(sub_member_id)
    """)

    op.execute("""
        CREATE INDEX idx_ci_principal_tag
            ON cts.cheque_instruments (bank_id, principal_tag)
            WHERE principal_tag = 'SUB_MEMBER'
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE cts.cheque_instruments
            DROP COLUMN IF EXISTS sub_member_id,
            DROP COLUMN IF EXISTS principal_tag
    """)
    op.execute("DROP TABLE IF EXISTS cts.sub_member_batch_ledgers")
    op.execute("DROP TABLE IF EXISTS cts.micr_prefix_routing")
    op.execute("DROP TABLE IF EXISTS cts.sub_member_banks")
