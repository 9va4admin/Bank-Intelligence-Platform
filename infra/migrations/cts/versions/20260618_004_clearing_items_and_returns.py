"""Inward clearing items, outward clearing items, and return memos.

inward_clearing_items  — each cheque received from presenting bank in NGCH inward file
outward_clearing_items — cheques sent outward (drawee bank receives these)
return_items           — return memos for dishonoured cheques (NPCI return reason codes)

Revision ID: 20260618_004
Revises: 20260618_003
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_004"
down_revision = "20260618_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── inward_clearing_items ──────────────────────────────────────────────
    # One row per cheque received in an NGCH inward file.
    # Linked to cheque_instruments (the canonical record) + the clearing batch.
    op.create_table(
        "inward_clearing_items",
        sa.Column("item_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_batches.batch_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_sessions.session_id"), nullable=False),

        # NGCH inward file reference
        sa.Column("ngch_file_ref", sa.Text, nullable=True),
        sa.Column("ngch_sequence_no", sa.Integer, nullable=True),  # seq within file

        # Presenting bank details (received from NGCH)
        sa.Column("presenting_bank_code", sa.Text, nullable=False),
        sa.Column("presenting_ifsc", sa.Text, nullable=False),
        sa.Column("drawee_ifsc", sa.Text, nullable=False),

        # MICR fields
        sa.Column("cheque_number", sa.String(6), nullable=False),
        sa.Column("micr_code", sa.String(9), nullable=False),

        # Amount received from presenting bank (for reconciliation cross-check)
        sa.Column("presented_amount_paise", sa.BigInteger, nullable=False),
        sa.Column("cheque_date", sa.Date, nullable=False),

        # Processing outcome
        sa.Column("decision", sa.Text, nullable=True),
        # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW_CONFIRM | HUMAN_REVIEW_RETURN
        sa.Column("decision_reason_code", sa.Text, nullable=True),   # NPCI return reason code if returned
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),

        # IET tracking
        sa.Column("iet_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("iet_breached", sa.Boolean, nullable=False, server_default="false"),

        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_inward_items_instrument",
                    "inward_clearing_items", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_inward_items_batch",
                    "inward_clearing_items", ["batch_id"], schema="cts")
    op.create_index("ix_cts_inward_items_bank_received",
                    "inward_clearing_items", ["bank_id", "received_at"], schema="cts")
    op.create_index("ix_cts_inward_items_iet_deadline",
                    "inward_clearing_items", ["iet_deadline_at"],
                    postgresql_where=sa.text("iet_breached = false AND decision IS NULL"),
                    schema="cts")

    # ── outward_clearing_items ─────────────────────────────────────────────
    # Cheques presented outward by the bank (the bank acts as presenting bank).
    # These are sent to NGCH for collection against other drawee banks.
    op.create_table(
        "outward_clearing_items",
        sa.Column("item_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("batch_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_batches.batch_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_sessions.session_id"), nullable=False),

        # Image keys (MinIO) — presented to NGCH
        sa.Column("front_grey_key", sa.Text, nullable=True),
        sa.Column("front_bw_key", sa.Text, nullable=True),
        sa.Column("reverse_bw_key", sa.Text, nullable=True),

        # MICR fields
        sa.Column("cheque_number", sa.String(6), nullable=False),
        sa.Column("micr_code", sa.String(9), nullable=False),
        sa.Column("drawee_ifsc", sa.Text, nullable=False),       # bank on which drawn
        sa.Column("drawee_bank_code", sa.Text, nullable=False),

        # Amount
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("cheque_date", sa.Date, nullable=False),

        # CTS 2010 compliance flags (validated before submission)
        sa.Column("cts2010_compliant", sa.Boolean, nullable=False, server_default="false"),

        # NGCH submission outcome
        sa.Column("ngch_item_ref", sa.Text, nullable=True),      # assigned by NGCH on receipt
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | SUBMITTED | ACKNOWLEDGED | RETURNED_BY_DRAWEE | SETTLED

        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_outward_items_batch",
                    "outward_clearing_items", ["batch_id"], schema="cts")
    op.create_index("ix_cts_outward_items_bank_status",
                    "outward_clearing_items", ["bank_id", "status"], schema="cts")
    op.create_index("ix_cts_outward_items_drawee_ifsc",
                    "outward_clearing_items", ["drawee_ifsc"], schema="cts")

    # ── return_items ───────────────────────────────────────────────────────
    # Return memos for dishonoured cheques.
    # A return can originate from:
    #   (a) drawee bank returning an inward item (cheque cannot be paid)
    #   (b) presenting bank receiving a return for an outward item it submitted
    # NPCI mandates return within 24 hours (IET for return filing).
    op.create_table(
        "return_items",
        sa.Column("return_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.clearing_sessions.session_id"), nullable=True),

        # Source linkage (one of these will be populated, not both)
        sa.Column("inward_item_id", UUID(as_uuid=True), nullable=True),   # if we are returning
        sa.Column("outward_item_id", UUID(as_uuid=True), nullable=True),  # if counterparty returned

        # Original cheque identifiers (denormalised for fast query without joining partitioned table)
        sa.Column("cheque_number", sa.String(6), nullable=False),
        sa.Column("micr_code", sa.String(9), nullable=False),
        sa.Column("original_amount_paise", sa.BigInteger, nullable=False),
        sa.Column("original_cheque_date", sa.Date, nullable=False),

        # NPCI-standardised return reason codes (CTS 2010 Annexure II)
        sa.Column("return_reason_code", sa.String(3), nullable=False),
        # e.g. "01"=Funds insufficient, "06"=Payment stopped by drawer, etc.
        sa.Column("return_reason_description", sa.Text, nullable=True),

        # Return direction
        sa.Column("return_type", sa.Text, nullable=False),
        # OUTWARD_RETURN (we return inward) | INWARD_RETURN (counterparty returns our outward)

        # Filing to NGCH
        sa.Column("return_ngch_ref", sa.Text, nullable=True),
        sa.Column("return_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("return_deadline_breached", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | FILED | ACKNOWLEDGED | SETTLED

        # Memo image in MinIO (scanned return memo)
        sa.Column("return_memo_key", sa.Text, nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_return_items_bank_status",
                    "return_items", ["bank_id", "status"], schema="cts")
    op.create_index("ix_cts_return_items_inward_item",
                    "return_items", ["inward_item_id"],
                    postgresql_where=sa.text("inward_item_id IS NOT NULL"), schema="cts")
    op.create_index("ix_cts_return_items_outward_item",
                    "return_items", ["outward_item_id"],
                    postgresql_where=sa.text("outward_item_id IS NOT NULL"), schema="cts")
    op.create_index("ix_cts_return_items_deadline",
                    "return_items", ["return_deadline_at"],
                    postgresql_where=sa.text("status = 'PENDING'"), schema="cts")


def downgrade() -> None:
    op.drop_table("return_items", schema="cts")
    op.drop_table("outward_clearing_items", schema="cts")
    op.drop_table("inward_clearing_items", schema="cts")
