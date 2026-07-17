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


def _batch_options() -> dict:
    if op.get_bind().dialect.name != "sqlite":
        return {}
    return {
        "recreate": "always",
        "naming_convention": {
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        },
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    batch_columns = {column["name"] for column in inspector.get_columns("meal_batch")}
    batch_foreign_keys = inspector.get_foreign_keys("meal_batch")
    parent_foreign_key = next(
        (item for item in batch_foreign_keys if item.get("constrained_columns") == ["parent_batch_id"]),
        None,
    )
    needs_parent = "parent_batch_id" not in batch_columns
    needs_component = "component_slot" not in batch_columns
    if needs_parent or needs_component or parent_foreign_key is None:
        with op.batch_alter_table("meal_batch", **_batch_options()) as batch_op:
            if needs_parent:
                batch_op.add_column(sa.Column("parent_batch_id", sa.String(length=36)))
            if needs_component:
                batch_op.add_column(
                    sa.Column("component_slot", sa.Integer(), server_default="0", nullable=False)
                )
            if parent_foreign_key is None:
                batch_op.create_foreign_key(
                    "fk_meal_batch_parent_batch_id",
                    "meal_batch",
                    ["parent_batch_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
    inspector = sa.inspect(op.get_bind())
    batch_indexes = {item["name"] for item in inspector.get_indexes("meal_batch")}
    if "ix_meal_batch_parent_batch_id" not in batch_indexes:
        op.create_index("ix_meal_batch_parent_batch_id", "meal_batch", ["parent_batch_id"])

    occurrence_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("meal_occurrence")
    }
    old_unique = _unique_for(["meal_plan_id", "meal_date", "meal_type"])
    new_unique = _unique_for(["meal_plan_id", "meal_date", "meal_type", "component_slot"])
    needs_occurrence_component = "component_slot" not in occurrence_columns
    if needs_occurrence_component or old_unique or not new_unique:
        old_unique_name = (
            old_unique.get("name")
            if old_unique and old_unique.get("name")
            else "uq_meal_occurrence_meal_plan_id_meal_date_meal_type"
        )
        with op.batch_alter_table("meal_occurrence", **_batch_options()) as batch_op:
            if needs_occurrence_component:
                batch_op.add_column(
                    sa.Column("component_slot", sa.Integer(), server_default="0", nullable=False)
                )
            if old_unique:
                batch_op.drop_constraint(old_unique_name, type_="unique")
            if not new_unique:
                batch_op.create_unique_constraint(
                    "uq_meal_occurrence_component",
                    ["meal_plan_id", "meal_date", "meal_type", "component_slot"],
                )

    checks = sa.inspect(op.get_bind()).get_check_constraints("recipe_meal_type")
    meal_type_check = next(
        (item for item in checks if item.get("name") == "ck_recipe_meal_type_valid"),
        None,
    )
    if not meal_type_check or "side" not in (meal_type_check.get("sqltext") or "").lower():
        with op.batch_alter_table("recipe_meal_type", **_batch_options()) as batch_op:
            if meal_type_check:
                batch_op.drop_constraint("ck_recipe_meal_type_valid", type_="check")
            batch_op.create_check_constraint(
                "ck_recipe_meal_type_valid",
                "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack', 'side')",
            )


def downgrade() -> None:
    op.execute("DELETE FROM recipe_meal_type WHERE meal_type = 'side'")
    checks = sa.inspect(op.get_bind()).get_check_constraints("recipe_meal_type")
    meal_type_check = next(
        (item for item in checks if item.get("name") == "ck_recipe_meal_type_valid"),
        None,
    )
    with op.batch_alter_table("recipe_meal_type", **_batch_options()) as batch_op:
        if meal_type_check:
            batch_op.drop_constraint("ck_recipe_meal_type_valid", type_="check")
        batch_op.create_check_constraint(
            "ck_recipe_meal_type_valid",
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
        )
    component_unique = _unique_for(
        ["meal_plan_id", "meal_date", "meal_type", "component_slot"]
    )
    occurrence_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("meal_occurrence")
    }
    with op.batch_alter_table("meal_occurrence", **_batch_options()) as batch_op:
        if component_unique:
            batch_op.drop_constraint(
                component_unique.get("name") or "uq_meal_occurrence_component",
                type_="unique",
            )
        if "component_slot" in occurrence_columns:
            batch_op.drop_column("component_slot")
        batch_op.create_unique_constraint(
            "uq_meal_occurrence_slot",
            ["meal_plan_id", "meal_date", "meal_type"],
        )
    inspector = sa.inspect(op.get_bind())
    batch_columns = {column["name"] for column in inspector.get_columns("meal_batch")}
    batch_indexes = {item["name"] for item in inspector.get_indexes("meal_batch")}
    batch_foreign_keys = inspector.get_foreign_keys("meal_batch")
    parent_foreign_key = next(
        (item for item in batch_foreign_keys if item.get("constrained_columns") == ["parent_batch_id"]),
        None,
    )
    if "ix_meal_batch_parent_batch_id" in batch_indexes:
        op.drop_index("ix_meal_batch_parent_batch_id", table_name="meal_batch")
    with op.batch_alter_table("meal_batch", **_batch_options()) as batch_op:
        if parent_foreign_key:
            batch_op.drop_constraint(
                parent_foreign_key.get("name") or "fk_meal_batch_parent_batch_id",
                type_="foreignkey",
            )
        if "component_slot" in batch_columns:
            batch_op.drop_column("component_slot")
        if "parent_batch_id" in batch_columns:
            batch_op.drop_column("parent_batch_id")
