"""Create MSV schema — Multi-Signature Validation module tables.

Tables created:
  msv.signatory_embeddings  — per-specimen float32 embedding vectors (source of truth)
  msv.signatory_manifest    — per-signatory metadata (role, name_masked, specimen count)
  msv.enrollment_progress   — per-account enrollment status (ENROLLED | FAILED | SKIPPED)
  msv.enrollment_jobs       — bulk enrollment job tracking with progress counters

Security / PII notes:
  - account_number is NEVER stored. Only account_hash (HMAC-SHA256 with bank pepper).
  - name_masked is always the CBS-provided masked value (P*** format) — full names never stored.
  - embedding (BYTEA) is binary float32 data — not human-interpretable.
  - MinIO stores cheque/specimen images; only account_hash references them here.

Revision ID: 20260709_create_msv_schema
Revises: None (first MSV migration)
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "20260709_create_msv_schema"
down_revision = None   # first MSV migration; set to previous in real chain
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS msv")

    # -------------------------------------------------------------------------
    # msv.signatory_embeddings
    # Source of truth for all specimen embedding vectors.
    # PK: (bank_id, account_hash, signatory_id, specimen_idx) — 4-part composite
    # UPSERT pattern: re-enrollment overwrites embedding, clears revoked_at.
    # -------------------------------------------------------------------------
    op.create_table(
        "signatory_embeddings",
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "account_hash",
            sa.Text(),
            nullable=False,
            comment="HMAC-SHA256(bank_pepper, bank_id:account_number) — raw account never stored",
        ),
        sa.Column("signatory_id", sa.Text(), nullable=False),
        sa.Column(
            "specimen_idx",
            sa.Integer(),
            nullable=False,
            comment="0-based index of specimen within this signatory's set",
        ),
        sa.Column(
            "embedding",
            sa.LargeBinary(),
            nullable=False,
            comment="512-dimensional float32 embedding, little-endian numpy tobytes()",
        ),
        sa.Column(
            "operation_type",
            sa.Text(),
            nullable=False,
            comment="S | E | F | A | J | JAS | L | T | P — from CBS signatory record",
        ),
        sa.Column(
            "enrolled_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "revoked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Set when signatory is revoked; NULL means active",
        ),
        sa.PrimaryKeyConstraint(
            "bank_id", "account_hash", "signatory_id", "specimen_idx",
            name="pk_signatory_embeddings",
        ),
        schema="msv",
    )

    # Index: look up all active specimens for an account + signatory (common read path)
    op.create_index(
        "ix_msv_emb_account_signatory",
        "signatory_embeddings",
        ["bank_id", "account_hash", "signatory_id"],
        schema="msv",
    )

    # Partial index: only active (non-revoked) rows — used in load_from_postgres queries
    op.execute(
        """
        CREATE INDEX ix_msv_emb_active
        ON msv.signatory_embeddings (bank_id, account_hash, signatory_id, specimen_idx)
        WHERE revoked_at IS NULL
        """
    )

    # -------------------------------------------------------------------------
    # msv.signatory_manifest
    # Metadata layer: roles, name_masked, specimen count.
    # Separate from embeddings to allow manifest queries without loading binary data.
    # PK: (bank_id, account_hash, signatory_id)
    # -------------------------------------------------------------------------
    op.create_table(
        "signatory_manifest",
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "account_hash",
            sa.Text(),
            nullable=False,
            comment="HMAC-SHA256 of account number — raw account never stored",
        ),
        sa.Column("signatory_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, comment="CFO | DIRECTOR | TRUSTEE | etc."),
        sa.Column(
            "name_masked",
            sa.Text(),
            nullable=False,
            comment="P*** — first initial + *** masking, always from CBS; never full name",
        ),
        sa.Column(
            "specimen_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of active (non-revoked) specimen embeddings",
        ),
        sa.Column(
            "operation_type",
            sa.Text(),
            nullable=False,
            comment="Inherited from signatory_embeddings.operation_type on enroll",
        ),
        sa.Column(
            "enrolled_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Updated on re-enrollment or revocation",
        ),
        sa.PrimaryKeyConstraint(
            "bank_id", "account_hash", "signatory_id",
            name="pk_signatory_manifest",
        ),
        schema="msv",
    )

    # Index: list all signatories for an account (used in load_all_signatories)
    op.create_index(
        "ix_msv_manifest_account",
        "signatory_manifest",
        ["bank_id", "account_hash"],
        schema="msv",
    )

    # -------------------------------------------------------------------------
    # msv.enrollment_progress
    # Per-account enrollment lifecycle: NOT_ENROLLED → ENROLLED | FAILED | SKIPPED
    # PK: (bank_id, account_hash) — one record per account
    # UPSERT on re-enrollment: mark_enrolled / mark_failed both use ON CONFLICT DO UPDATE
    # -------------------------------------------------------------------------
    op.create_table(
        "enrollment_progress",
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "account_hash",
            sa.Text(),
            nullable=False,
            comment="HMAC-SHA256 of account number",
        ),
        sa.Column(
            "operation_type",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="Most recent operation_type enrolled; empty string before first enrollment",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="ENROLLED | FAILED | SKIPPED",
        ),
        sa.Column(
            "batch_id",
            sa.Text(),
            nullable=True,
            comment="batch_id of the most recent enrollment or delta sync",
        ),
        sa.Column(
            "enrolled_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp of last successful enrollment",
        ),
        sa.Column(
            "error_reason",
            sa.Text(),
            nullable=True,
            comment="Error detail if status = FAILED; NULL otherwise",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint(
            "bank_id", "account_hash",
            name="pk_enrollment_progress",
        ),
        schema="msv",
    )

    # Index: look up all FAILED accounts for a bank (for retry jobs)
    op.create_index(
        "ix_msv_progress_status",
        "enrollment_progress",
        ["bank_id", "status"],
        schema="msv",
    )

    # -------------------------------------------------------------------------
    # msv.enrollment_jobs
    # Bulk enrollment job lifecycle: RUNNING → COMPLETE | FAILED | PARTIAL
    # Created by BulkEnrollmentProcessor; polled by /v1/msv/enrollment/jobs/{id}/progress
    # -------------------------------------------------------------------------
    op.create_table(
        "enrollment_jobs",
        sa.Column("job_id", sa.Text(), nullable=False, comment="UUIDv7-based job identifier"),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "file_name",
            sa.Text(),
            nullable=False,
            comment="Original filename of the CBS export file",
        ),
        sa.Column(
            "file_hash",
            sa.Text(),
            nullable=True,
            comment="SHA-256 of the raw file — idempotency key; UNIQUE per bank",
        ),
        sa.Column(
            "file_type",
            sa.Text(),
            nullable=False,
            comment="FULL | DELTA | REVOCATION",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="RUNNING",
            comment="RUNNING | COMPLETE | FAILED | PARTIAL",
        ),
        sa.Column(
            "total_accounts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "processed_accounts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "enrolled_accounts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_accounts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_signatures",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total specimen images found in the file",
        ),
        sa.Column(
            "enrolled_signatures",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Specimen embeddings successfully stored",
        ),
        sa.Column(
            "current_operation_type",
            sa.Text(),
            nullable=True,
            comment="Most recently processed operation_type within the job",
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "completed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Set when status transitions to COMPLETE | FAILED | PARTIAL",
        ),
        sa.Column(
            "error_summary",
            sa.Text(),
            nullable=True,
            comment="Brief error description if status = FAILED; NULL otherwise",
        ),
        sa.PrimaryKeyConstraint("job_id", name="pk_enrollment_jobs"),
        schema="msv",
    )

    # Unique: one job per (bank_id, file_hash) — re-submitting the same file is idempotent
    op.create_unique_constraint(
        "uq_msv_jobs_bank_file_hash",
        "enrollment_jobs",
        ["bank_id", "file_hash"],
        schema="msv",
    )

    # Index: list all jobs for a bank ordered by started_at (common API query)
    op.create_index(
        "ix_msv_jobs_bank_started",
        "enrollment_jobs",
        ["bank_id", "started_at"],
        schema="msv",
    )


def downgrade() -> None:
    op.drop_index("ix_msv_jobs_bank_started", table_name="enrollment_jobs", schema="msv")
    op.drop_constraint("uq_msv_jobs_bank_file_hash", "enrollment_jobs", schema="msv", type_="unique")
    op.drop_table("enrollment_jobs", schema="msv")

    op.drop_index("ix_msv_progress_status", table_name="enrollment_progress", schema="msv")
    op.drop_table("enrollment_progress", schema="msv")

    op.drop_index("ix_msv_manifest_account", table_name="signatory_manifest", schema="msv")
    op.drop_table("signatory_manifest", schema="msv")

    op.execute("DROP INDEX IF EXISTS msv.ix_msv_emb_active")
    op.drop_index("ix_msv_emb_account_signatory", table_name="signatory_embeddings", schema="msv")
    op.drop_table("signatory_embeddings", schema="msv")
