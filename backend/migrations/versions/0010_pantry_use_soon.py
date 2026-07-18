"""Add a user-controlled pantry use-soon flag.

Revision ID: 0010_pantry_use_soon
Revises: 0009_cooked_batch_weight
"""

import sqlalchemy as sa
from alembic import op


revision = "0010_pantry_use_soon"
down_revision = "0009_cooked_batch_weight"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pantry_lot",
        sa.Column("use_soon", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("pantry_lot", "use_soon")
