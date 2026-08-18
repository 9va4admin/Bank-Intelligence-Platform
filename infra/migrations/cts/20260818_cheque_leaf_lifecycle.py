"""
Cheque Leaf Vault lifecycle tables + Account Vault Detail + Upload Batches.

New tables:
  cts.cheque_books            — one row per issued cheque book (seed data from CBS)
  cts.cheque_leaves           — one row per individual leaf; full lifecycle status
  cts.cheque_books_history    — snapshot before every UPDATE/DEACTIVATE on a book
  cts.cheque_leaves_history   — snapshot before every leaf status change
  cts.account_vault_detail    — one row per account holder (splits joint/corporate names
                                 out of cts.account_vault summary row)
  cts.account_vault_detail_history — snapshot before every holder detail change
  cts.vault_upload_batches    — audit row for each CSV/SFTP upload batch

Revision ID: 20260818_cheque_leaf_lifecycle
Revises:     20260811_account_vault_add_holder_names
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260818_cheque_leaf_lifecycle"
down_revision = "20260811_account_vault_add_holder_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # vault_upload_batches — created first; FK target for other tables
    # ------------------------------------------------------------------
    op.create_table(
        "vault_upload_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("vault_type", sa.Text(), nullable=False),
        # SIGNATURE | PPS | ACCOUNT_SUMMARY | ACCOUNT_DETAIL |
        # CHEQUE_BOOK | LEAF_STATUS | BLOOM
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("upload_channel", sa.Text(), nullable=False, server_default="UI"),
        # UI | SFTP
        sa.Column("uploaded_by", sa.Text(), nullable=False),
        # "user:{user_id}" or "system:{feed_name}"
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        # PENDING | PROCESSING | COMPLETE | PARTIAL | FAILED
        sa.Column("rows_total", sa.Integer(), nullable=True),
        sa.Column("rows_processed", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("rows_failed", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("errors_json", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="cts",
    )
    op.create_index("ix_vault_upload_batches_bank_id",
                    "vault_upload_batches", ["bank_id", "created_at"],
                    schema="cts")

    # ------------------------------------------------------------------
    # cheque_books
    # ------------------------------------------------------------------
    op.create_table(
        "cheque_books",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("account_number_last4", sa.Text(), nullable=False),
        sa.Column("series_start", sa.Text(), nullable=False),
        sa.Column("series_end", sa.Text(), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=False),
        sa.Column("branch_code", sa.Text(), nullable=True),
        sa.Column("cbs_book_ref", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="cts",
    )
    op.create_unique_constraint(
        "uq_cheque_books_bank_account_series",
        "cheque_books",
        ["bank_id", "account_hash", "series_start"],
        schema="cts",
    )
    op.create_index("ix_cheque_books_bank_account",
                    "cheque_books", ["bank_id", "account_hash"],
                    schema="cts")

    # ------------------------------------------------------------------
    # cheque_books_history — snapshot before every book-level change
    # ------------------------------------------------------------------
    op.create_table(
        "cheque_books_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("series_start", sa.Text(), nullable=False),
        sa.Column("series_end", sa.Text(), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("branch_code", sa.Text(), nullable=True),
        sa.Column("cbs_book_ref", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("change_action", sa.Text(), nullable=False),
        # UPDATE_ONLY | DEACTIVATE | UPSERT
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="cts",
    )
    op.create_index("ix_cheque_books_history_book_id",
                    "cheque_books_history", ["book_id", "changed_at"],
                    schema="cts")

    # ------------------------------------------------------------------
    # cheque_leaves — full lifecycle per individual leaf
    # ------------------------------------------------------------------
    op.create_table(
        "cheque_leaves",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("account_number_last4", sa.Text(), nullable=False),
        sa.Column("cheque_number", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        # ACTIVE | STOPPED | LOST | STOLEN | CANCELLED |
        # PRESENTED | PAID | RETURNED | EXPIRED
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=True),
        # FK to cheque_books — nullable for pre-migration leaves
        sa.Column("series_start", sa.Text(), nullable=True),
        # denormalised for fast lookup without join
        sa.Column("instrument_id", sa.Text(), nullable=True),
        # set when PRESENTED — links to cheque_instruments
        sa.Column("return_reason_code", sa.Text(), nullable=True),
        # set on RETURNED
        sa.Column("exception_reason", sa.Text(), nullable=True),
        # free text for STOPPED/LOST/STOLEN/CANCELLED
        sa.Column("reported_by", sa.Text(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="cts",
    )
    op.create_unique_constraint(
        "uq_cheque_leaves_bank_account_cheque",
        "cheque_leaves",
        ["bank_id", "account_hash", "cheque_number"],
        schema="cts",
    )
    op.create_index("ix_cheque_leaves_bank_account",
                    "cheque_leaves", ["bank_id", "account_hash"],
                    schema="cts")
    op.create_index("ix_cheque_leaves_status",
                    "cheque_leaves", ["bank_id", "status"],
                    schema="cts")
    # For daily expired sweep: all ACTIVE leaves older than N months
    op.create_index("ix_cheque_leaves_active_issued",
                    "cheque_leaves", ["bank_id", "issued_date"],
                    postgresql_where=sa.text("status = 'ACTIVE'"),
                    schema="cts")

    # ------------------------------------------------------------------
    # cheque_leaves_history — snapshot before every status change
    # ------------------------------------------------------------------
    op.create_table(
        "cheque_leaves_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("leaf_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("cheque_number", sa.Text(), nullable=False),
        sa.Column("prev_status", sa.Text(), nullable=False),
        sa.Column("new_status", sa.Text(), nullable=False),
        sa.Column("change_action", sa.Text(), nullable=False),
        # INSERT_ONLY | DEACTIVATE | ASTRA_PRESENTED | ASTRA_PAID |
        # ASTRA_RETURNED | ASTRA_EXPIRED
        sa.Column("changed_by", sa.Text(), nullable=False),
        # "user:{id}" | "system:{feed}" | "astra:workflow"
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("instrument_id", sa.Text(), nullable=True),
        sa.Column("return_reason_code", sa.Text(), nullable=True),
        schema="cts",
    )
    op.create_index("ix_cheque_leaves_history_leaf_id",
                    "cheque_leaves_history", ["leaf_id", "changed_at"],
                    schema="cts")

    # ------------------------------------------------------------------
    # account_vault_detail — one row per account holder
    # ------------------------------------------------------------------
    op.create_table(
        "account_vault_detail",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("holder_seq", sa.Integer(), nullable=False, server_default="1"),
        # 1 = primary holder, 2+ = joint/additional
        sa.Column("holder_name_encrypted", sa.LargeBinary(), nullable=True),
        # pgcrypto AES-256 encrypted; decrypted only when can_view_pii()
        sa.Column("holder_name_display", sa.Text(), nullable=False),
        # "R***" — first initial + masked; always visible
        sa.Column("role", sa.Text(), nullable=False, server_default="PRIMARY"),
        # PRIMARY | JOINT | KARTA | COPARCENER | DIRECTOR |
        # TRUSTEE | AUTHORISED_SIGNATORY | GUARDIAN
        sa.Column("pan_last4", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="cts",
    )
    op.create_unique_constraint(
        "uq_account_vault_detail_holder",
        "account_vault_detail",
        ["bank_id", "account_hash", "holder_seq"],
        schema="cts",
    )
    op.create_index("ix_account_vault_detail_bank_account",
                    "account_vault_detail", ["bank_id", "account_hash"],
                    schema="cts")

    # ------------------------------------------------------------------
    # account_vault_detail_history
    # ------------------------------------------------------------------
    op.create_table(
        "account_vault_detail_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("detail_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column("account_hash", sa.Text(), nullable=False),
        sa.Column("holder_seq", sa.Integer(), nullable=True),
        sa.Column("holder_name_display", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("pan_last4", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("change_action", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="cts",
    )
    op.create_index("ix_account_vault_detail_history_detail_id",
                    "account_vault_detail_history", ["detail_id", "changed_at"],
                    schema="cts")


def downgrade() -> None:
    op.drop_table("account_vault_detail_history", schema="cts")
    op.drop_table("account_vault_detail", schema="cts")
    op.drop_table("cheque_leaves_history", schema="cts")
    op.drop_table("cheque_leaves", schema="cts")
    op.drop_table("cheque_books_history", schema="cts")
    op.drop_table("cheque_books", schema="cts")
    op.drop_table("vault_upload_batches", schema="cts")
