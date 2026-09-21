"""Consolidate vault tables that lived outside the applied chain.

The account-vault migrations (20260803 / 20260805 / 20260811) and the cheque-leaf
lifecycle migration (20260818) sit in infra/migrations/cts/ root, outside versions/,
so no environment ever created cts.account_vault / cts.cheque_books / cts.cheque_leaves
(+ history, vault_upload_batches) and the vaults ran without their tables.

This migration creates the FINAL schema of each, idempotently (IF NOT EXISTS / guard),
so it is safe on databases where they were created by hand.

Revision ID: 20260921_021
Revises: e2ad1328467c
Create Date: 2026-09-21
"""
import importlib.util
from pathlib import Path

from alembic import op

revision = "20260921_021"
down_revision = "e2ad1328467c"
branch_labels = None
depends_on = None

_ROOT = Path(__file__).resolve().parents[1]


def _table_missing(name: str) -> bool:
    return op.get_bind().exec_driver_sql(f"SELECT to_regclass('{name}')").scalar() is None


def upgrade() -> None:
    # ── cts.account_vault — final schema (20260803 + 20260805 + 20260811) ──────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS cts.account_vault (
            bank_id                TEXT        NOT NULL,
            account_hash           TEXT        NOT NULL,
            account_number_last4   TEXT        NOT NULL,
            account_type           TEXT        NOT NULL DEFAULT 'UNKNOWN',
            branch_code            TEXT        NOT NULL DEFAULT '',
            branch_name            TEXT        NOT NULL DEFAULT '',
            branch_ifsc            TEXT        NOT NULL DEFAULT '',
            branch_manager_email   TEXT        NOT NULL DEFAULT '',
            branch_contact_email   TEXT        NOT NULL DEFAULT '',
            branch_contact_phone   TEXT        NOT NULL DEFAULT '',
            last_synced_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            sync_source            TEXT        NOT NULL DEFAULT 'CBS',
            vault_version          INTEGER     NOT NULL DEFAULT 1,
            PRIMARY KEY (bank_id, account_hash)
        )
    """)
    op.execute("ALTER TABLE cts.account_vault ADD COLUMN IF NOT EXISTS account_status TEXT NOT NULL DEFAULT 'ACTIVE'")
    op.execute("ALTER TABLE cts.account_vault ADD COLUMN IF NOT EXISTS holder_name_display TEXT NOT NULL DEFAULT '***'")
    op.execute("ALTER TABLE cts.account_vault ADD COLUMN IF NOT EXISTS holder_names JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("CREATE INDEX IF NOT EXISTS idx_account_vault_branch_code ON cts.account_vault (bank_id, branch_code)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_account_vault_last_synced ON cts.account_vault (bank_id, last_synced_at DESC)")

    # ── cheque-leaf lifecycle tables (20260818) — run its own upgrade only if absent ─
    if _table_missing("cts.cheque_books"):
        spec = importlib.util.spec_from_file_location("_leaf_orphan", _ROOT / "20260818_cheque_leaf_lifecycle.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.upgrade()


def downgrade() -> None:
    # Only the account vault is dropped here; the cheque-leaf tables carry production
    # data once seeded and are dropped by their own dedicated downgrade if ever needed.
    op.execute("DROP TABLE IF EXISTS cts.account_vault")
