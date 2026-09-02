"""Keep plan-only shopping snapshots out of editable recipe history.

Revision ID: 0026_shopping_recipe_snapshots
Revises: 0025_live_unit_recipe_nutrition
"""

import sqlalchemy as sa
from alembic import op


revision = "0026_shopping_recipe_snapshots"
down_revision = "0025_live_unit_recipe_nutrition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_version") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_shopping_snapshot",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("recipe_version") as batch_op:
        batch_op.drop_column("is_shopping_snapshot")
