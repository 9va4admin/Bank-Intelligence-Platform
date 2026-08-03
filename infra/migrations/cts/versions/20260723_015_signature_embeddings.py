"""Add cts.signature_embeddings — persistent two-tier vault storage.

Stores 512-dim float32 signature embeddings (2048 bytes each) durably in
YugabyteDB so Redis is a hot cache only.  On Redis restart the vault sync
workflow warms Redis from this table — no re-embedding from CBS required.

Each account may have up to 3 specimens (specimen_index 0, 1, 2).
Keys are HMAC-SHA256 hashes — raw account numbers are never stored.

Revision ID: 20260723_015
Revises: 20260626_014
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260723_015"
down_revision = "20260626_014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE cts.signature_embeddings (
            id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            bank_id         TEXT            NOT NULL,
            account_hash    TEXT            NOT NULL,
            specimen_index  SMALLINT        NOT NULL CHECK (specimen_index BETWEEN 0 AND 9),
            embedding       BYTEA           NOT NULL,
            source          TEXT            NOT NULL CHECK (source IN ('CBS', 'CBS_FALLBACK')),
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
            CONSTRAINT uq_sig_emb_account_specimen
                UNIQUE (bank_id, account_hash, specimen_index)
        )
    """)

    op.execute("""
        CREATE INDEX idx_sig_emb_lookup
            ON cts.signature_embeddings (bank_id, account_hash)
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION cts.update_sig_emb_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        CREATE TRIGGER trg_sig_emb_updated_at
        BEFORE UPDATE ON cts.signature_embeddings
        FOR EACH ROW EXECUTE FUNCTION cts.update_sig_emb_updated_at()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sig_emb_updated_at ON cts.signature_embeddings")
    op.execute("DROP FUNCTION IF EXISTS cts.update_sig_emb_updated_at()")
    op.execute("DROP TABLE IF EXISTS cts.signature_embeddings")
