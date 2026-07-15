"""Add versioned ingredient parsing and remembered shopping names.

Revision ID: 0005_ingredient_parsing
Revises: 0004_ingredient_names
"""

import sqlalchemy as sa
from alembic import op


revision = "0005_ingredient_parsing"
down_revision = "0004_ingredient_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipe_ingredient", sa.Column("parsed_food_phrase", sa.String(240)))
    op.add_column("recipe_ingredient", sa.Column("parser_version", sa.String(80)))
    op.add_column("recipe_ingredient", sa.Column("name_confidence", sa.Numeric(5, 4)))
    op.add_column(
        "recipe_ingredient",
        sa.Column("name_overridden", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "recipe_ingredient",
        sa.Column(
            "parser_name_keys",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "shopping_list",
        sa.Column("rebuild_recommended", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "shopping_item",
        sa.Column(
            "source_name_keys",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    table = op.create_table(
        "ingredient_name_override",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), sa.ForeignKey("household.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingredient_key", sa.String(240), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.UniqueConstraint("household_id", "ingredient_key"),
    )
    op.create_index(op.f("ix_ingredient_name_override_household_id"), table.name, ["household_id"])


def downgrade() -> None:
    op.drop_table("ingredient_name_override")
    op.drop_column("shopping_item", "source_name_keys")
    op.drop_column("shopping_list", "rebuild_recommended")
    op.drop_column("recipe_ingredient", "parser_name_keys")
    op.drop_column("recipe_ingredient", "name_overridden")
    op.drop_column("recipe_ingredient", "name_confidence")
    op.drop_column("recipe_ingredient", "parser_version")
    op.drop_column("recipe_ingredient", "parsed_food_phrase")
