"""
Add signatory_id to cts.signature_embeddings and create cts.account_signatories.

Before (migration 015):
  signature_embeddings keyed by (bank_id, account_hash, specimen_index).
  All specimens for all signatories of an account lumped in one flat list.
  Redis key: sig:{bank_id}:{hmac} — no signatory dimension.

After:
  signature_embeddings keyed by (bank_id, account_hash, signatory_id, specimen_index).
  One signatory_id per authorised signatory; up to 9 specimens per signatory.
  Redis key: sig:{bank_id}:{hmac}:{signatory_id} — one key per signatory.

  account_signatories: mandate rule per account
    ANY_ONE       — any one signatory match satisfies (default, single-signatory retail)
    ALL_REQUIRED  — every registered signatory must match
    QUORUM_N_OF_M — N of M must match; N stored in quorum_n column

Data migration:
  Existing rows get signatory_id = 'PRIMARY' (correct for single-signatory accounts).
  Redis keys are NOT migrated — VaultSyncWorkflow rebuilds Redis on next run.

Revision ID: 20260810_017
Revises: 20260723_015
"""
from alembic import op
import sqlalchemy as sa

revision = "20260810_017"
down_revision = "20260723_015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add signatory_id (existing rows default to 'PRIMARY')
    op.execute("""
        ALTER TABLE cts.signature_embeddings
        ADD COLUMN signatory_id TEXT NOT NULL DEFAULT 'PRIMARY'
    """)

    # 2. Drop old unique constraint (account_hash + specimen_index)
    op.execute("""
        ALTER TABLE cts.signature_embeddings
        DROP CONSTRAINT uq_sig_emb_account_specimen
    """)

    # 3. New unique constraint includes signatory_id
    op.execute("""
        ALTER TABLE cts.signature_embeddings
        ADD CONSTRAINT uq_sig_emb_account_signatory_specimen
        UNIQUE (bank_id, account_hash, signatory_id, specimen_index)
    """)

    # 4. Update lookup index to include signatory_id
    op.execute("DROP INDEX IF EXISTS idx_sig_emb_lookup")
    op.execute("""
        CREATE INDEX idx_sig_emb_lookup
        ON cts.signature_embeddings (bank_id, account_hash, signatory_id)
    """)

    # 5. account_signatories — mandate rules and signatory roster per account
    op.execute("""
        CREATE TABLE cts.account_signatories (
            id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
            bank_id         TEXT        NOT NULL,
            account_hash    TEXT        NOT NULL,
            signatory_id    TEXT        NOT NULL,
            role            TEXT        NOT NULL DEFAULT 'PRIMARY',
            name_masked     TEXT        NOT NULL DEFAULT '***',
            mandate_rule    TEXT        NOT NULL DEFAULT 'ANY_ONE'
                            CHECK (
                                mandate_rule IN ('ANY_ONE', 'ALL_REQUIRED')
                                OR mandate_rule LIKE 'QUORUM_%'
                            ),
            quorum_n        SMALLINT    NOT NULL DEFAULT 1 CHECK (quorum_n >= 1),
            is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
            synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (bank_id, account_hash, signatory_id)
        )
    """)

    op.execute("""
        CREATE INDEX idx_acct_sig_lookup
        ON cts.account_signatories (bank_id, account_hash)
        WHERE is_active = TRUE
    """)

    op.execute("""
        CREATE INDEX idx_acct_sig_bank_active
        ON cts.account_signatories (bank_id, is_active)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_acct_sig_bank_active")
    op.execute("DROP INDEX IF EXISTS idx_acct_sig_lookup")
    op.execute("DROP TABLE IF EXISTS cts.account_signatories")

    op.execute("DROP INDEX IF EXISTS idx_sig_emb_lookup")
    op.execute("""
        ALTER TABLE cts.signature_embeddings
        DROP CONSTRAINT IF EXISTS uq_sig_emb_account_signatory_specimen
    """)
    op.execute("""
        ALTER TABLE cts.signature_embeddings
        ADD CONSTRAINT uq_sig_emb_account_specimen
        UNIQUE (bank_id, account_hash, specimen_index)
    """)
    op.execute("""
        CREATE INDEX idx_sig_emb_lookup
        ON cts.signature_embeddings (bank_id, account_hash)
    """)
    op.execute("""
        ALTER TABLE cts.signature_embeddings
        DROP COLUMN signatory_id
    """)
