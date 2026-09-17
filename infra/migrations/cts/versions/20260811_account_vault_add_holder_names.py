"""
account_vault: add holder_names JSONB column for joint account support.

Stores the display-masked name of every account holder (up to 4 names) as a
JSON array, e.g. ["R***", "V***"].  Used by validate_payee_account to match
the depositor's name on the deposit slip against ANY holder — not just the
primary holder stored in holder_name_display.

holder_name_display (existing) stays as-is — it is the primary holder display
string and is shown in the audit trail and UI.

holder_names (new) carries ALL holders including the primary.  On existing rows
the default is a JSON array wrapping holder_name_display so the column is never
empty for current vault entries.

Safe for rolling deploy:
  - old pods do not read holder_names — they use holder_name_display only
  - new pods fall back to [holder_name_display] if holder_names is empty or null

Revision ID: 20260811_account_vault_add_holder_names
Revises: 20260805_account_vault_add_status_and_name
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260811_account_vault_add_holder_names"
down_revision = "20260805_account_vault_add_status_and_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_vault",
        sa.Column(
            "holder_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="cts",
    )
    # Back-fill: wrap existing holder_name_display into a single-element array
    # so queries against holder_names work correctly for current single-holder rows.
    op.execute(
        """
        UPDATE cts.account_vault
        SET    holder_names = jsonb_build_array(holder_name_display)
        WHERE  holder_names = '[]'::jsonb
          AND  holder_name_display IS NOT NULL
          AND  holder_name_display != '***'
        """
    )


def downgrade() -> None:
    op.drop_column("account_vault", "holder_names", schema="cts")
