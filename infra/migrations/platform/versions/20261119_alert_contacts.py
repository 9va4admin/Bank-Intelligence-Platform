"""Alert contacts: the outside addresses and phone numbers alerts may be sent to, each verified by a code before it counts for Go-Live.

platform.alert_contacts  one row per (bank, address): the address encrypted, a keyed hash for lookup, a label, whether it is verified, and the pending code (stored only as a hash)

Additive only.

Revision ID: 20261119_alert_contacts
Revises: 20261119_readiness_proofs
Create Date: 2026-11-19
"""
from alembic import op

revision = "20261119_alert_contacts"
down_revision = "20261119_readiness_proofs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.alert_contacts (
            contact_id       TEXT PRIMARY KEY,
            bank_id          TEXT NOT NULL,
            kind             TEXT NOT NULL CHECK (kind IN ('email','phone')),
            address_enc      BYTEA NOT NULL,
            address_hash     TEXT NOT NULL,
            label            TEXT NOT NULL DEFAULT '',
            status           TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK (status IN ('UNVERIFIED','VERIFIED')),
            code_hash        TEXT,
            code_expires_at  TIMESTAMPTZ,
            attempts         INTEGER NOT NULL DEFAULT 0,
            verified_at      TIMESTAMPTZ,
            verified_by      TEXT,
            created_by       TEXT NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_contacts_address ON platform.alert_contacts (bank_id, address_hash)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform.alert_contacts")
