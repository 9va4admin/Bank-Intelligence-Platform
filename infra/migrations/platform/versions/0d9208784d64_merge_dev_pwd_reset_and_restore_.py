"""merge dev_pwd_reset and restore_sessions_login branches

Revision ID: 0d9208784d64
Revises: 20260912_dev_pwd_reset, 20260916_restore_sessions_login
Create Date: 2026-09-17 22:53:22.354293

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d9208784d64'
down_revision: Union[str, Sequence[str], None] = ('20260912_dev_pwd_reset', '20260916_restore_sessions_login')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
