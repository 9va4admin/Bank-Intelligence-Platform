"""Add email/phone to platform.local_auth_accounts.

Without these, local-auth entities (smallest SMBs with no SAML/LDAP
directory) have no way to be resolved as notification recipients —
NotificationRoutingTable.get_spec() can correctly say "notify
bank_it_admin" but nothing can turn that into a real email or phone
number for locally-authenticated users. SAML/LDAP-backed entities have
their own, separate story (the bank's IdP is the source of truth there,
by design — see CLAUDE.md Security Principle "Identity via SAML 2.0,
ASTRA never stores passwords"); this migration only ever applies to the
local connector's own table, not a platform-wide user directory.

Additive, nullable — matches CLAUDE.md's migration strategy (new column:
nullable first, populate in app, tighten in a later release). Existing
rows and the existing LocalAuthConnector contract are unaffected;
email/phone are optional right up until a notification-routing consumer
actually needs them for a specific account.

Revision ID: 20260716_local_auth_contact
Revises: 20260705_local_auth
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260716_local_auth_contact"
down_revision = "20260705_local_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "local_auth_accounts",
        sa.Column("email", sa.Text(), nullable=True),
        schema="platform",
    )
    op.add_column(
        "local_auth_accounts",
        sa.Column("phone", sa.Text(), nullable=True),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_column("local_auth_accounts", "phone", schema="platform")
    op.drop_column("local_auth_accounts", "email", schema="platform")
