"""Add cooked batch weight.

Revision ID: 0009_cooked_batch_weight
Revises: 0008_recipe_publisher_tags
"""

import sqlalchemy as sa
from alembic import op


revision = "0009_cooked_batch_weight"
down_revision = "0008_recipe_publisher_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meal_batch",
        sa.Column("cooked_weight_grams", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meal_batch", "cooked_weight_grams")
