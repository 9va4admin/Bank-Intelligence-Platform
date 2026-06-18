"""PPS operational tables: registrations, confirmations, submission audit, NPCI exchange, disputes.

Covers the full PPS lifecycle beyond the vault cache:
  - pps_registrations        — customer-initiated PPS registrations (intake from CBS/channel)
  - pps_confirmations        — bank confirms payment after STP_CONFIRM decision
  - pps_submission_audit     — audit log of all NPCI PPS submissions
  - pps_npci_exchange_log    — NPCI acknowledgements for PPS data exchange
  - pps_dispute_log          — PPS-based disputes raised by drawee bank

Revision ID: 20260618_007
Revises: 20260618_006
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_007"
down_revision = "20260618_006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pps_registrations ──────────────────────────────────────────────────
    # Customer registers a cheque via internet banking / mobile / branch.
    # Bank validates and forwards to NPCI PPS system.
    # Linked to pps_vault_entries after NPCI confirmation.
    op.create_table(
        "pps_registrations",
        sa.Column("registration_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),

        # Account (hashed, never raw)
        sa.Column("account_hash", sa.Text, nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=False),

        # Cheque details as provided by customer
        sa.Column("cheque_number", sa.String(6), nullable=False),
        sa.Column("cheque_date", sa.Date, nullable=False),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("amount_range", sa.Text, nullable=False),
        sa.Column("payee_name_enc", sa.LargeBinary, nullable=True),  # pgp_sym_encrypt

        # Registration source
        sa.Column("channel", sa.Text, nullable=False),
        # INTERNET_BANKING | MOBILE_APP | BRANCH | API | CBS_BATCH

        # Validation and NPCI submission
        sa.Column("validation_status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | VALID | INVALID (bank-side validation before NPCI)
        sa.Column("validation_errors", JSONB, nullable=True),

        sa.Column("npci_submission_status", sa.Text, nullable=True),
        # NOT_SUBMITTED | SUBMITTED | ACCEPTED | REJECTED
        sa.Column("npci_submission_ref", sa.Text, nullable=True),
        sa.Column("npci_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("npci_response_at", sa.DateTime(timezone=True), nullable=True),

        # Vault entry linked once NPCI accepts
        sa.Column("vault_entry_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.pps_vault_entries.entry_id"), nullable=True),

        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_pps_registrations_bank_account",
                    "pps_registrations", ["bank_id", "account_hash"], schema="cts")
    op.create_index("ix_cts_pps_registrations_npci_status",
                    "pps_registrations", ["bank_id", "npci_submission_status"], schema="cts")

    # ── pps_confirmations ──────────────────────────────────────────────────
    # After a cheque is STP_CONFIRM decided, bank notifies NPCI PPS that cheque was paid.
    # This marks the PPS registration as CONFIRMED_PAID and prevents re-presentment fraud.
    op.create_table(
        "pps_confirmations",
        sa.Column("confirmation_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("vault_entry_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.pps_vault_entries.entry_id"), nullable=False),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.agent_decisions.decision_id"), nullable=False),

        # NPCI confirmation submission
        sa.Column("npci_confirmation_ref", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | SUBMITTED | CONFIRMED | FAILED
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_pps_confirmations_vault_entry",
                    "pps_confirmations", ["vault_entry_id"], schema="cts")
    op.create_index("ix_cts_pps_confirmations_instrument",
                    "pps_confirmations", ["instrument_id"], schema="cts")

    # ── pps_submission_audit ───────────────────────────────────────────────
    # Append-only audit log of every message sent to/received from NPCI PPS.
    # Separate from Immudb (which is the tamper-evident store); this is the
    # relational audit for reconciliation and dispute investigation.
    op.create_table(
        "pps_submission_audit",
        sa.Column("audit_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("related_registration_id", UUID(as_uuid=True), nullable=True),
        sa.Column("related_confirmation_id", UUID(as_uuid=True), nullable=True),

        sa.Column("message_type", sa.Text, nullable=False),
        # REGISTER | CANCEL | CONFIRM_PAID | QUERY | BULK_UPLOAD

        sa.Column("direction", sa.Text, nullable=False),
        # OUTBOUND (bank → NPCI) | INBOUND (NPCI → bank)

        sa.Column("npci_ref", sa.Text, nullable=True),
        sa.Column("status_code", sa.Text, nullable=True),   # NPCI response code
        sa.Column("payload_hash", sa.Text, nullable=True),  # SHA-256 of message (not raw content)

        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_pps_submission_audit_bank_date",
                    "pps_submission_audit", ["bank_id", "occurred_at"], schema="cts")
    op.create_index("ix_cts_pps_submission_audit_npci_ref",
                    "pps_submission_audit", ["npci_ref"],
                    postgresql_where=sa.text("npci_ref IS NOT NULL"), schema="cts")

    # ── pps_npci_exchange_log ──────────────────────────────────────────────
    # NPCI sends bulk PPS data files (other banks' PPS registrations) for cross-verification.
    # Bank must load these to validate inward cheques against presenting bank's PPS.
    op.create_table(
        "pps_npci_exchange_log",
        sa.Column("exchange_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),

        sa.Column("file_ref", sa.Text, nullable=False),        # NPCI exchange file reference
        sa.Column("file_type", sa.Text, nullable=False),
        # INWARD_PPS_DATA | OUTWARD_CONFIRMATION | DAILY_RECONCILIATION

        sa.Column("file_date", sa.Date, nullable=False),
        sa.Column("record_count", sa.Integer, nullable=True),
        sa.Column("file_hash", sa.Text, nullable=True),        # SHA-256 of exchange file

        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="'RECEIVED'"),
        # RECEIVED | PROCESSING | PROCESSED | FAILED

        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_pps_exchange_bank_date",
                    "pps_npci_exchange_log", ["bank_id", "file_date"], schema="cts")

    # ── pps_dispute_log ────────────────────────────────────────────────────
    # PPS-based disputes: drawee bank disputes a cheque that was STP_CONFIRM filed
    # but should have been returned (PPS mismatch not caught, or PPS not registered).
    op.create_table(
        "pps_dispute_log",
        sa.Column("dispute_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),

        sa.Column("disputed_by_bank_code", sa.Text, nullable=False),  # drawee bank
        sa.Column("dispute_reason", sa.Text, nullable=False),
        # PPS_NOT_REGISTERED | PPS_AMOUNT_MISMATCH | PPS_DATE_MISMATCH | PPS_PAYEE_MISMATCH

        sa.Column("dispute_raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("npci_dispute_ref", sa.Text, nullable=True),

        sa.Column("resolution", sa.Text, nullable=True),
        # UPHELD (bank pays back) | REJECTED (dispute not valid) | PENDING
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_pps_dispute_bank_instrument",
                    "pps_dispute_log", ["bank_id", "instrument_id"], schema="cts")
    op.create_index("ix_cts_pps_dispute_resolution",
                    "pps_dispute_log", ["bank_id", "resolution"],
                    postgresql_where=sa.text("resolution = 'PENDING' OR resolution IS NULL"),
                    schema="cts")


def downgrade() -> None:
    op.drop_table("pps_dispute_log", schema="cts")
    op.drop_table("pps_npci_exchange_log", schema="cts")
    op.drop_table("pps_submission_audit", schema="cts")
    op.drop_table("pps_confirmations", schema="cts")
    op.drop_table("pps_registrations", schema="cts")
