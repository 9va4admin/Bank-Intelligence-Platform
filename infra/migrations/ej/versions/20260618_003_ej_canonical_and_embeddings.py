"""EJ canonical records, embeddings, and field extraction audit.

ej_canonical_records     — normalised per-transaction records (LLM output)
ej_embeddings            — BGE-M3 vector(1024) for dispute semantic matching
ej_field_extraction_audit — per-field confidence scores and extraction provenance

Revision ID: 20260618_ej_003
Revises: 20260618_ej_002
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_ej_003"
down_revision = "20260618_ej_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ej_canonical_records ───────────────────────────────────────────────
    # One row per transaction extracted from an EJ log file.
    # A single raw log file can yield many canonical records (one per transaction).
    # Immutable once written (raw log is immutable; canonical is its derived form).
    op.create_table(
        "ej_canonical_records",
        sa.Column("record_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, nullable=False),
        sa.Column("atm_id", sa.Text,
                  sa.ForeignKey("ej.atm_master.atm_id"), nullable=False),
        sa.Column("log_id", UUID(as_uuid=True), nullable=False),
        # FK to ej_raw_logs not enforced (partitioned table — FK across partitions
        # not supported in YugabyteDB without explicit partition FK; managed by app)

        # Canonical identity
        sa.Column("canonical_hash", sa.Text, nullable=False, unique=True),
        # SHA-256 of JSON-serialised canonical record (sort_keys=True)

        # Workflow reference
        sa.Column("workflow_id", sa.Text, nullable=True),

        # Transaction classification
        sa.Column("transaction_type", sa.Text, nullable=False),
        # CASH_DISPENSED | BALANCE_INQUIRY | TRANSFER | DEPOSIT | FAILED_DISPENSE |
        # CARD_RETAINED | PARTIAL_DISPENSE | REVERSAL | SESSION_START | SESSION_END

        sa.Column("transaction_status", sa.Text, nullable=False),
        # SUCCESS | FAILED | TIMEOUT | REVERSED | PARTIAL

        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        # Transaction timestamp from EJ (normalised to UTC)

        # Transaction amounts (structured — not raw text from EJ)
        sa.Column("requested_amount_paise", sa.BigInteger, nullable=True),
        sa.Column("dispensed_amount_paise", sa.BigInteger, nullable=True),
        sa.Column("discrepancy_amount_paise", sa.BigInteger, nullable=True),
        # Non-zero if dispense != request (key dispute signal)

        # Card and channel (partial data — no full card number ever)
        sa.Column("card_last4", sa.String(4), nullable=True),
        sa.Column("card_type", sa.Text, nullable=True),   # VISA | MASTERCARD | RUPAY | UNKNOWN
        sa.Column("acquiring_bank_code", sa.Text, nullable=True),

        # ATM components state at transaction time
        sa.Column("cassette_states", JSONB, nullable=True),
        # {"cassette_1": {"denomination": 500, "count": 40, "status": "OK"}, ...}
        sa.Column("dispenser_status", sa.Text, nullable=True),
        # OK | JAM | PARTIAL | RETRACT | ERROR

        # Extraction quality
        sa.Column("extraction_confidence", sa.Numeric(5, 4), nullable=True),
        # Overall confidence score from LLM parser
        sa.Column("low_confidence_fields", JSONB, nullable=True),
        # List of field names with confidence below threshold

        # OEM that produced this record
        sa.Column("oem_fingerprint", sa.Text, nullable=False),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_canonical_bank_atm_time",
                    "ej_canonical_records", ["bank_id", "atm_id", "timestamp"], schema="ej")
    op.create_index("ix_ej_canonical_hash",
                    "ej_canonical_records", ["canonical_hash"], unique=True, schema="ej")
    op.create_index("ix_ej_canonical_log_id",
                    "ej_canonical_records", ["log_id"], schema="ej")
    op.create_index("ix_ej_canonical_tx_type_status",
                    "ej_canonical_records", ["bank_id", "transaction_type", "transaction_status"],
                    schema="ej")
    op.create_index("ix_ej_canonical_discrepancy",
                    "ej_canonical_records", ["bank_id", "atm_id"],
                    postgresql_where=sa.text(
                        "discrepancy_amount_paise IS NOT NULL AND discrepancy_amount_paise != 0"
                    ), schema="ej")

    # ── ej_embeddings ──────────────────────────────────────────────────────
    # BGE-M3 vector embeddings for each canonical record.
    # Used by DisputeResolutionWorkflow for semantic similarity matching.
    # vector(1024) — BGE-M3 output dimension.
    # pgvector extension (CREATE EXTENSION vector) loaded in migration _001.
    op.execute("""
        CREATE TABLE ej.ej_embeddings (
            embedding_id    UUID            NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
            record_id       UUID            NOT NULL REFERENCES ej.ej_canonical_records(record_id),
            bank_id         TEXT            NOT NULL,
            atm_id          TEXT            NOT NULL,

            -- BGE-M3 1024-dim embedding of the canonical record JSON
            embedding       vector(1024)    NOT NULL,

            -- Model version that produced this embedding (for drift detection)
            model_version   TEXT            NOT NULL DEFAULT 'bge-m3-v1',

            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)
    # IVFFlat index for approximate nearest-neighbor search
    # lists=100 is appropriate for ~1M vectors; tune when volume grows
    op.execute("""
        CREATE INDEX ix_ej_embeddings_ivfflat
        ON ej.ej_embeddings
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
    op.create_index("ix_ej_embeddings_record",
                    "ej_embeddings", ["record_id"], schema="ej")
    op.create_index("ix_ej_embeddings_bank_atm",
                    "ej_embeddings", ["bank_id", "atm_id"], schema="ej")

    # ── ej_field_extraction_audit ──────────────────────────────────────────
    # Per-field confidence scores from LLM extraction.
    # Enables analysis of which fields the LLM consistently struggles with
    # per OEM — used to tune prompts and identify OEM-specific edge cases.
    op.create_table(
        "ej_field_extraction_audit",
        sa.Column("audit_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("record_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.ej_canonical_records.record_id"), nullable=False),
        sa.Column("bank_id", sa.Text, nullable=False),
        sa.Column("oem_fingerprint", sa.Text, nullable=False),

        # Per-field extraction detail
        sa.Column("field_name", sa.Text, nullable=False),
        # transaction_type | transaction_status | timestamp | requested_amount |
        # dispensed_amount | card_type | dispenser_status | cassette_1 ...

        sa.Column("extracted_raw", sa.Text, nullable=True),
        # Raw extracted text before type coercion — helps debug parsing errors
        # Never contains card numbers, amounts > ₹1000 logged as range

        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("extraction_method", sa.Text, nullable=True),
        # LLM_PARSE | REGEX_FALLBACK | OEM_FIELD_MAP

        sa.Column("was_low_confidence", sa.Boolean, nullable=False, server_default="false"),
        # True if confidence < min_confidence threshold at extraction time

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_field_extraction_record",
                    "ej_field_extraction_audit", ["record_id"], schema="ej")
    op.create_index("ix_ej_field_extraction_oem_field",
                    "ej_field_extraction_audit", ["oem_fingerprint", "field_name",
                                                   "was_low_confidence"], schema="ej")


def downgrade() -> None:
    op.drop_table("ej_field_extraction_audit", schema="ej")
    op.execute("DROP TABLE IF EXISTS ej.ej_embeddings")
    op.drop_table("ej_canonical_records", schema="ej")
