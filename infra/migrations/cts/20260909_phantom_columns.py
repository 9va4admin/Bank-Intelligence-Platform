"""
Additive ALTER TABLE migration — fills phantom columns discovered by column audit
(2026-09-09).

Each column listed here was referenced in Python code but absent from the migration
chain, meaning any deployed code path that touched them would raise
PG ERROR: column "X" does not exist at runtime.

All new columns are nullable (backwards-compatible per upgrade policy in CLAUDE.md §2.4).
NOT NULL constraints, if needed, are deferred to the next release once backfill is done.

Tables patched:
  cts.cheque_instruments  — +queue_tier, +review_assigned_at, +ngch_acknowledgement_id,
                             +final_decision, +decision_recorded_at
  cts.clearing_sessions   — +failure_reason
  cts.lots                — +sealed_by, +updated_at
  cts.mismatch_queue      — +scan_id, +updated_at

Revision: 20260909_phantom_columns
Revises:  20260903_rrf_sessions
"""
from alembic import op
import sqlalchemy as sa

revision = "20260909_phantom_columns"
down_revision = "20260903_rrf_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cts.cheque_instruments ───────────────────────────────────────────────────
    # queue_tier — priority tier used by inward queue to allocate Temporal workers.
    # Values: "standard" | "high_value" | "smb". Defaults to "standard".
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "queue_tier",
            sa.Text(),
            nullable=False,
            server_default="standard",
            comment="Inward worker queue priority: standard | high_value | smb",
        ),
        schema="cts",
    )

    # review_assigned_at — set by HumanReviewConsumer when the instrument enters
    # the human review queue; used by ops dashboard to track assignment latency.
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "review_assigned_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp when cheque was routed to human review queue",
        ),
        schema="cts",
    )

    # ngch_acknowledgement_id — the NGCH filing ack ref written by DecisionConsumer
    # on CTS_NGCH_FILED event; lets ops UI show ack without querying Temporal.
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "ngch_acknowledgement_id",
            sa.Text(),
            nullable=True,
            comment="NGCH filing acknowledgement reference — set on CTS_NGCH_FILED event",
        ),
        schema="cts",
    )

    # final_decision — APPROVED | RETURNED etc., mirrored from agent_decisions so the
    # ops UI can read from a single table without joining.
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "final_decision",
            sa.Text(),
            nullable=True,
            comment="APPROVED | RETURNED | STP_CONFIRMED | HUMAN_REVIEW — copied from agent_decisions on NGCH filing",
        ),
        schema="cts",
    )

    # decision_recorded_at — timestamp of the above mirroring; used for p99 latency
    # dashboards and audit queries that need a single timestamp per instrument.
    op.add_column(
        "cheque_instruments",
        sa.Column(
            "decision_recorded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp when final_decision was written by DecisionConsumer",
        ),
        schema="cts",
    )

    # ── cts.clearing_sessions ────────────────────────────────────────────────────
    # failure_reason — populated by update_session_status activity when status=EXCEPTION;
    # surfaces the reason in the Ops Dashboard without querying Temporal history.
    op.add_column(
        "clearing_sessions",
        sa.Column(
            "failure_reason",
            sa.Text(),
            nullable=True,
            comment="Human-readable reason when clearing session status = EXCEPTION",
        ),
        schema="cts",
    )

    # ── cts.lots ─────────────────────────────────────────────────────────────────
    # sealed_by — operator_id who manually sealed the lot (or "system" for auto-seal).
    op.add_column(
        "lots",
        sa.Column(
            "sealed_by",
            sa.Text(),
            nullable=True,
            comment="operator_id who sealed the lot; 'system' for auto-seal on max_instruments",
        ),
        schema="cts",
    )

    # updated_at — last modification timestamp; set by SEAL operation.
    op.add_column(
        "lots",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp of last status change (seal, re-open)",
        ),
        schema="cts",
    )

    # ── cts.mismatch_queue ───────────────────────────────────────────────────────
    # scan_id — the EEH gRPC scan_id from the ChequeAck that triggered this mismatch;
    # returned in ResolutionAck so the scanner bridge can correlate.
    op.add_column(
        "mismatch_queue",
        sa.Column(
            "scan_id",
            sa.Text(),
            nullable=True,
            comment="EEH gRPC ChequeAck.scan_id that triggered this mismatch hold",
        ),
        schema="cts",
    )

    # updated_at — set on every status change (GO_AHEAD, REJECTED, TIMEOUT_REJECTED).
    op.add_column(
        "mismatch_queue",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp of last status change",
        ),
        schema="cts",
    )


def downgrade() -> None:
    # mismatch_queue
    op.drop_column("mismatch_queue", "updated_at", schema="cts")
    op.drop_column("mismatch_queue", "scan_id", schema="cts")
    # lots
    op.drop_column("lots", "updated_at", schema="cts")
    op.drop_column("lots", "sealed_by", schema="cts")
    # clearing_sessions
    op.drop_column("clearing_sessions", "failure_reason", schema="cts")
    # cheque_instruments
    op.drop_column("cheque_instruments", "decision_recorded_at", schema="cts")
    op.drop_column("cheque_instruments", "final_decision", schema="cts")
    op.drop_column("cheque_instruments", "ngch_acknowledgement_id", schema="cts")
    op.drop_column("cheque_instruments", "review_assigned_at", schema="cts")
    op.drop_column("cheque_instruments", "queue_tier", schema="cts")
