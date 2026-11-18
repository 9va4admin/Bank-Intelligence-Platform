"""Go-Live readiness proofs: the recorded result of each check that has to be run by a person or a routine, not just read (audit-path proof, test sends, DNS check).

platform.alert_readiness_proofs  one row per run: bank, kind, whether it passed, a small JSON of facts (never an address, phone number or secret), who ran it, when

Additive only.

Revision ID: 20261119_readiness_proofs
Revises: 20261118_oncall
Create Date: 2026-11-19
"""
from alembic import op

revision = "20261119_readiness_proofs"
down_revision = "20261118_oncall"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_readiness_proofs (
            proof_id   TEXT PRIMARY KEY,
            bank_id    TEXT NOT NULL,
            kind       TEXT NOT NULL,
            ok         BOOLEAN NOT NULL,
            detail     JSONB NOT NULL DEFAULT '{}'::jsonb,
            ran_by     TEXT NOT NULL,
            ran_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_readiness_proofs_latest ON platform.alert_readiness_proofs (bank_id, kind, ran_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.alert_readiness_proofs")
