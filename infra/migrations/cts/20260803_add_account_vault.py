"""
add cts.account_vault table

Stores account operational profiles synced from CBS — branch contact details
needed for Hold notification routing without a live CBS call during IET window.

Revision: 20260803_add_account_vault
"""
from alembic import op
import sqlalchemy as sa

revision = "20260803_add_account_vault"
down_revision = "20260706_alter_ngch_submissions_add_pu"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_account_vault_branch_code
        ON cts.account_vault (bank_id, branch_code)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_account_vault_last_synced
        ON cts.account_vault (bank_id, last_synced_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.account_vault")
