"""Add recipe meal types and shopping exclusions.

Revision ID: 0002_recipe_meal_types
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op


revision = "0002_recipe_meal_types"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 builds from live metadata, so a brand-new database may
    # already contain these objects. Existing 0001 deployments do not.
    inspector = sa.inspect(op.get_bind())
    if "recipe_meal_type" not in inspector.get_table_names():
        op.create_table(
            "recipe_meal_type",
            sa.Column("recipe_id", sa.String(length=36), nullable=False),
            sa.Column("meal_type", sa.String(length=40), nullable=False),
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("recipe_id", "meal_type"),
            sa.CheckConstraint(
                "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
                name="ck_recipe_meal_type_valid",
            ),
        )
        op.create_index(
            op.f("ix_recipe_meal_type_recipe_id"),
            "recipe_meal_type",
            ["recipe_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_recipe_meal_type_meal_type"),
            "recipe_meal_type",
            ["meal_type"],
            unique=False,
        )
    ingredient_columns = {
        column["name"] for column in inspector.get_columns("recipe_ingredient")
    }
    if "shopping_excluded" not in ingredient_columns:
        op.add_column(
            "recipe_ingredient",
            sa.Column(
                "shopping_excluded", sa.Boolean(), server_default=sa.false(), nullable=False
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = inspector.get_table_names()
    if "recipe_ingredient" in table_names:
        ingredient_columns = {
            column["name"] for column in inspector.get_columns("recipe_ingredient")
        }
        if "shopping_excluded" in ingredient_columns:
            op.drop_column("recipe_ingredient", "shopping_excluded")
    if "recipe_meal_type" in table_names:
        op.drop_table("recipe_meal_type")
