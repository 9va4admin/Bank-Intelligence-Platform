"""Platform notifications — single dispatcher, all modules.

Tables:
  platform.notification_templates — WhatsApp approved template registry
  platform.notification_records   — all outbound notifications (CTS + EJ + platform)

Replaces:
  cts.cheque_notifications      — merged here with module='CTS'
  cts.return_notices            — merged here with event_type='RETURN_NOTICE'
  ej.dispute_notifications      — merged here with module='EJ'

The notification-service is a shared service that reads from a single Kafka topic
(platform.notifications) regardless of which module fired the event.
It writes delivery status back to this table.

Revision ID: 20260618_p_003
Revises: 20260618_p_002
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_p_003"
down_revision = "20260618_p_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── platform.notification_templates ────────────────────────────────────
    # WhatsApp Business API approved templates must be registered and approved
    # by Meta before use. This registry tracks what is available per bank.
    # Also covers email templates (HTML via React Email).
    op.create_table(
        "notification_templates",
        sa.Column("template_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=True),
        # NULL = platform default template (used by all banks unless bank has own)

        sa.Column("module", sa.Text, nullable=False),
        # CTS | EJ | PLATFORM

        sa.Column("event_type", sa.Text, nullable=False),
        # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW_REQUIRED | RETURN_FILED |
        # DISPUTE_RAISED | DISPUTE_RESOLVED | ATM_CRITICAL | CASH_LOW |
        # CONFIG_CHANGE_PENDING | POLICY_ACTIVATED | USER_LOGIN_ALERT

        sa.Column("channel", sa.Text, nullable=False),
        # WHATSAPP | EMAIL | SMS

        sa.Column("language", sa.Text, nullable=False, server_default="en"),
        # ISO 639-1 language code

        # WhatsApp-specific
        sa.Column("wa_template_name", sa.Text, nullable=True),
        # Meta-assigned template name (e.g. "cts_cheque_return_notice")
        sa.Column("wa_template_status", sa.Text, nullable=True),
        # PENDING | APPROVED | REJECTED | PAUSED (Meta approval status)

        # Email-specific
        sa.Column("email_subject_template", sa.Text, nullable=True),
        sa.Column("email_component_name", sa.Text, nullable=True),
        # React Email component name in apps/notifications/

        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_notif_templates_lookup",
                    "notification_templates",
                    ["module", "event_type", "channel", "language"],
                    postgresql_where=sa.text("is_active = true"),
                    schema="platform")

    # ── platform.notification_records ─────────────────────────────────────
    # Every outbound notification from any module lands here.
    # module + event_type tells you which module triggered it.
    # case_ref is the relevant domain ID (instrument_id, dispute case_id, etc.)
    op.create_table(
        "notification_records",
        sa.Column("notification_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        # Source module and event
        sa.Column("module", sa.Text, nullable=False),
        # CTS | EJ | PLATFORM
        sa.Column("event_type", sa.Text, nullable=False),
        # CTS: STP_CONFIRM | STP_RETURN | HUMAN_REVIEW_REQUIRED | RETURN_FILED |
        #      STOP_PAYMENT_ACTIVATED | IET_NEAR_BREACH
        # EJ:  DISPUTE_RAISED | EVIDENCE_ASSEMBLED | AUTO_RESOLVED | ESCALATED |
        #      NPCI_FILED | ATM_CRITICAL | CASH_LOW | PREDICTED_FAILURE
        # PLATFORM: CONFIG_CHANGE_PENDING | POLICY_ACTIVATED | USER_LOGIN_ALERT |
        #           BANK_ONBOARDING_STEP

        # Domain reference — what this notification is about
        sa.Column("case_ref_type", sa.Text, nullable=True),
        # INSTRUMENT | DISPUTE | ATM | STOP_PAYMENT | CONFIG_CHANGE | POLICY
        sa.Column("case_ref_id", sa.Text, nullable=True),
        # The domain ID (instrument_id, dispute case_id, atm_id, etc.) as TEXT
        # Stored as TEXT not UUID — different modules use different ID formats

        # Recipient
        sa.Column("recipient_type", sa.Text, nullable=False),
        # DRAWER | PAYEE | OPS_REVIEWER | OPS_MANAGER | BRANCH_MANAGER |
        # COMPLIANCE_OFFICER | BANK_IT_ADMIN | CUSTOMER
        sa.Column("recipient_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        # NULL for external recipients (customers, drawers) who are not platform users

        # Channel and template
        sa.Column("channel", sa.Text, nullable=False),
        # WHATSAPP | EMAIL | SMS | PUSH
        sa.Column("template_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.notification_templates.template_id"), nullable=True),

        # Delivery status
        sa.Column("status", sa.Text, nullable=False, server_default="PENDING"),
        # PENDING | SENT | DELIVERED | READ | FAILED | OPTED_OUT
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_error", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),

        # Kafka event that triggered this notification
        sa.Column("kafka_offset", sa.BigInteger, nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_notif_records_bank_module",
                    "notification_records", ["bank_id", "module", "created_at"],
                    schema="platform")
    op.create_index("ix_platform_notif_records_case_ref",
                    "notification_records", ["case_ref_type", "case_ref_id"],
                    postgresql_where=sa.text("case_ref_id IS NOT NULL"),
                    schema="platform")
    op.create_index("ix_platform_notif_records_pending_retry",
                    "notification_records", ["next_retry_at"],
                    postgresql_where=sa.text("status IN ('PENDING', 'FAILED')"),
                    schema="platform")
    op.create_index("ix_platform_notif_records_recipient",
                    "notification_records", ["recipient_user_id"],
                    postgresql_where=sa.text("recipient_user_id IS NOT NULL"),
                    schema="platform")


def downgrade() -> None:
    op.drop_table("notification_records", schema="platform")
    op.drop_table("notification_templates", schema="platform")
