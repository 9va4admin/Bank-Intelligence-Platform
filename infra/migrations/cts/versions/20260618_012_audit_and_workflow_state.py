"""CTS audit events, workflow states, and high-value check log.

cts_audit_events    — domain-level audit trail (Immudb is the tamper-proof store;
                      this YugabyteDB copy enables fast SQL queries for compliance reports)
workflow_states     — snapshot of each Temporal workflow's last-known state
                      (for admin UI and IET dashboard — Temporal is authoritative)
high_value_check_log — dual-approver log for cheques requiring extra sign-off

Revision ID: 20260618_012
Revises: 20260618_011
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_012"
down_revision = "20260618_011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cts_audit_events ───────────────────────────────────────────────────
    # Domain audit events written by every CTS service activity.
    # These are secondary copies — Immudb is the primary tamper-evident store.
    # This table exists so compliance_officer can run standard SQL audit reports
    # without querying Immudb (which has no SQL interface).
    # Every row here has a corresponding Immudb entry (verified by immudb_tx_id).
    op.create_table(
        "cts_audit_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),

        # Event classification
        sa.Column("event_type", sa.Text, nullable=False),
        # CHEQUE_RECEIVED | OCR_COMPLETE | SIGNATURE_VERIFIED | PPS_CHECKED |
        # FRAUD_SCORED | DECISION_MADE | NGCH_FILED | NGCH_ACKNOWLEDGED |
        # HUMAN_REVIEW_ESCALATED | HUMAN_REVIEW_DECIDED | RETURN_FILED |
        # VAULT_SYNC_COMPLETE | CONFIG_CHANGED | STOP_PAYMENT_ACTIVATED

        sa.Column("severity", sa.Text, nullable=False, server_default="'INFO'"),
        # INFO | WARN | CRITICAL

        # Source
        sa.Column("workflow_id", sa.Text, nullable=True),
        sa.Column("activity_name", sa.Text, nullable=True),
        sa.Column("service_name", sa.Text, nullable=False),

        # Subject
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=True),
        sa.Column("decision_id", UUID(as_uuid=True), nullable=True),

        # Event payload (non-PII — no account numbers, masked amounts)
        sa.Column("event_data", JSONB, nullable=False),
        # {"amount_range": "₹[5L-10L]", "account_suffix": "****4521", "decision": "STP_CONFIRM"}

        # Immudb reference (proves this event is in the tamper-evident log)
        sa.Column("immudb_tx_id", sa.BigInteger, nullable=True),
        sa.Column("immudb_verified", sa.Boolean, nullable=False, server_default="false"),

        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_audit_events_bank_occurred",
                    "cts_audit_events", ["bank_id", "occurred_at"], schema="cts")
    op.create_index("ix_cts_audit_events_instrument",
                    "cts_audit_events", ["instrument_id"],
                    postgresql_where=sa.text("instrument_id IS NOT NULL"), schema="cts")
    op.create_index("ix_cts_audit_events_type_bank",
                    "cts_audit_events", ["event_type", "bank_id", "occurred_at"], schema="cts")
    op.create_index("ix_cts_audit_events_severity_critical",
                    "cts_audit_events", ["bank_id", "occurred_at"],
                    postgresql_where=sa.text("severity = 'CRITICAL'"), schema="cts")

    # ── workflow_states ────────────────────────────────────────────────────
    # Last-known state snapshot of each Temporal workflow.
    # Temporal is the authoritative source; this is the ASTRA-side projection
    # used for the IET dashboard and admin UI (avoids polling Temporal SDK per request).
    # Updated by workflow activities via Kafka events.
    op.create_table(
        "workflow_states",
        sa.Column("workflow_id", sa.Text, primary_key=True),
        # cts-{bank_id}-{instrument_id} or cts-iet-{bank_id}-{instrument_id}
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),
        sa.Column("workflow_type", sa.Text, nullable=False),
        # ChequeProcessingWorkflow | IETWatchdogWorkflow | HumanReviewWorkflow | VaultSyncWorkflow

        sa.Column("instrument_id", UUID(as_uuid=True), nullable=True),

        # Temporal state
        sa.Column("temporal_run_id", sa.Text, nullable=True),
        sa.Column("current_state", sa.Text, nullable=False),
        # RUNNING | COMPLETED | FAILED | TIMED_OUT | CANCELLED
        # For ChequeProcessingWorkflow: also OCR_RUNNING | FRAUD_SCORING | FILING etc.

        sa.Column("last_activity", sa.Text, nullable=True),   # most recently completed activity
        sa.Column("current_activity", sa.Text, nullable=True), # currently executing activity

        # IET tracking (populated for ChequeProcessingWorkflow)
        sa.Column("iet_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("iet_margin_seconds", sa.Integer, nullable=True),
        # Updated every 30s by IETWatchdogWorkflow — powers the IET countdown UI

        # Terminal result
        sa.Column("terminal_decision", sa.Text, nullable=True),
        # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW | EMERGENCY_FILED

        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_workflow_states_bank_running",
                    "workflow_states", ["bank_id", "current_state"],
                    postgresql_where=sa.text("current_state = 'RUNNING'"), schema="cts")
    op.create_index("ix_cts_workflow_states_instrument",
                    "workflow_states", ["instrument_id"],
                    postgresql_where=sa.text("instrument_id IS NOT NULL"), schema="cts")
    op.create_index("ix_cts_workflow_states_iet_deadline",
                    "workflow_states", ["iet_deadline_at"],
                    postgresql_where=sa.text(
                        "current_state = 'RUNNING' AND iet_deadline_at IS NOT NULL"
                    ), schema="cts")

    # ── high_value_check_log ───────────────────────────────────────────────
    # Cheques above the high_value_amount_threshold (configurable, default ₹50L)
    # that require dual ops_reviewer approval (OPA Rego Layer 4 policy).
    # This table tracks both approvals — second approval triggers NGCH filing.
    op.create_table(
        "high_value_check_log",
        sa.Column("hvc_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.agent_decisions.decision_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("cts.banks_master.bank_id"),
                  nullable=False),

        sa.Column("amount_range", sa.Text, nullable=False),
        # HIGH_VALUE | VERY_HIGH_VALUE — stored as range bucket, not exact amount

        # First approver
        sa.Column("first_reviewer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("first_decision", sa.Text, nullable=True),  # CONFIRM | RETURN
        sa.Column("first_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_reviewer_notes", sa.Text, nullable=True),

        # Second approver (required for VERY_HIGH_VALUE)
        sa.Column("second_reviewer_required", sa.Boolean, nullable=False,
                  server_default="false"),
        sa.Column("second_reviewer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("second_decision", sa.Text, nullable=True),  # CONFIRM | RETURN
        sa.Column("second_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("second_reviewer_notes", sa.Text, nullable=True),

        # Conflict resolution (if first and second disagree — escalate to ops_manager)
        sa.Column("conflict_detected", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("conflict_resolved_by", UUID(as_uuid=True), nullable=True),
        sa.Column("conflict_resolution", sa.Text, nullable=True),

        # Final outcome after dual approval
        sa.Column("final_decision", sa.Text, nullable=True),  # CONFIRM | RETURN
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("status", sa.Text, nullable=False, server_default="'AWAITING_FIRST'"),
        # AWAITING_FIRST | AWAITING_SECOND | CONFLICT | FINALIZED

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_hvc_log_instrument",
                    "high_value_check_log", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_hvc_log_bank_status",
                    "high_value_check_log", ["bank_id", "status"],
                    postgresql_where=sa.text("status != 'FINALIZED'"), schema="cts")


def downgrade() -> None:
    op.drop_table("high_value_check_log", schema="cts")
    op.drop_table("workflow_states", schema="cts")
    op.drop_table("cts_audit_events", schema="cts")
