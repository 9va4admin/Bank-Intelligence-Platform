"""scanner_configs: enable CRUD API with audit + Ops Dashboard notification.

The cts.scanner_configs table was created in 20260705_add_scanner_configs but
had no application CRUD layer — this migration adds nothing to the schema (table
already exists). The migration marker ensures Alembic treats the new router
(apps/api/routers/scanner_configs.py) as post-20260811 work, keeping the chain
linear and the history readable.

What changed at application layer (not schema):
  - apps/api/routers/scanner_configs.py: full CRUD, RBAC, Immudb audit, Kafka
  - AuditEventType: SCANNER_CONFIG_CREATED / UPDATED / DELETED
  - main.py: scanner_configs.router_v1 registered

Revision ID: 20260811_scanner_configs_crud
Revises:     20260811_branches_drop_folder_path
"""
from alembic import op

revision = "20260811_scanner_configs_crud"
down_revision = "20260811_branches_drop_folder_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema already exists from 20260705_add_scanner_configs.
    # This migration is a chain marker only.
    pass


def downgrade() -> None:
    pass
