"""ATM health snapshots and anomaly detection records.

atm_health_snapshots — periodic health state captured from EJ analysis
atm_health_anomalies — detected anomalies (threshold breaches, error spikes)

ATMHealthWorkflow runs hourly, analyses ej_canonical_records for error patterns,
and writes to these tables. Anomalies trigger notification-service alerts.

Revision ID: 20260618_ej_004
Revises: 20260618_ej_003
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_ej_004"
down_revision = "20260618_ej_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── atm_health_snapshots ───────────────────────────────────────────────
    # One row per ATMHealthWorkflow run per ATM.
    # Captures the health picture at a point in time for trend analysis.
    op.create_table(
        "atm_health_snapshots",
        sa.Column("snapshot_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("atm_id", sa.Text,
                  sa.ForeignKey("ej.atm_master.atm_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        # Workflow reference
        sa.Column("workflow_id", sa.Text, nullable=True),

        # Observation window
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_hours", sa.Integer, nullable=False, server_default="1"),

        # Transaction counts in window
        sa.Column("total_transactions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("successful_transactions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_transactions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("partial_dispense_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("card_retained_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("timeout_count", sa.Integer, nullable=False, server_default="0"),

        # Computed metrics
        sa.Column("success_rate", sa.Numeric(5, 4), nullable=True),
        # successful / total
        sa.Column("dispense_failure_rate", sa.Numeric(5, 4), nullable=True),

        # Cassette state at end of window
        sa.Column("cassette_states", JSONB, nullable=True),
        # {"cassette_1": {"denomination": 500, "count": 12, "status": "LOW"}, ...}
        sa.Column("cash_low_flag", sa.Boolean, nullable=False, server_default="false"),
        # True if any cassette below replenishment threshold

        # Hardware health
        sa.Column("hardware_errors", JSONB, nullable=True),
        # {"dispenser": 0, "card_reader": 2, "receipt_printer": 0}
        sa.Column("hardware_health_score", sa.Numeric(5, 4), nullable=True),
        # 1.0 = fully healthy, 0.0 = critical failure

        # Overall health verdict for this window
        sa.Column("health_verdict", sa.Text, nullable=False),
        # HEALTHY | DEGRADED | CRITICAL
        sa.Column("verdict_reason", sa.Text, nullable=True),

        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_health_snapshots_atm_window",
                    "atm_health_snapshots", ["atm_id", "window_end"], schema="ej")
    op.create_index("ix_ej_health_snapshots_bank_verdict",
                    "atm_health_snapshots", ["bank_id", "health_verdict", "snapshot_at"],
                    schema="ej")
    op.create_index("ix_ej_health_snapshots_cash_low",
                    "atm_health_snapshots", ["bank_id", "snapshot_at"],
                    postgresql_where=sa.text("cash_low_flag = true"), schema="ej")

    # ── atm_health_anomalies ───────────────────────────────────────────────
    # Detected anomalies — created when a health metric crosses a threshold.
    # Each anomaly triggers a notification via notification-service.
    op.create_table(
        "atm_health_anomalies",
        sa.Column("anomaly_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("atm_id", sa.Text,
                  sa.ForeignKey("ej.atm_master.atm_id"), nullable=False),
        sa.Column("bank_id", sa.Text, sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("snapshot_id", UUID(as_uuid=True),
                  sa.ForeignKey("ej.atm_health_snapshots.snapshot_id"), nullable=True),

        # Anomaly classification
        sa.Column("anomaly_type", sa.Text, nullable=False),
        # FAILURE_RATE_SPIKE | CASH_LOW | CASH_CRITICAL | HARDWARE_ERROR |
        # PARTIAL_DISPENSE_SPIKE | CARD_RETAINED_SPIKE | OFFLINE | PREDICTED_FAILURE

        sa.Column("severity", sa.Text, nullable=False),
        # INFO | WARN | CRITICAL

        # Observed vs threshold
        sa.Column("metric_name", sa.Text, nullable=False),
        # "failure_rate" | "cash_cassette_1_count" | "dispenser_errors"
        sa.Column("observed_value", sa.Numeric(10, 4), nullable=True),
        sa.Column("threshold_value", sa.Numeric(10, 4), nullable=True),

        # Predictive maintenance signal (if anomaly_type = PREDICTED_FAILURE)
        sa.Column("predicted_failure_window_hours", sa.Integer, nullable=True),
        sa.Column("prediction_confidence", sa.Numeric(5, 4), nullable=True),

        # Resolution
        sa.Column("status", sa.Text, nullable=False, server_default="'OPEN'"),
        # OPEN | NOTIFIED | ACKNOWLEDGED | RESOLVED | AUTO_RESOLVED
        sa.Column("acknowledged_by", sa.Text, nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),

        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="ej",
    )
    op.create_index("ix_ej_health_anomalies_atm_open",
                    "atm_health_anomalies", ["atm_id", "status"],
                    postgresql_where=sa.text("status IN ('OPEN', 'NOTIFIED')"), schema="ej")
    op.create_index("ix_ej_health_anomalies_bank_severity",
                    "atm_health_anomalies", ["bank_id", "severity", "detected_at"], schema="ej")
    op.create_index("ix_ej_health_anomalies_critical",
                    "atm_health_anomalies", ["bank_id", "detected_at"],
                    postgresql_where=sa.text("severity = 'CRITICAL' AND status = 'OPEN'"),
                    schema="ej")


def downgrade() -> None:
    op.drop_table("atm_health_anomalies", schema="ej")
    op.drop_table("atm_health_snapshots", schema="ej")
