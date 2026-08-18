"""Add recipe-specific planner serving constraints.

Revision ID: 0024_recipe_serving_constraints
Revises: 0023_member_meal_groups
"""

import sqlalchemy as sa
from alembic import op


revision = "0024_recipe_serving_constraints"
down_revision = "0023_member_meal_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_version") as batch_op:
        batch_op.add_column(sa.Column("minimum_servings", sa.Numeric(8, 2), nullable=True))
        batch_op.add_column(sa.Column("serving_increment", sa.Numeric(8, 2), nullable=True))
        batch_op.create_check_constraint(
            "ck_recipe_version_serving_constraints",
            "(minimum_servings IS NULL AND serving_increment IS NULL) OR "
            "(minimum_servings IS NOT NULL AND serving_increment IS NOT NULL AND "
            "minimum_servings BETWEEN 0.25 AND 2 AND serving_increment BETWEEN 0.25 AND 2)",
        )


def downgrade() -> None:
    with op.batch_alter_table("recipe_version") as batch_op:
        batch_op.drop_constraint(
            "ck_recipe_version_serving_constraints", type_="check"
        )
        batch_op.drop_column("serving_increment")
        batch_op.drop_column("minimum_servings")
