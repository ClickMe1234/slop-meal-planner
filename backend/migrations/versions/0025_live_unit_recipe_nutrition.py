"""Store confirmed recipe nutrition unit conversions.

Revision ID: 0025_live_unit_recipe_nutrition
Revises: 0024_recipe_serving_constraints
"""

import sqlalchemy as sa
from alembic import op


revision = "0025_live_unit_recipe_nutrition"
down_revision = "0024_recipe_serving_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_version") as batch_op:
        batch_op.add_column(sa.Column("meal_types", sa.JSON(), nullable=True))

    with op.batch_alter_table("recipe_ingredient") as batch_op:
        batch_op.add_column(sa.Column("nutrition_input_unit", sa.String(40), nullable=True))
        batch_op.add_column(
            sa.Column("nutrition_basis_amount_per_unit", sa.Numeric(12, 4), nullable=True)
        )
        batch_op.add_column(sa.Column("nutrition_basis_unit", sa.String(20), nullable=True))
        batch_op.add_column(
            sa.Column("nutrition_conversion_source", sa.String(20), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_recipe_ingredient_nutrition_conversion_complete",
            "(nutrition_input_unit IS NULL AND nutrition_basis_amount_per_unit IS NULL "
            "AND nutrition_basis_unit IS NULL AND nutrition_conversion_source IS NULL) OR "
            "(nutrition_input_unit IS NOT NULL AND nutrition_basis_amount_per_unit > 0 "
            "AND nutrition_basis_unit IN ('g', 'ml') "
            "AND nutrition_conversion_source IN ('package', 'serving', 'manual'))",
        )

    op.create_table(
        "household_food_unit_conversion",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("food_record_id", sa.String(36), nullable=False),
        sa.Column("nutrition_input_unit", sa.String(40), nullable=False),
        sa.Column(
            "nutrition_basis_amount_per_unit", sa.Numeric(12, 4), nullable=False
        ),
        sa.Column("nutrition_basis_unit", sa.String(20), nullable=False),
        sa.Column("nutrition_conversion_source", sa.String(20), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "nutrition_basis_amount_per_unit > 0",
            name="ck_household_food_unit_conversion_amount_positive",
        ),
        sa.CheckConstraint(
            "nutrition_basis_unit IN ('g', 'ml')",
            name="ck_household_food_unit_conversion_basis_unit",
        ),
        sa.CheckConstraint(
            "nutrition_conversion_source IN ('package', 'serving', 'manual')",
            name="ck_household_food_unit_conversion_source",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["food_record_id"], ["food_record.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_household_food_unit_conversion_household_id",
        "household_food_unit_conversion",
        ["household_id"],
    )
    op.create_index(
        "ix_household_food_unit_conversion_food_record_id",
        "household_food_unit_conversion",
        ["food_record_id"],
    )
    op.create_index(
        "ix_household_food_unit_conversion_lookup",
        "household_food_unit_conversion",
        [
            "household_id",
            "food_record_id",
            "nutrition_input_unit",
            "created_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_household_food_unit_conversion_lookup",
        table_name="household_food_unit_conversion",
    )
    op.drop_index(
        "ix_household_food_unit_conversion_food_record_id",
        table_name="household_food_unit_conversion",
    )
    op.drop_index(
        "ix_household_food_unit_conversion_household_id",
        table_name="household_food_unit_conversion",
    )
    op.drop_table("household_food_unit_conversion")

    with op.batch_alter_table("recipe_version") as batch_op:
        batch_op.drop_column("meal_types")

    with op.batch_alter_table("recipe_ingredient") as batch_op:
        batch_op.drop_constraint(
            "ck_recipe_ingredient_nutrition_conversion_complete", type_="check"
        )
        batch_op.drop_column("nutrition_conversion_source")
        batch_op.drop_column("nutrition_basis_unit")
        batch_op.drop_column("nutrition_basis_amount_per_unit")
        batch_op.drop_column("nutrition_input_unit")
