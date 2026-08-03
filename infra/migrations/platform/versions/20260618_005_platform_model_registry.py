"""Platform AI model registry and drift alerts.

Tables:
  platform.model_versions   — deployed model metadata per bank (mirrors MLflow)
  platform.model_drift_alerts — detected drift signals crossing alert thresholds

Both CTS (Qwen2-VL, GOT-OCR2, Siamese, XGBoost) and EJ (Llama 3.3 70B, BGE-M3)
models are tracked here. A single registry across modules enables:
  - Unified model health dashboard for ml_engineer role
  - Cross-module drift correlation (same Llama 3.3 70B serves both CTS reasoning
    and EJ parsing — drift in one affects both)
  - Deployment history for RBI audit (which model version made which decision)

Revision ID: 20260618_p_005
Revises: 20260618_p_004
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_p_005"
down_revision = "20260618_p_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── platform.model_versions ────────────────────────────────────────────
    # One row per deployed model version per bank.
    # MLflow is the authoritative model registry; this table mirrors
    # what is currently DEPLOYED (not all registered versions — only active).
    # BankOnboardingWorkflow populates this after confirming GPU availability.
    op.create_table(
        "model_versions",
        sa.Column("model_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),

        # Model identity
        sa.Column("model_name", sa.Text, nullable=False),
        # qwen2-vl-72b | got-ocr2 | siamese-signature | xgboost-fraud |
        # llama-3.3-70b | bge-m3 | qwen2.5-72b | internvl2-26b

        sa.Column("model_family", sa.Text, nullable=False),
        # VISION | OCR | SIGNATURE | FRAUD | REASONING | EMBEDDINGS | DISPUTE

        sa.Column("module", sa.Text, nullable=False),
        # CTS | EJ | SHARED
        # SHARED: Llama 3.3 70B is used by both CTS (fraud synthesis) and EJ (parsing)

        sa.Column("version_tag", sa.Text, nullable=False),
        # e.g. "v1.2.0", "awq-4bit-v3" — matches MLflow run tag
        sa.Column("mlflow_run_id", sa.Text, nullable=True),
        sa.Column("mlflow_model_uri", sa.Text, nullable=True),
        # mlflow://models/qwen2-vl-72b/3 — for audit traceability

        # GPU configuration
        sa.Column("gpu_profile", sa.Text, nullable=True),
        # PILOT (4×RTX4090) | PRODUCTION (4×A100)
        sa.Column("quantisation", sa.Text, nullable=True),
        # NONE | AWQ_4BIT | GPTQ_4BIT | GGUF_Q4_K_M

        # Inference queue assignment
        sa.Column("vllm_queue", sa.Text, nullable=True),
        # cts-vision | cts-ocr | cts-reasoning | ej-reasoning | ej-embeddings | ej-dispute

        # Performance metrics at deployment (used as baseline for drift detection)
        sa.Column("baseline_metrics", JSONB, nullable=True),
        # {
        #   "ocr_accuracy": 0.994,             -- OCR model
        #   "signature_precision": 0.971,       -- Siamese model
        #   "fraud_f1": 0.931,                  -- XGBoost
        #   "field_extraction_accuracy": 0.985, -- EJ LLM
        #   "embedding_recall_at_10": 0.943     -- BGE-M3
        # }

        # Deployment state
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deployed_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retire_reason", sa.Text, nullable=True),
        # DRIFT_EXCEEDED | UPGRADED | DECOMMISSIONED | PERFORMANCE_DEGRADED

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    # Only one active version per model per bank
    op.create_index("ix_platform_model_versions_active",
                    "model_versions", ["bank_id", "model_name"],
                    postgresql_where=sa.text("is_active = true"),
                    unique=True, schema="platform")
    op.create_index("ix_platform_model_versions_bank_module",
                    "model_versions", ["bank_id", "module"], schema="platform")
    op.create_index("ix_platform_model_versions_queue",
                    "model_versions", ["vllm_queue"],
                    postgresql_where=sa.text("is_active = true AND vllm_queue IS NOT NULL"),
                    schema="platform")

    # ── platform.model_drift_alerts ────────────────────────────────────────
    # Triggered when a model metric drops beyond the thresholds in CLAUDE.md §12:
    #   WARN:    metric drops > 2% over 7 days
    #   CRITICAL: metric drops > 5% over 7 days
    #   PULLED:  metric drops > 8% (model removed from production)
    # Thresholds come from config_service (never hardcoded).
    op.create_table(
        "model_drift_alerts",
        sa.Column("alert_id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("bank_id", sa.Text,
                  sa.ForeignKey("platform.banks.bank_id"), nullable=False),
        sa.Column("model_id", UUID(as_uuid=True),
                  sa.ForeignKey("platform.model_versions.model_id"), nullable=False),

        # Drift signal
        sa.Column("metric_name", sa.Text, nullable=False),
        # ocr_accuracy | fraud_f1 | signature_precision | field_extraction_accuracy |
        # fraud_false_positive_rate | fraud_false_negative_rate | embedding_recall_at_10

        sa.Column("window_days", sa.Integer, nullable=False, server_default="7"),
        sa.Column("baseline_value", sa.Numeric(8, 6), nullable=False),
        sa.Column("current_value", sa.Numeric(8, 6), nullable=False),
        sa.Column("drift_pct", sa.Numeric(6, 3), nullable=False),
        # Negative = degradation (e.g. -2.4 means 2.4% drop)

        sa.Column("severity", sa.Text, nullable=False),
        # WARN | CRITICAL | PULLED

        # Automated action taken
        sa.Column("auto_action_taken", sa.Text, nullable=True),
        # THRESHOLD_TIGHTENED | MODEL_PULLED | ALERT_SENT | NONE

        # Resolution
        sa.Column("status", sa.Text, nullable=False, server_default="OPEN"),
        # OPEN | ACKNOWLEDGED | INVESTIGATING | RESOLVED | AUTO_RESOLVED
        sa.Column("acknowledged_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform.users.user_id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),

        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        schema="platform",
    )
    op.create_index("ix_platform_model_drift_alerts_model",
                    "model_drift_alerts", ["model_id", "detected_at"], schema="platform")
    op.create_index("ix_platform_model_drift_alerts_open",
                    "model_drift_alerts", ["bank_id", "severity"],
                    postgresql_where=sa.text("status IN ('OPEN', 'ACKNOWLEDGED')"),
                    schema="platform")
    op.create_index("ix_platform_model_drift_alerts_pulled",
                    "model_drift_alerts", ["bank_id", "detected_at"],
                    postgresql_where=sa.text("severity = 'PULLED'"),
                    schema="platform")


def downgrade() -> None:
    op.drop_table("model_drift_alerts", schema="platform")
    op.drop_table("model_versions", schema="platform")
