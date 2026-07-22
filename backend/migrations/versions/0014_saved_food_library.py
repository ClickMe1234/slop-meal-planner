"""Add the household ingredient library and private food records.

Revision ID: 0014_saved_food_library
Revises: 0013_rejected_pantry_matches
"""

import sqlalchemy as sa
from alembic import op


revision = "0014_saved_food_library"
down_revision = "0013_rejected_pantry_matches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("food_record") as batch:
        batch.add_column(sa.Column("owner_household_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_food_record_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_food_record_owner_household",
            "household",
            ["owner_household_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_food_record_source",
            "food_record",
            ["source_food_record_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_food_record_owner_household_id", ["owner_household_id"])
        batch.create_index("ix_food_record_source_food_record_id", ["source_food_record_id"])

    op.create_table(
        "saved_food",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("food_record_id", sa.String(36), nullable=False),
        sa.Column("display_name", sa.String(300), nullable=False),
        sa.Column("serving_amount", sa.Numeric(10, 4), nullable=True),
        sa.Column("serving_unit", sa.String(20), nullable=True),
        sa.Column("planner_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("planner_recipe_id", sa.String(36), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["food_record_id"], ["food_record.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["planner_recipe_id"], ["recipe.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "food_record_id"),
    )
    op.create_index("ix_saved_food_household_id", "saved_food", ["household_id"])
    op.create_index("ix_saved_food_food_record_id", "saved_food", ["food_record_id"])
    op.create_index("ix_saved_food_planner_recipe_id", "saved_food", ["planner_recipe_id"])
    op.create_index(
        "ix_saved_food_household_name", "saved_food", ["household_id", "display_name"]
    )


def downgrade() -> None:
    op.drop_table("saved_food")
    with op.batch_alter_table("food_record") as batch:
        batch.drop_index("ix_food_record_source_food_record_id")
        batch.drop_index("ix_food_record_owner_household_id")
        batch.drop_constraint("fk_food_record_source", type_="foreignkey")
        batch.drop_constraint("fk_food_record_owner_household", type_="foreignkey")
        batch.drop_column("source_food_record_id")
        batch.drop_column("owner_household_id")
