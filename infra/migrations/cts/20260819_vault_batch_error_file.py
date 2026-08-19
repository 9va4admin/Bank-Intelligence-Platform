"""
vault_upload_batches — add error_file_path column.

When rows_failed > 0, VaultUploadProcessor writes the full error list
to MinIO as a CSV and stores the object key here. The download endpoint
streams from MinIO when this column is non-NULL, falling back to the
errors_json JSONB column for older batches (backwards-compatible).

Revision ID: 20260819_vault_batch_error_file
Revises:     20260818_mismatch_queue_add_bank_id
"""
from alembic import op
import sqlalchemy as sa

revision = "20260819_vault_batch_error_file"
down_revision = "20260818_mismatch_queue_add_bank_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vault_upload_batches",
        sa.Column(
            "error_file_path",
            sa.Text(),
            nullable=True,
            comment=(
                "MinIO object key for full error CSV "
                "(e.g. saraswat-coop/vault-errors/<batch_id>.csv). "
                "NULL when rows_failed = 0 or MinIO unavailable."
            ),
        ),
        schema="cts",
    )
    op.create_index(
        "ix_vault_upload_batches_error_file_path",
        "vault_upload_batches",
        ["error_file_path"],
        schema="cts",
        postgresql_where=sa.text("error_file_path IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vault_upload_batches_error_file_path",
        table_name="vault_upload_batches",
        schema="cts",
    )
    op.drop_column("vault_upload_batches", "error_file_path", schema="cts")
