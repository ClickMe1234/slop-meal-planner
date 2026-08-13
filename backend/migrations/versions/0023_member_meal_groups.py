"""Allow household members to have different planned meals.

Revision ID: 0023_member_meal_groups
Revises: 0022_normalize_method_view
"""

import sqlalchemy as sa
from alembic import op


revision = "0023_member_meal_groups"
down_revision = "0022_normalize_method_view"
branch_labels = None
depends_on = None


def _batch_options() -> dict:
    if op.get_bind().dialect.name != "sqlite":
        return {}
    return {"recreate": "always"}


def _unique_for(columns: list[str]) -> dict | None:
    wanted = set(columns)
    return next(
        (
            item
            for item in sa.inspect(op.get_bind()).get_unique_constraints(
                "meal_occurrence"
            )
            if set(item.get("column_names") or []) == wanted
        ),
        None,
    )


def upgrade() -> None:
    op.create_table(
        "household_meal_group_assignment",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column("meal_type", sa.String(40), nullable=False),
        sa.Column("group_key", sa.String(80), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["household_member.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id",
            "member_id",
            "meal_type",
            name="uq_household_meal_group_member_type",
        ),
    )
    op.create_index(
        "ix_household_meal_group_assignment_household_id",
        "household_meal_group_assignment",
        ["household_id"],
    )
    op.create_index(
        "ix_household_meal_group_assignment_member_id",
        "household_meal_group_assignment",
        ["member_id"],
    )

    old_unique = _unique_for(
        ["meal_plan_id", "meal_date", "meal_type", "component_slot"]
    )
    with op.batch_alter_table("meal_occurrence", **_batch_options()) as batch_op:
        batch_op.add_column(
            sa.Column(
                "meal_group_key",
                sa.String(80),
                server_default="shared",
                nullable=False,
            )
        )
        if old_unique:
            batch_op.drop_constraint(
                old_unique.get("name") or "uq_meal_occurrence_component",
                type_="unique",
            )
        batch_op.create_unique_constraint(
            "uq_meal_occurrence_group_component",
            [
                "meal_plan_id",
                "meal_date",
                "meal_type",
                "meal_group_key",
                "component_slot",
            ],
        )


def downgrade() -> None:
    new_unique = _unique_for(
        [
            "meal_plan_id",
            "meal_date",
            "meal_type",
            "meal_group_key",
            "component_slot",
        ]
    )
    with op.batch_alter_table("meal_occurrence", **_batch_options()) as batch_op:
        if new_unique:
            batch_op.drop_constraint(
                new_unique.get("name") or "uq_meal_occurrence_group_component",
                type_="unique",
            )
        batch_op.drop_column("meal_group_key")
        batch_op.create_unique_constraint(
            "uq_meal_occurrence_component",
            ["meal_plan_id", "meal_date", "meal_type", "component_slot"],
        )
    op.drop_index(
        "ix_household_meal_group_assignment_member_id",
        table_name="household_meal_group_assignment",
    )
    op.drop_index(
        "ix_household_meal_group_assignment_household_id",
        table_name="household_meal_group_assignment",
    )
    op.drop_table("household_meal_group_assignment")
