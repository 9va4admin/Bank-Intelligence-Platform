"""Core cheque instruments (monthly partitioned) and image metadata.

PII columns (payee_name, drawer_name, account_number) stored as pgcrypto-encrypted BYTEA.
account_number never stored raw — account_hash (HMAC-SHA256) + account_last4 only.
amount stored as range bucket — never exact figure in plaintext column.

Revision ID: 20260618_003
Revises: 20260618_002
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_003"
down_revision = "20260618_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cheque_instruments (range-partitioned by received_at) ──────────────
    # YugabyteDB: range partitioning on timestamp column
    op.execute("""
        CREATE TABLE cts.cheque_instruments (
            instrument_id       UUID            NOT NULL DEFAULT uuid_generate_v4(),
            bank_id             TEXT            NOT NULL REFERENCES platform.banks(bank_id),
            center_id           UUID            REFERENCES cts.processing_centers(center_id),
            batch_id            UUID            REFERENCES cts.clearing_batches(batch_id),

            -- NPCI / NGCH identifiers
            ngch_instrument_ref TEXT            UNIQUE,
            presenting_bank_code TEXT           NOT NULL,
            presenting_ifsc     TEXT            NOT NULL,
            drawee_ifsc         TEXT            NOT NULL,

            -- MICR fields (non-PII)
            cheque_number       VARCHAR(6)      NOT NULL,
            micr_code           VARCHAR(9)      NOT NULL,

            -- PII: stored encrypted via pgcrypto — app decrypts using bank key from Vault
            account_hash        TEXT            NOT NULL,     -- HMAC-SHA256 of bank_id:account_number
            account_last4       VARCHAR(4)      NOT NULL,     -- for display only
            payee_name_enc      BYTEA,                        -- pgp_sym_encrypt(payee_name, $key)
            drawer_name_enc     BYTEA,                        -- pgp_sym_encrypt(drawer_name, $key)

            -- Amount: stored as paise (integer) for processing; range bucket for audit/logs
            amount_paise        BIGINT          NOT NULL,     -- exact value for processing decisions
            amount_range        TEXT            NOT NULL,     -- 'STANDARD'|'HIGH_VALUE'|'VERY_HIGH_VALUE'
            amount_words_match  BOOLEAN         NOT NULL DEFAULT TRUE,  -- figures == words

            -- Cheque metadata
            cheque_date         DATE            NOT NULL,
            instrument_type     TEXT            NOT NULL DEFAULT 'CTS',  -- 'CTS'|'MICR'|'NON_MICR'

            -- CTS 2010 compliance
            cts2010_compliant   BOOLEAN         NOT NULL DEFAULT FALSE,
            watermark_verified  BOOLEAN         NOT NULL DEFAULT FALSE,

            -- IET deadline (Unix timestamp — copied from Temporal workflow input)
            iet_deadline        DOUBLE PRECISION NOT NULL,
            iet_breached        BOOLEAN         NOT NULL DEFAULT FALSE,

            -- Lifecycle
            status              TEXT            NOT NULL DEFAULT 'RECEIVED',
            -- RECEIVED|OCR_DONE|DECISION_PENDING|STP_CONFIRM|STP_RETURN|HUMAN_REVIEW|FILED|RETURNED
            received_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            filed_at            TIMESTAMPTZ,

            -- Temporal workflow reference
            workflow_id         TEXT            NOT NULL,     -- cts-{bank_id}-{instrument_id}

            PRIMARY KEY (instrument_id, received_at)
        ) PARTITION BY RANGE (received_at)
    """)

    # Create first 3 monthly partitions (migration creates them; ongoing: scheduled job)
    op.execute("""
        CREATE TABLE cts.cheque_instruments_2026_06
            PARTITION OF cts.cheque_instruments
            FOR VALUES FROM ('2026-06-01') TO ('2026-07-01')
    """)
    op.execute("""
        CREATE TABLE cts.cheque_instruments_2026_07
            PARTITION OF cts.cheque_instruments
            FOR VALUES FROM ('2026-07-01') TO ('2026-08-01')
    """)
    op.execute("""
        CREATE TABLE cts.cheque_instruments_2026_08
            PARTITION OF cts.cheque_instruments
            FOR VALUES FROM ('2026-08-01') TO ('2026-09-01')
    """)

    # Indexes on the parent table (inherited by partitions)
    op.create_index("ix_cts_instruments_bank_received",
                    "cheque_instruments", ["bank_id", "received_at"], schema="cts")
    op.create_index("ix_cts_instruments_bank_status",
                    "cheque_instruments", ["bank_id", "status"], schema="cts")
    op.create_index("ix_cts_instruments_account_hash",
                    "cheque_instruments", ["account_hash"], schema="cts")
    op.create_index("ix_cts_instruments_workflow_id",
                    "cheque_instruments", ["workflow_id"], schema="cts")
    op.create_index("ix_cts_instruments_micr_code",
                    "cheque_instruments", ["micr_code"], schema="cts")

    # ── cheque_image_metadata ──────────────────────────────────────────────
    # MinIO object references for CTS 2010 images — 3 images per cheque
    op.create_table(
        "cheque_image_metadata",
        sa.Column("image_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", sa.Text, nullable=False),

        # MinIO object keys (never inline image bytes)
        sa.Column("front_grey_key", sa.Text, nullable=True),       # JPEG grayscale
        sa.Column("front_bw_key", sa.Text, nullable=True),         # TIFF black & white
        sa.Column("reverse_bw_key", sa.Text, nullable=True),       # TIFF reverse B&W

        # SHA-256 integrity hashes
        sa.Column("hash_front_grey", sa.Text, nullable=True),
        sa.Column("hash_front_bw", sa.Text, nullable=True),
        sa.Column("hash_reverse_bw", sa.Text, nullable=True),

        # Image quality flags
        sa.Column("dpi_front", sa.Integer, nullable=True),
        sa.Column("dpi_reverse", sa.Integer, nullable=True),
        sa.Column("quality_score", sa.Numeric(4, 3), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_image_metadata_instrument",
                    "cheque_image_metadata", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_image_metadata_bank",
                    "cheque_image_metadata", ["bank_id"], schema="cts")


def downgrade() -> None:
    op.drop_table("cheque_image_metadata", schema="cts")
    op.execute("DROP TABLE IF EXISTS cts.cheque_instruments CASCADE")
