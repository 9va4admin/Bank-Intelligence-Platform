"""Agent decisions, NGCH submissions, and human review items.

agent_decisions     — AI agent output per cheque: fraud score, SHAP, rationale, final decision
ngch_submissions    — exactly-once NGCH filing record (idempotency guard)
human_review_items  — escalated cheques with full context bundle for ops reviewer

Revision ID: 20260618_005
Revises: 20260618_004
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_005"
down_revision = "20260618_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agent_decisions ────────────────────────────────────────────────────
    # One row per ChequeProcessingWorkflow terminal decision.
    # SHAP values mandatory — no NGCH submission without this row.
    op.create_table(
        "agent_decisions",
        sa.Column("decision_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False, unique=True),
        # cts-{bank_id}-{instrument_id} — unique per cheque

        # AI activity outputs
        sa.Column("ocr_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("ocr_extracted", JSONB, nullable=True),
        # {"amount_figures": ..., "amount_words": ..., "payee": ..., "date": ...}
        # Values here are extracted text, NOT raw PII — payee is first-letter-masked

        sa.Column("alteration_detected", sa.Boolean, nullable=True),
        sa.Column("alteration_details", JSONB, nullable=True),
        # {"fields_altered": [...], "tamper_risk": 0.xx}

        sa.Column("signature_match_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("signature_verdict", sa.Text, nullable=True),
        # MATCH | MISMATCH | VAULT_MISS | LOW_CONFIDENCE

        sa.Column("pps_checked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("pps_verdict", sa.Text, nullable=True),
        # MATCH | MISMATCH | NOT_REGISTERED | VAULT_MISS

        sa.Column("cbs_balance_status", sa.Text, nullable=True),
        # SUFFICIENT | INSUFFICIENT | ACCOUNT_FROZEN | ACCOUNT_CLOSED | CBS_UNREACHABLE

        # Fraud scoring — XGBoost + SHAP (mandatory before NGCH filing)
        sa.Column("fraud_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("shap_values", JSONB, nullable=True),
        # {"feature_name": shap_impact, ...} — must be non-null before NGCH filing
        sa.Column("fraud_rationale", sa.Text, nullable=True),  # LLM-generated human-readable explanation

        # Final decision
        sa.Column("decision", sa.Text, nullable=False),
        # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW
        sa.Column("decision_reason", sa.Text, nullable=True),
        sa.Column("decision_confidence", sa.Numeric(5, 4), nullable=True),

        # Processing timing
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_duration_ms", sa.Integer, nullable=True),

        # IET safety
        sa.Column("iet_margin_seconds", sa.Integer, nullable=True),
        # Seconds remaining when decision was made — must be > 0 always

        sa.Column("degraded_mode", sa.Boolean, nullable=False, server_default="false"),
        # True if any activity ran in fallback (CBS miss, vLLM down, etc.)

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_agent_decisions_instrument",
                    "agent_decisions", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_agent_decisions_bank_decision",
                    "agent_decisions", ["bank_id", "decision"], schema="cts")
    op.create_index("ix_cts_agent_decisions_workflow",
                    "agent_decisions", ["workflow_id"], schema="cts")
    op.create_index("ix_cts_agent_decisions_fraud_score",
                    "agent_decisions", ["bank_id", "fraud_score"],
                    postgresql_where=sa.text("fraud_score IS NOT NULL"), schema="cts")

    # ── ngch_submissions ───────────────────────────────────────────────────
    # Exactly-once NGCH filing record.
    # Before submitting to NGCH: insert this row with status=PENDING.
    # If row already exists (workflow replay/retry) → skip submission (idempotency guard).
    # NGCH acknowledgement updates the row to ACKNOWLEDGED.
    op.create_table(
        "ngch_submissions",
        sa.Column("submission_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.agent_decisions.decision_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),

        # Idempotency: one submission per instrument per decision type
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        # Format: ngch-{bank_id}-{instrument_id}-{decision}

        sa.Column("submission_type", sa.Text, nullable=False),
        # CONFIRM | RETURN | EMERGENCY_CONFIRM | EMERGENCY_RETURN
        # EMERGENCY variants used when IETWatchdogWorkflow fires at T-30s

        # NGCH response
        sa.Column("ngch_ref", sa.Text, nullable=True),     # NGCH-assigned reference on ack
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | SUBMITTED | ACKNOWLEDGED | REJECTED | DUPLICATE_REJECTED

        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ngch_response_raw", JSONB, nullable=True),  # full NGCH ack/reject payload

        # Retry tracking
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_ngch_submissions_instrument",
                    "ngch_submissions", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_ngch_submissions_bank_status",
                    "ngch_submissions", ["bank_id", "status"], schema="cts")
    op.create_index("ix_cts_ngch_submissions_idempotency",
                    "ngch_submissions", ["idempotency_key"], unique=True, schema="cts")

    # ── human_review_items ─────────────────────────────────────────────────
    # Escalated cheques awaiting ops reviewer decision.
    # Contains full context bundle so reviewer doesn't need to query other tables.
    # HumanReviewWorkflow waits on Temporal signal (max 55 min before auto-return).
    op.create_table(
        "human_review_items",
        sa.Column("review_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("instrument_id", UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", UUID(as_uuid=True),
                  sa.ForeignKey("cts.agent_decisions.decision_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"),
                  nullable=False),
        sa.Column("workflow_id", sa.Text, nullable=False),  # HumanReviewWorkflow ID
        sa.Column("parent_workflow_id", sa.Text, nullable=False),  # ChequeProcessingWorkflow ID

        # Escalation reason
        sa.Column("escalation_reason", sa.Text, nullable=False),
        # FRAUD_SCORE_HIGH | SIGNATURE_VAULT_MISS | PPS_MISMATCH | ALTERATION_DETECTED |
        # OCR_LOW_CONFIDENCE | CBS_UNREACHABLE | POLICY_RULE | HUMAN_REVIEW_THRESHOLD

        # Context bundle for reviewer UI (pre-assembled by agent — avoids reviewer waiting)
        sa.Column("context_bundle", JSONB, nullable=False),
        # {
        #   "cheque_number": "123456",
        #   "account_suffix": "****4521",
        #   "amount_range": "₹[5L-10L]",
        #   "payee_display": "N***",
        #   "fraud_score": 0.74,
        #   "fraud_rationale": "...",
        #   "signature_verdict": "VAULT_MISS",
        #   "alteration_details": {...},
        #   "image_urls": {"front_grey": "presigned_url", ...},
        #   "shap_top5": [{"feature": ..., "impact": ...}, ...]
        # }

        # IET deadline (reviewer must decide before this — otherwise auto-returned)
        sa.Column("review_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("iet_deadline_at", sa.DateTime(timezone=True), nullable=False),

        # Reviewer assignment (cleared zone scoping enforced by RBAC)
        sa.Column("assigned_zone", sa.Text, nullable=True),
        sa.Column("assigned_reviewer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),

        # Outcome
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | IN_REVIEW | REVIEWER_CONFIRMED | REVIEWER_RETURNED | TIMEOUT_AUTO_RETURNED
        sa.Column("reviewer_decision", sa.Text, nullable=True),   # CONFIRM | RETURN
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="cts",
    )
    op.create_index("ix_cts_human_review_bank_status",
                    "human_review_items", ["bank_id", "status"], schema="cts")
    op.create_index("ix_cts_human_review_instrument",
                    "human_review_items", ["instrument_id"], schema="cts")
    op.create_index("ix_cts_human_review_deadline",
                    "human_review_items", ["review_deadline_at"],
                    postgresql_where=sa.text("status = 'PENDING' OR status = 'IN_REVIEW'"),
                    schema="cts")
    op.create_index("ix_cts_human_review_zone_pending",
                    "human_review_items", ["assigned_zone", "status"], schema="cts")


def downgrade() -> None:
    op.drop_table("human_review_items", schema="cts")
    op.drop_table("ngch_submissions", schema="cts")
    op.drop_table("agent_decisions", schema="cts")
