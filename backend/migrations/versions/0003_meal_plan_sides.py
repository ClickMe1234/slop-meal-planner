"""Add side recipe tags and planned meal components.

Revision ID: 0003_meal_plan_sides
Revises: 0002_recipe_meal_types
"""

import sqlalchemy as sa
from alembic import op


revision = "0003_meal_plan_sides"
down_revision = "0002_recipe_meal_types"
branch_labels = None
depends_on = None


def _unique_for(columns: list[str]) -> dict | None:
    inspector = sa.inspect(op.get_bind())
    wanted = set(columns)
    return next(
        (
            constraint
            for constraint in inspector.get_unique_constraints("meal_occurrence")
            if set(constraint.get("column_names") or []) == wanted
        ),
        None,
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    batch_columns = {column["name"] for column in inspector.get_columns("meal_batch")}
    if "parent_batch_id" not in batch_columns:
        op.add_column("meal_batch", sa.Column("parent_batch_id", sa.String(length=36)))
        op.create_foreign_key(
            "fk_meal_batch_parent_batch_id",
            "meal_batch",
            "meal_batch",
            ["parent_batch_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(
            op.f("ix_meal_batch_parent_batch_id"),
            "meal_batch",
            ["parent_batch_id"],
        )
    if "component_slot" not in batch_columns:
        op.add_column(
            "meal_batch",
            sa.Column("component_slot", sa.Integer(), server_default="0", nullable=False),
        )

    occurrence_columns = {
        column["name"] for column in inspector.get_columns("meal_occurrence")
    }
    if "component_slot" not in occurrence_columns:
        op.add_column(
            "meal_occurrence",
            sa.Column("component_slot", sa.Integer(), server_default="0", nullable=False),
        )
    old_unique = _unique_for(["meal_plan_id", "meal_date", "meal_type"])
    if old_unique and old_unique.get("name"):
        op.drop_constraint(old_unique["name"], "meal_occurrence", type_="unique")
    if not _unique_for(["meal_plan_id", "meal_date", "meal_type", "component_slot"]):
        op.create_unique_constraint(
            "uq_meal_occurrence_component",
            "meal_occurrence",
            ["meal_plan_id", "meal_date", "meal_type", "component_slot"],
        )

    checks = sa.inspect(op.get_bind()).get_check_constraints("recipe_meal_type")
    meal_type_check = next(
        (item for item in checks if item.get("name") == "ck_recipe_meal_type_valid"),
        None,
    )
    if meal_type_check and "side" not in (meal_type_check.get("sqltext") or "").lower():
        op.drop_constraint(
            "ck_recipe_meal_type_valid", "recipe_meal_type", type_="check"
        )
        op.create_check_constraint(
            "ck_recipe_meal_type_valid",
            "recipe_meal_type",
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'side')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM recipe_meal_type WHERE meal_type = 'side'")
    op.drop_constraint(
        "ck_recipe_meal_type_valid", "recipe_meal_type", type_="check"
    )
    op.create_check_constraint(
        "ck_recipe_meal_type_valid",
        "recipe_meal_type",
        "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
    )
    component_unique = _unique_for(
        ["meal_plan_id", "meal_date", "meal_type", "component_slot"]
    )
    if component_unique and component_unique.get("name"):
        op.drop_constraint(component_unique["name"], "meal_occurrence", type_="unique")
    op.drop_column("meal_occurrence", "component_slot")
    op.create_unique_constraint(
        "uq_meal_occurrence_slot",
        "meal_occurrence",
        ["meal_plan_id", "meal_date", "meal_type"],
    )
    op.drop_index(op.f("ix_meal_batch_parent_batch_id"), table_name="meal_batch")
    op.drop_constraint("fk_meal_batch_parent_batch_id", "meal_batch", type_="foreignkey")
    op.drop_column("meal_batch", "component_slot")
    op.drop_column("meal_batch", "parent_batch_id")
