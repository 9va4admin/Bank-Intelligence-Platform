"""msv.mandate_rules — per-account mandate configuration used by BREEngine.

MandateRule (modules/msv/mandates/models.py) documents "originate from CBS and are stored in
msv.mandate_rules" — that table never existed. modules/msv/mandates/models.py's AccountMandateMeta
has never been constructible from real data anywhere in this codebase before today (confirmed: zero
call sites outside its own model file).

Revision ID: 20260922_mandate_rules
Revises: 20260709_create_msv_schema
Create Date: 2026-09-22
"""
import sqlalchemy as sa
from alembic import op

revision = "20260922_mandate_rules"
down_revision = "20260709_create_msv_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mandate_rules",
        sa.Column("bank_id", sa.Text(), nullable=False),
        sa.Column(
            "account_hash",
            sa.Text(),
            nullable=False,
            comment="HMAC-SHA256(bank_pepper, bank_id:account_number) — raw account never stored",
        ),
        sa.Column(
            "operation_type",
            sa.Text(),
            nullable=False,
            comment="S | E | F | A | J | JAS | L | T | P — from CBS account record",
        ),
        sa.Column(
            "rule_type",
            sa.Text(),
            nullable=False,
            comment="ALL_OF | ANY_N_OF | MANDATORY_PLUS_QUORUM | THRESHOLD_SPLIT | ROLE_BASED",
        ),
        sa.Column("mandatory_ids", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("required_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("required_roles", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("min_score", sa.Numeric(4, 3), nullable=False, server_default="0.80"),
        sa.Column("source", sa.Text(), nullable=False, server_default="CBS"),
        sa.Column("synced_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("bank_id", "account_hash", name="pk_mandate_rules"),
        sa.CheckConstraint(
            "rule_type IN ('ALL_OF','ANY_N_OF','MANDATORY_PLUS_QUORUM','THRESHOLD_SPLIT','ROLE_BASED')",
            name="ck_mandate_rules_rule_type",
        ),
        schema="msv",
    )


def downgrade() -> None:
    op.drop_table("mandate_rules", schema="msv")
