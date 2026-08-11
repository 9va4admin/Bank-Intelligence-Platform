"""branches: add contact fields + make pu_id nullable for bulk import

New columns on cts.branches:
  - address       TEXT  (full street address from branch directory CSV)
  - district      TEXT  (administrative district)
  - pin_code      TEXT  (6-digit PIN code)
  - phone_number  TEXT  (branch contact number)

Schema change:
  - pu_id: NOT NULL → nullable
    Reason: bulk CSV import loads branches before PU assignment. The
    bank_it_admin assigns PU mappings in a second step via the Admin UI.
    Layer 1 enforced constraint: scanning cannot be enabled on a branch
    unless pu_id is set (enforced at application layer, not DB layer).

Revision ID: 20260806_branches_add_contact_fields
Revises: 20260705_add_branches
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa

revision = "20260806_branches_add_contact_fields"
down_revision = "20260705_add_branches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add contact/location columns to support CSV branch directory import
    op.add_column(
        "branches",
        sa.Column("address", sa.Text(), nullable=True, comment="Full street address"),
        schema="cts",
    )
    op.add_column(
        "branches",
        sa.Column("district", sa.Text(), nullable=True, comment="Administrative district"),
        schema="cts",
    )
    op.add_column(
        "branches",
        sa.Column("pin_code", sa.Text(), nullable=True, comment="6-digit PIN code"),
        schema="cts",
    )
    op.add_column(
        "branches",
        sa.Column("phone_number", sa.Text(), nullable=True, comment="Branch contact phone number"),
        schema="cts",
    )

    # Make pu_id nullable — branches are imported before PU assignment
    op.alter_column(
        "branches",
        "pu_id",
        existing_type=sa.Text(),
        nullable=True,
        schema="cts",
    )


def downgrade() -> None:
    # Restore pu_id NOT NULL — first set any NULLs to a sentinel value
    # to avoid constraint violation on downgrade (safe: sentinel is obvious)
    op.execute(
        "UPDATE cts.branches SET pu_id = 'UNASSIGNED' WHERE pu_id IS NULL"
    )
    op.alter_column(
        "branches",
        "pu_id",
        existing_type=sa.Text(),
        nullable=False,
        schema="cts",
    )

    op.drop_column("branches", "phone_number", schema="cts")
    op.drop_column("branches", "pin_code", schema="cts")
    op.drop_column("branches", "district", schema="cts")
    op.drop_column("branches", "address", schema="cts")
