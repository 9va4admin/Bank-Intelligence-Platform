"""
agent_decisions — add steps_digest JSONB + registry_version columns.

steps_digest: full InstrumentDigest payload (ordered step trail) for every
processed cheque. Written once at workflow finalise() via persist_agent_decision.
Allows the passbook UI (GET /v1/cts/instruments/{id}/digest) to reconstruct the
complete PASS/FAIL/SKIPPED view without touching Immudb.

registry_version: REGISTRY_VERSION from modules/cts/pipeline/registry.py at the
time the digest was built — allows the passbook to handle schema evolution
(old digests have fewer steps than the current registry).

Revision ID: 20260819_agent_decisions_steps_digest
Revises:     20260819_vault_batch_error_file
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260819_agent_decisions_steps_digest"
down_revision = "20260819_vault_batch_error_file"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_decisions",
        sa.Column(
            "steps_digest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Full InstrumentDigest payload: ordered step trail with PASS/FAIL/SKIPPED "
                "per pipeline step. Populated by persist_agent_decision activity."
            ),
        ),
        schema="cts",
    )
    op.add_column(
        "agent_decisions",
        sa.Column(
            "registry_version",
            sa.String(10),
            nullable=True,
            comment="REGISTRY_VERSION from pipeline/registry.py when digest was built (e.g. '1.1').",
        ),
        schema="cts",
    )


def downgrade() -> None:
    op.drop_column("agent_decisions", "registry_version", schema="cts")
    op.drop_column("agent_decisions", "steps_digest", schema="cts")
