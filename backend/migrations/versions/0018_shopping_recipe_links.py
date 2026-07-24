"""Link generated shopping items back to their recipe ingredients.

Revision ID: 0018_shopping_recipe_links
Revises: 0017_quarantine_urls
"""

import sqlalchemy as sa
from alembic import op


revision = "0018_shopping_recipe_links"
down_revision = "0017_quarantine_urls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_ingredient") as batch:
        batch.add_column(
            sa.Column(
                "shopping_measurement_overridden",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("shopping_group_key", sa.String(length=240), nullable=True))
    with op.batch_alter_table("shopping_item") as batch:
        batch.add_column(
            sa.Column(
                "source_ingredients",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
    op.execute(
        sa.text(
            "UPDATE shopping_list SET rebuild_recommended = true "
            "WHERE active = true AND meal_plan_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("shopping_item") as batch:
        batch.drop_column("source_ingredients")
    with op.batch_alter_table("recipe_ingredient") as batch:
        batch.drop_column("shopping_group_key")
        batch.drop_column("shopping_measurement_overridden")
