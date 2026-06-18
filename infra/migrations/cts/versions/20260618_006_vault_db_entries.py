"""DB-side vault entries: signature_vault_entries and pps_vault_entries.

Redis holds the hot cache. These YugabyteDB tables are the source of truth
that VaultSyncWorkflow reads from CBS and uses to warm Redis.

Rationale for keeping DB copies:
  - Redis is ephemeral — vault_sync_workflow repopulates from here on Redis failure
  - Audit trail: when was each signature loaded, from which CBS version
  - Regulatory: RBI requires audit of all specimen signatures used in verification

PII handling:
  - No raw account numbers — account_hash (HMAC-SHA256) + account_last4 only
  - Signature vectors stored as BYTEA (model output — not directly PII but sensitive)
  - Signature images referenced by MinIO key (encrypted at rest via SSE-KMS)

Revision ID: 20260618_006
Revises: 20260618_005
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_006"
down_revision = "20260618_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── signature_vault_entries ────────────────────────────────────────────
    # One row per account's current signature record.
    # VaultSyncWorkflow loads from CBS and upserts here; then warms Redis.
    op.create_table(
        "signature_vault_entries",
        sa.Column("entry_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),

        # Account identified by hash — never raw account number
        sa.Column("account_hash", sa.Text, nullable=False),  # HMAC-SHA256(bank_id:account_number)
        sa.Column("account_last4", sa.String(4), nullable=False),  # display only

        # Siamese network feature vector (serialised as BYTEA)
        # Length depends on model version — typically 512-dim float32 = 2048 bytes
        sa.Column("signature_vector", sa.LargeBinary, nullable=True),
        sa.Column("vector_model_version", sa.Text, nullable=True),  # which model generated the vector

        # MinIO reference to specimen signature image (encrypted at rest)
        sa.Column("specimen_image_key", sa.Text, nullable=True),
        sa.Column("specimen_image_hash", sa.Text, nullable=True),  # SHA-256 of original image

        # CBS metadata
        sa.Column("cbs_account_status", sa.Text, nullable=True),
        # ACTIVE | DORMANT | FROZEN | CLOSED
        sa.Column("cbs_sync_version", sa.Text, nullable=True),   # CBS record version / ETag

        # Validity
        sa.Column("valid_from", sa.Date, nullable=True),
        sa.Column("valid_until", sa.Date, nullable=True),  # NULL = indefinite
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),

        # Sync tracking
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("synced_by_workflow", sa.Text, nullable=True),  # VaultSyncWorkflow ID

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    # Unique constraint: one active record per account per bank
    op.create_index("ix_cts_sig_vault_bank_account",
                    "signature_vault_entries", ["bank_id", "account_hash"],
                    unique=True,
                    postgresql_where=sa.text("is_active = true"),
                    schema="cts")
    op.create_index("ix_cts_sig_vault_account_hash",
                    "signature_vault_entries", ["account_hash"], schema="cts")
    op.create_index("ix_cts_sig_vault_last_synced",
                    "signature_vault_entries", ["bank_id", "last_synced_at"], schema="cts")

    # ── pps_vault_entries ──────────────────────────────────────────────────
    # Positive Pay System registrations for cheques >= ₹5 lakh.
    # RBI mandated from Jan 2021; disputes not accepted if PPS not used.
    # One row per registered cheque series entry.
    op.create_table(
        "pps_vault_entries",
        sa.Column("entry_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),

        # Account identified by hash — never raw
        sa.Column("account_hash", sa.Text, nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=False),

        # PPS registration details
        sa.Column("cheque_number", sa.String(6), nullable=False),
        sa.Column("cheque_date", sa.Date, nullable=False),

        # Amount stored as range + paise (paise for exact matching, range for audit)
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("amount_range", sa.Text, nullable=False),
        # STANDARD (< ₹5L) | HIGH_VALUE (₹5L–₹50L) | VERY_HIGH_VALUE (> ₹50L)

        # Payee — encrypted (needed for PPS match verification)
        sa.Column("payee_name_enc", sa.LargeBinary, nullable=True),  # pgp_sym_encrypt

        # PPS lifecycle
        sa.Column("status", sa.Text, nullable=False, server_default="'REGISTERED'"),
        # REGISTERED | CONFIRMED_PAID | EXPIRED | CANCELLED
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.Date, nullable=False),   # cheque date + 3 months typically
        sa.Column("confirmed_paid_at", sa.DateTime(timezone=True), nullable=True),

        # CBS/channel reference
        sa.Column("registration_channel", sa.Text, nullable=True),
        # INTERNET_BANKING | MOBILE | BRANCH | CBS_BATCH
        sa.Column("cbs_pps_ref", sa.Text, nullable=True),  # CBS-assigned reference

        # Sync tracking
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    # Unique: one PPS registration per cheque number per account
    op.create_index("ix_cts_pps_vault_account_cheque",
                    "pps_vault_entries", ["bank_id", "account_hash", "cheque_number"],
                    unique=True, schema="cts")
    op.create_index("ix_cts_pps_vault_account_hash",
                    "pps_vault_entries", ["account_hash"], schema="cts")
    op.create_index("ix_cts_pps_vault_status",
                    "pps_vault_entries", ["bank_id", "status"], schema="cts")
    op.create_index("ix_cts_pps_vault_expires",
                    "pps_vault_entries", ["expires_at"],
                    postgresql_where=sa.text("status = 'REGISTERED'"), schema="cts")


def downgrade() -> None:
    op.drop_table("pps_vault_entries", schema="cts")
    op.drop_table("signature_vault_entries", schema="cts")
