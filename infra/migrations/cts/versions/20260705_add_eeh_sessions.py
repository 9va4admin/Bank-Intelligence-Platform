"""add cts.eeh_sessions table

EEHSession — tracks an authenticated upload session from the External Exchange Hub
(EEH) or Internal Exchange Hub (IEH). Created when a branch operator authenticates
and begins a scanning session. The session is tied to a mTLS client certificate
(branch cert issued by the SB's internal CA).

One session per branch per clearing day. If the session is EXPIRED or CLOSED, the
branch must re-authenticate to start a new one.

The session record drives:
  - Rate limit enforcement (max_upload_per_minute per session)
  - Instrument count tracking (total_uploaded vs total_accepted)
  - Audit trail for every scan batch within the session

Revision ID: 20260705_add_eeh_sessions
Revises: 20260705_add_mismatch_queue
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

revision = "20260705_add_eeh_sessions"
down_revision = "20260705_add_mismatch_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cts")

    op.create_table(
        "eeh_sessions",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "branch_id",
            sa.Text(),
            nullable=False,
            comment="FK to cts.branches.branch_id",
        ),
        sa.Column(
            "operator_id",
            sa.Text(),
            nullable=False,
            comment="Authenticated operator JWT sub claim — never email or name",
        ),
        sa.Column(
            "cert_fingerprint",
            sa.Text(),
            nullable=False,
            comment="SHA-256 fingerprint of the branch mTLS client certificate",
        ),
        sa.Column(
            "hub_type",
            sa.Text(),
            nullable=False,
            comment="EEH | IEH — which hub accepted this session",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="ACTIVE",
            comment="ACTIVE | CLOSED | EXPIRED | REVOKED",
        ),
        sa.Column(
            "clearing_date",
            sa.Date(),
            nullable=False,
            comment="The clearing date this session is associated with",
        ),
        sa.Column(
            "opened_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Session TTL: typically end of clearing day (bank-configurable, Layer 3)",
        ),
        sa.Column(
            "total_uploaded",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Count of instruments submitted to this hub in this session",
        ),
        sa.Column(
            "total_accepted",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Count of instruments successfully routed to OutwardScanWorkflow",
        ),
        sa.Column(
            "total_rejected",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Count rejected at CTS-2010 validation before workflow",
        ),
        sa.Column(
            "revocation_reason",
            sa.Text(),
            nullable=True,
            comment="Populated if status=REVOKED — e.g. CERT_REVOKED, OPERATOR_SUSPENDED",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
        schema="cts",
    )

    # One active session per branch per clearing day
    op.execute(
        """
        CREATE UNIQUE INDEX uq_eeh_sessions_branch_date_active
        ON cts.eeh_sessions (branch_id, clearing_date)
        WHERE status = 'ACTIVE'
        """
    )

    # Fast lookup: active sessions for a bank (hub startup: which branches are live)
    op.create_index(
        "ix_eeh_sessions_bank_status",
        "eeh_sessions",
        ["bank_id", "status"],
        schema="cts",
    )

    # Fast lookup: by cert fingerprint (mTLS verification path — the hot path)
    op.create_index(
        "ix_eeh_sessions_cert_fingerprint",
        "eeh_sessions",
        ["cert_fingerprint", "status"],
        schema="cts",
    )

    # TTL query: find expired sessions to sweep (scheduled job)
    op.create_index(
        "ix_eeh_sessions_expires_at",
        "eeh_sessions",
        ["expires_at"],
        schema="cts",
    )


def downgrade() -> None:
    op.drop_index("ix_eeh_sessions_expires_at", table_name="eeh_sessions", schema="cts")
    op.drop_index("ix_eeh_sessions_cert_fingerprint", table_name="eeh_sessions", schema="cts")
    op.drop_index("ix_eeh_sessions_bank_status", table_name="eeh_sessions", schema="cts")
    op.execute("DROP INDEX IF EXISTS cts.uq_eeh_sessions_branch_date_active")
    op.drop_table("eeh_sessions", schema="cts")
