"""Stop payment instructions and audit log.

stop_payment_instructions — customer-issued stop payment orders
stop_payment_audit        — every state transition and CBS sync event

A cheque matching a stop payment must be returned immediately
regardless of fraud score — enforced by OPA Rego policy (Layer 4).

Revision ID: 20260618_008
Revises: 20260618_007
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_008"
down_revision = "20260618_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── stop_payment_instructions ──────────────────────────────────────────
    # Customer instructs bank to stop payment on a specific cheque.
    # CBS is the authoritative source; VaultSyncWorkflow syncs to Redis fast-lookup.
    # ChequeProcessingWorkflow checks Redis first (< 1ms); DB is fallback + audit.
    op.create_table(
        "stop_payment_instructions",
        sa.Column("stop_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),

        # Account (hashed — never raw)
        sa.Column("account_hash", sa.Text, nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=False),

        # Stop payment scope
        sa.Column("scope", sa.Text, nullable=False),
        # SINGLE_CHEQUE | RANGE | ALL_CHEQUES

        # For SINGLE_CHEQUE scope
        sa.Column("cheque_number", sa.String(6), nullable=True),
        sa.Column("cheque_date", sa.Date, nullable=True),
        sa.Column("amount_paise", sa.BigInteger, nullable=True),  # for exact-match verification
        sa.Column("amount_range", sa.Text, nullable=True),

        # For RANGE scope
        sa.Column("cheque_from", sa.String(6), nullable=True),
        sa.Column("cheque_to", sa.String(6), nullable=True),

        # Stop reason (customer-provided)
        sa.Column("reason_code", sa.Text, nullable=False),
        # LOST | STOLEN | PAYMENT_CANCELLED | DISPUTE | OTHER
        sa.Column("reason_notes", sa.Text, nullable=True),

        # Lifecycle
        sa.Column("status", sa.Text, nullable=False, server_default="ACTIVE"),
        # ACTIVE | REVOKED | EXPIRED | PAYMENT_PROCESSED
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.Date, nullable=True),  # NULL = indefinite
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),

        # CBS reference
        sa.Column("cbs_stop_ref", sa.Text, nullable=True),
        sa.Column("channel", sa.Text, nullable=True),
        # INTERNET_BANKING | MOBILE | BRANCH | PHONE | CBS

        # Sync to Redis fast-lookup vault
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_stop_payment_account",
                    "stop_payment_instructions", ["bank_id", "account_hash"],
                    postgresql_where=sa.text("status = 'ACTIVE'"), schema="cts")
    op.create_index("ix_cts_stop_payment_cheque",
                    "stop_payment_instructions", ["bank_id", "cheque_number"],
                    postgresql_where=sa.text("scope = 'SINGLE_CHEQUE' AND status = 'ACTIVE'"),
                    schema="cts")
    op.create_index("ix_cts_stop_payment_status",
                    "stop_payment_instructions", ["bank_id", "status"], schema="cts")

    # ── stop_payment_audit ─────────────────────────────────────────────────
    # Append-only log of all stop payment lifecycle events.
    # Required for RBI audit (customer can dispute that stop payment wasn't honoured).
    op.create_table(
        "stop_payment_audit",
        sa.Column("audit_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("stop_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.stop_payment_instructions.stop_id"), nullable=False),
        sa.Column("bank_id", sa.Text, nullable=False),

        sa.Column("event_type", sa.Text, nullable=False),
        # CREATED | SYNCED_TO_REDIS | CBS_SYNC | CHEQUE_MATCHED | CHEQUE_RETURNED |
        # REVOKED | EXPIRED | PAYMENT_PROCESSED_DESPITE_STOP (critical — triggers alert)

        sa.Column("related_instrument_id", UUID(as_uuid=True), nullable=True),
        # Populated when a cheque matches this stop instruction

        sa.Column("event_detail", JSONB, nullable=True),
        # e.g. {"cheque_number": "123456", "action": "RETURNED", "workflow_id": "..."}

        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_stop_payment_audit_stop_id",
                    "stop_payment_audit", ["stop_id"], schema="cts")
    op.create_index("ix_cts_stop_payment_audit_instrument",
                    "stop_payment_audit", ["related_instrument_id"],
                    postgresql_where=sa.text("related_instrument_id IS NOT NULL"), schema="cts")
    op.create_index("ix_cts_stop_payment_audit_bank_event",
                    "stop_payment_audit", ["bank_id", "event_type", "occurred_at"], schema="cts")


def downgrade() -> None:
    op.drop_table("stop_payment_audit", schema="cts")
    op.drop_table("stop_payment_instructions", schema="cts")
