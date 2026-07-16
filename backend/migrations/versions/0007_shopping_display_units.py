"""Add shopper-controlled shopping measurement display units.

Revision ID: 0007_shopping_display_units
Revises: 0006_shopping_measurements
"""

import sqlalchemy as sa
from alembic import op


revision = "0007_shopping_display_units"
down_revision = "0006_shopping_measurements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shopping_item", sa.Column("density_g_per_ml", sa.Numeric(10, 5)))
    op.add_column("shopping_item", sa.Column("display_unit", sa.String(30)))
    op.execute("UPDATE shopping_item SET display_unit = unit")
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
    op.drop_column("shopping_item", "display_unit")
    op.drop_column("shopping_item", "density_g_per_ml")
