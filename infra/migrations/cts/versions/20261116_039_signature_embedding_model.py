"""Record which embedder produced each stored signature vector.

Vectors from different embedders cannot be compared with each other, so a vault vector is only usable against the model that made it.
Every existing row was made by the generic ImageNet ResNet-18 embedder, which is therefore the column's default. The vault reads only rows
whose embedding_model matches the running embedder; anything else is a vault miss and is re-embedded from CBS. Additive only.

Revision ID: 20261116_039
Revises: 20261116_038
Create Date: 2026-11-16
"""
from alembic import op

revision = "20261116_039"
down_revision = "20261116_038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cts.signature_embeddings ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT 'resnet18-imagenet-generic'")


def downgrade() -> None:
    op.execute("ALTER TABLE cts.signature_embeddings DROP COLUMN IF EXISTS embedding_model")
