"""
add platform.layer2_change_requests table

Stores Layer 2 configuration change requests raised by bank_it_admin.
Layer 2 changes require ASTRA vendor review + CAB approval + Helm upgrade
(no hot-reload). Each request is audited to Immudb on creation.

Revision: 20260803_add_layer2_change_requests
"""
from alembic import op
import sqlalchemy as sa

revision = "20260803_add_layer2_change_requests"
down_revision = "20260803_add_account_vault"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.layer2_change_requests (
            request_id      TEXT        NOT NULL,
            bank_id         TEXT        NOT NULL,
            config_key      TEXT        NOT NULL,
            current_value   TEXT        NOT NULL DEFAULT '',
            requested_value TEXT        NOT NULL,
            reason          TEXT        NOT NULL,
            cab_ticket      TEXT        NOT NULL DEFAULT '',
            status          TEXT        NOT NULL DEFAULT 'PENDING_ASTRA_REVIEW',
            submitted_by    TEXT        NOT NULL,
            submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (request_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_layer2_change_requests_bank_id_at
            ON platform.layer2_change_requests (bank_id, submitted_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_layer2_change_requests_bank_id_at")
    op.execute("DROP TABLE IF EXISTS platform.layer2_change_requests")
