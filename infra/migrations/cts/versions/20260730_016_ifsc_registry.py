"""IFSC Registry — per-bank branch IFSC master table with SB/SMB scoping.

Stores the canonical list of valid IFSC codes for each ASTRA bank tenant:
  - SB entries: the sponsor bank's own branch IFSCs (smb_id = NULL)
  - SMB entries: each sub-member bank's branch IFSCs (smb_id = FK to sub_member_banks)

Used by validate_ifsc activity (inward pipeline) to confirm the NGCH presentment
IFSC is actually ours — catching wrongly-routed instruments before they consume
CBS, PPS, and signature vault resources.

Maker-checker: ops_manager creates (status=PENDING), bank_it_admin approves (status=ACTIVE).

Revision ID: 20260730_016
Revises: 20260723_015
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_016"
down_revision = "20260723_015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE cts.ifsc_registry (
            id              UUID            NOT NULL DEFAULT uuid_generate_v4(),
            bank_id         TEXT            NOT NULL,
            bank_type       TEXT            NOT NULL,
            smb_id          TEXT,

            ifsc_code       VARCHAR(11)     NOT NULL,
            branch_name     TEXT,
            branch_city     TEXT,
            micr_code       VARCHAR(9),

            is_active       BOOLEAN         NOT NULL DEFAULT FALSE,
            effective_from  DATE            NOT NULL DEFAULT CURRENT_DATE,
            effective_till  DATE,

            status          TEXT            NOT NULL DEFAULT 'PENDING',

            created_by      TEXT            NOT NULL,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            approved_by     TEXT,
            approved_at     TIMESTAMPTZ,
            updated_by      TEXT,
            updated_at      TIMESTAMPTZ,

            CONSTRAINT ifsc_registry_pk PRIMARY KEY (id),
            CONSTRAINT ifsc_registry_bank_ifsc_unique UNIQUE (bank_id, ifsc_code),
            CONSTRAINT ifsc_bank_type_check
                CHECK (bank_type IN ('SB', 'SMB')),
            CONSTRAINT ifsc_smb_consistency
                CHECK (
                    (bank_type = 'SB'  AND smb_id IS NULL) OR
                    (bank_type = 'SMB' AND smb_id IS NOT NULL)
                ),
            CONSTRAINT ifsc_status_check
                CHECK (status IN ('PENDING', 'ACTIVE', 'INACTIVE')),
            CONSTRAINT ifsc_code_format
                CHECK (ifsc_code ~ '^[A-Z]{4}[0-9A-Z]{7}$')
        )
    """)

    op.execute("""
        CREATE INDEX idx_ifsc_registry_bank_active
            ON cts.ifsc_registry (bank_id, is_active)
    """)

    op.execute("""
        CREATE INDEX idx_ifsc_registry_bank_ifsc
            ON cts.ifsc_registry (bank_id, ifsc_code)
        WHERE is_active = TRUE
    """)

    op.execute("""
        CREATE INDEX idx_ifsc_registry_smb
            ON cts.ifsc_registry (bank_id, smb_id)
        WHERE smb_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cts.ifsc_registry CASCADE")
