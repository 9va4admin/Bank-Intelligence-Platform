"""Cheque notifications and return notices.

cheque_notifications — outbound notifications to drawers/payees (WhatsApp + email)
return_notices       — formal return memo notices (RBI-mandated communication)

Revision ID: 20260618_010
Revises: 20260618_009
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_010"
down_revision = "20260618_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cheque_notifications ───────────────────────────────────────────────
    # Every outbound notification triggered by cheque lifecycle events.
    # Notification dispatcher (shared service) reads Kafka and writes delivery status here.
    op.create_table(
        "cheque_notifications",
        sa.Column("notification_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),

        # Trigger event
        sa.Column("event_type", sa.Text, nullable=False),
        # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW_REQUIRED |
        # RETURN_FILED | STOP_PAYMENT_ACTIVATED | IET_NEAR_BREACH

        # Recipient — masked, never raw PII
        sa.Column("recipient_type", sa.Text, nullable=False),
        # DRAWER | PAYEE | OPS_REVIEWER | BANK_OPS_MANAGER

        sa.Column("channel", sa.Text, nullable=False),
        # WHATSAPP | EMAIL | SMS | PUSH

        # Delivery
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | SENT | DELIVERED | FAILED | OPTED_OUT

        sa.Column("template_id", sa.Text, nullable=True),   # WhatsApp approved template ID
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_error", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_notifications_instrument",
                    "cheque_notifications", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_notifications_bank_status",
                    "cheque_notifications", ["bank_id", "status"],
                    postgresql_where=sa.text("status IN ('PENDING', 'FAILED')"), schema="cts")

    # ── return_notices ─────────────────────────────────────────────────────
    # Formal return notice sent to presenting bank / drawer.
    # RBI mandates return memo be communicated within the clearing cycle.
    # Distinct from cheque_notifications (those are customer-facing informal alerts).
    op.create_table(
        "return_notices",
        sa.Column("notice_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("return_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.return_items.return_id"), nullable=False),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),

        # Return reason (from NPCI return reason code)
        sa.Column("return_reason_code", sa.String(3), nullable=False),
        sa.Column("return_reason_description", sa.Text, nullable=False),

        # Presenting bank communication
        sa.Column("presenting_bank_code", sa.Text, nullable=False),
        sa.Column("presenting_ifsc", sa.Text, nullable=False),

        # NGCH electronic return memo reference
        sa.Column("ngch_return_memo_ref", sa.Text, nullable=True),

        # Customer notification (drawer of the cheque)
        sa.Column("drawer_notified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("drawer_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drawer_notification_channel", sa.Text, nullable=True),

        # Return memo document in MinIO
        sa.Column("memo_document_key", sa.Text, nullable=True),

        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | SENT_TO_NGCH | ACKNOWLEDGED | DRAWER_NOTIFIED | COMPLETE

        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_return_notices_return_id",
                    "return_notices", ["return_id"], schema="cts")
    op.create_index("ix_cts_return_notices_instrument",
                    "return_notices", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_return_notices_bank_status",
                    "return_notices", ["bank_id", "status"], schema="cts")


def downgrade() -> None:
    op.drop_table("return_notices", schema="cts")
    op.drop_table("cheque_notifications", schema="cts")
