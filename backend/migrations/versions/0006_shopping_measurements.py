"""Recommend rebuilding active lists for ingredient-aware measurements.

Revision ID: 0006_shopping_measurements
Revises: 0005_ingredient_parsing
"""

import sqlalchemy as sa
from alembic import op


revision = "0006_shopping_measurements"
down_revision = "0005_ingredient_parsing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    shopping_list = sa.table(
        "shopping_list",
        sa.column("active", sa.Boolean()),
        sa.column("rebuild_recommended", sa.Boolean()),
    )
    op.execute(
        shopping_list.update()
        .where(shopping_list.c.active.is_(True))
        .values(rebuild_recommended=True)
    )


def downgrade() -> None:
    # Existing lists may also need a rebuild for ingredient parsing or quantity
    # normalization, so a downgrade cannot safely clear this shared flag.
    pass
