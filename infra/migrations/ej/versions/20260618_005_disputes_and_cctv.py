"""Dispute cases, evidence packages, NPCI filings, CCTV evidence, and notifications.

dispute_cases              — one per NPCI claim / customer dispute
dispute_evidence_package   — assembled evidence for each dispute case
dispute_npci_filings       — formal filing with NPCI dispute portal
cctv_evidences             — CCTV clip references (MinIO only — never inline bytes)
dispute_notifications      — outbound notifications for dispute events

Revision ID: 20260618_ej_005
Revises: 20260618_ej_004
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_ej_005"
down_revision = "20260618_ej_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── dispute_cases ──────────────────────────────────────────────────────
    # One row per dispute case, triggered by NPCI claim or customer complaint.
    # DisputeResolutionWorkflow uses workflow_id = ej-dispute-{bank_id}-{npci_claim_id}
    op.create_table(
        "dispute_cases",
        sa.Column("case_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("atm_id", sa.Text,
                  sa.ForeignKey("ej.atm_master.atm_id"), nullable=True),

        # NPCI / customer claim details
        sa.Column("npci_claim_id", sa.Text, nullable=True, unique=True),
        # Null for internal disputes raised before NPCI involvement
        sa.Column("dispute_type", sa.Text, nullable=False),
        # CASH_NOT_DISPENSED | PARTIAL_DISPENSE | CARD_RETAINED |
        # WRONG_AMOUNT | DOUBLE_DEBIT | UNAUTHORIZED_TXNEW

        # Cardholder claim (no full card number — last 4 only)
        sa.Column("card_last4", sa.String(4), nullable=True),
        sa.Column("claimed_amount_paise", sa.BigInteger, nullable=True),
        sa.Column("claimed_timestamp", sa.DateTime(timezone=True), nullable=True),

        # Matched EJ canonical record (populated by dispute_match activity)
        sa.Column("matched_record_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.ej_canonical_records.record_id"), nullable=True),
        sa.Column("match_score", sa.Numeric(5, 4), nullable=True),
        # BGE-M3 cosine similarity score — must be above threshold for auto-resolution

        # Workflow reference
        sa.Column("workflow_id", sa.Text, nullable=True),
        # ej-dispute-{bank_id}-{npci_claim_id}

        # Resolution
        sa.Column("status", sa.Text, nullable=False, server_default="'OPEN'"),
        # OPEN | MATCHING | EVIDENCE_ASSEMBLY | UNDER_REVIEW |
        # AUTO_RESOLVED | ESCALATED_TO_HUMAN | FILED_TO_NPCI | CLOSED

        sa.Column("resolution", sa.Text, nullable=True),
        # AUTO_RESOLVED_IN_FAVOUR | AUTO_RESOLVED_REJECTED |
        # HUMAN_RESOLVED_IN_FAVOUR | HUMAN_RESOLVED_REJECTED | NPCI_ARBITRATED

        sa.Column("resolution_reason", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Text, nullable=True),  # user ID or "SYSTEM"

        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_dispute_cases_bank_status",
                    "dispute_cases", ["bank_id", "status"], schema="ej")
    op.create_index("ix_ej_dispute_cases_atm",
                    "dispute_cases", ["atm_id"],
                    postgresql_where=sa.text("atm_id IS NOT NULL"), schema="ej")
    op.create_index("ix_ej_dispute_cases_npci_claim",
                    "dispute_cases", ["npci_claim_id"],
                    postgresql_where=sa.text("npci_claim_id IS NOT NULL"), schema="ej")
    op.create_index("ix_ej_dispute_cases_matched_record",
                    "dispute_cases", ["matched_record_id"],
                    postgresql_where=sa.text("matched_record_id IS NOT NULL"), schema="ej")

    # ── dispute_evidence_package ───────────────────────────────────────────
    # Assembled evidence for each dispute case.
    # Created by DisputeResolutionWorkflow before auto-resolve or NPCI filing.
    op.create_table(
        "dispute_evidence_package",
        sa.Column("package_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("case_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.dispute_cases.case_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        # EJ evidence
        sa.Column("ej_record_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.ej_canonical_records.record_id"), nullable=True),
        sa.Column("ej_match_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("ej_evidence_summary", JSONB, nullable=True),
        # Structured summary of what the EJ record shows (no raw log content)

        # CCTV evidence (MinIO key only — no inline clip data ever)
        sa.Column("cctv_evidence_id", UUID(as_uuid=True), nullable=True),
        # FK to cctv_evidences (created below)
        sa.Column("cctv_available", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("cctv_confirms_dispense", sa.Boolean, nullable=True),
        # NULL = CCTV inconclusive; True = dispense confirmed; False = no dispense confirmed

        # Package MinIO key (PDF evidence bundle for NPCI)
        sa.Column("package_document_key", sa.Text, nullable=True),
        # ej/disputes/{bank_id}/{case_id}/evidence.pdf

        sa.Column("assembled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("package_hash", sa.Text, nullable=True),  # SHA-256 of evidence bundle
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_evidence_package_case",
                    "dispute_evidence_package", ["case_id"], schema="ej")

    # ── cctv_evidences ─────────────────────────────────────────────────────
    # CCTV clip metadata for dispute evidence.
    # Actual clip in MinIO only — no BYTEA here.
    # Branch CCTV adapter fetches clip, stores to MinIO, writes this row.
    op.create_table(
        "cctv_evidences",
        sa.Column("evidence_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("case_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.dispute_cases.case_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("atm_id", sa.Text, nullable=False),
        sa.Column("branch_ifsc", sa.Text, nullable=True),

        # CCTV clip details
        sa.Column("camera_id", sa.Text, nullable=True),
        sa.Column("clip_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clip_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clip_duration_seconds", sa.Integer, nullable=True),

        # MinIO storage (encrypted at rest, WORM policy)
        # Object key format: cctv/{bank_id}/{atm_id}/{npci_claim_id}.mp4
        sa.Column("minio_key", sa.Text, nullable=False),
        sa.Column("file_hash", sa.Text, nullable=True),     # SHA-256 of clip
        sa.Column("file_size_bytes", sa.BigInteger, nullable=True),

        # AI analysis result (InternVL2-26B)
        sa.Column("analysis_status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | ANALYSED | ANALYSIS_FAILED
        sa.Column("dispense_event_detected", sa.Boolean, nullable=True),
        sa.Column("person_present_detected", sa.Boolean, nullable=True),
        sa.Column("analysis_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("analysis_summary", sa.Text, nullable=True),

        # Source
        sa.Column("fetch_status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | FETCHED | FETCH_FAILED | STORE_FAILED
        sa.Column("vendor_clip_ref", sa.Text, nullable=True),  # CCTV vendor's clip ID

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_cctv_evidences_case",
                    "cctv_evidences", ["case_id"], schema="ej")
    op.create_index("ix_ej_cctv_evidences_atm",
                    "cctv_evidences", ["atm_id"], schema="ej")

    # Add FK from dispute_evidence_package to cctv_evidences now that both exist
    op.create_foreign_key(
        "fk_evidence_package_cctv",
        "dispute_evidence_package", "cctv_evidences",
        ["cctv_evidence_id"], ["evidence_id"],
        source_schema="ej", referent_schema="ej",
    )

    # ── dispute_npci_filings ───────────────────────────────────────────────
    # Formal NPCI dispute portal filing when auto-resolution is not possible.
    op.create_table(
        "dispute_npci_filings",
        sa.Column("filing_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("case_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.dispute_cases.case_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        sa.Column("npci_claim_id", sa.Text, nullable=True),   # NPCI's claim reference
        sa.Column("filing_type", sa.Text, nullable=False),
        # INITIAL_FILING | RESPONSE | SUPPLEMENTARY | APPEAL

        # Evidence package submitted
        sa.Column("package_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.dispute_evidence_package.package_id"), nullable=True),

        # NPCI response
        sa.Column("npci_filing_ref", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | SUBMITTED | ACKNOWLEDGED | PENDING_ARBITRATION | DECIDED

        sa.Column("npci_decision", sa.Text, nullable=True),
        # BANK_FAVOURED | CUSTOMER_FAVOURED | SPLIT | FURTHER_INFO_REQUIRED

        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        # NPCI mandated response deadline

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_npci_filings_case",
                    "dispute_npci_filings", ["case_id"], schema="ej")
    op.create_index("ix_ej_npci_filings_bank_status",
                    "dispute_npci_filings", ["bank_id", "status"],
                    postgresql_where=sa.text("status NOT IN ('DECIDED')"), schema="ej")

    # ── dispute_notifications ──────────────────────────────────────────────
    # Outbound notifications for dispute lifecycle events.
    op.create_table(
        "dispute_notifications",
        sa.Column("notification_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("case_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.dispute_cases.case_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        sa.Column("event_type", sa.Text, nullable=False),
        # DISPUTE_RAISED | EVIDENCE_ASSEMBLED | AUTO_RESOLVED | ESCALATED |
        # NPCI_FILED | NPCI_DECIDED | HUMAN_REVIEW_REQUIRED

        sa.Column("recipient_type", sa.Text, nullable=False),
        # CUSTOMER | BRANCH_MANAGER | OPS_MANAGER | COMPLIANCE_OFFICER

        sa.Column("channel", sa.Text, nullable=False),
        # WHATSAPP | EMAIL | SMS

        sa.Column("status", sa.Text, nullable=False, server_default="'PENDING'"),
        # PENDING | SENT | DELIVERED | FAILED

        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_dispute_notifications_case",
                    "dispute_notifications", ["case_id"], schema="ej")
    op.create_index("ix_ej_dispute_notifications_bank_status",
                    "dispute_notifications", ["bank_id", "status"],
                    postgresql_where=sa.text("status IN ('PENDING', 'FAILED')"), schema="ej")


def downgrade() -> None:
    op.drop_table("dispute_notifications", schema="ej")
    op.drop_table("dispute_npci_filings", schema="ej")
    op.drop_constraint("fk_evidence_package_cctv", "dispute_evidence_package", schema="ej",
                       type_="foreignkey")
    op.drop_table("cctv_evidences", schema="ej")
    op.drop_table("dispute_evidence_package", schema="ej")
    op.drop_table("dispute_cases", schema="ej")
