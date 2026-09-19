"""merge inward_live_cols and 019 branches

Revision ID: e2ad1328467c
Revises: 20260913_inward_live_cols, 20260916_019
Create Date: 2026-09-17 23:07:00.540631

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2ad1328467c'
down_revision: Union[str, Sequence[str], None] = ('20260913_inward_live_cols', '20260916_019')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
