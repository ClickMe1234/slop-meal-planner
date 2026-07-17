"""Add publisher recipe tags and metadata backfill state.

Revision ID: 0008_recipe_publisher_tags
Revises: 0007_shopping_display_units
"""

import sqlalchemy as sa
from alembic import op


revision = "0008_recipe_publisher_tags"
down_revision = "0007_shopping_display_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recipe",
        sa.Column(
            "publisher_metadata_status",
            sa.String(30),
            nullable=False,
            server_default="not_applicable",
        ),
    )
    op.add_column(
        "recipe",
        sa.Column("publisher_metadata_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("recipe", sa.Column("publisher_metadata_refreshed_at", sa.DateTime(timezone=True)))
    op.add_column("recipe", sa.Column("publisher_metadata_error", sa.String(500)))
    op.create_index(
        "ix_recipe_publisher_metadata_status",
        "recipe",
        ["publisher_metadata_status"],
    )
    op.execute(
        "UPDATE recipe SET publisher_metadata_status = 'pending' "
        "WHERE source_type = 'url' AND source_url IS NOT NULL"
    )

    op.create_table(
        "recipe_publisher_tag",
        sa.Column("recipe_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("normalised_value", sa.String(160), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "kind", "normalised_value"),
    )
    op.create_index(
        "ix_recipe_publisher_tag_recipe_id",
        "recipe_publisher_tag",
        ["recipe_id"],
    )
    op.create_index(
        "ix_recipe_publisher_tag_normalised_value",
        "recipe_publisher_tag",
        ["normalised_value"],
    )


def downgrade() -> None:
    op.drop_index("ix_recipe_publisher_tag_normalised_value", table_name="recipe_publisher_tag")
    op.drop_index("ix_recipe_publisher_tag_recipe_id", table_name="recipe_publisher_tag")
    op.drop_table("recipe_publisher_tag")
    op.drop_index("ix_recipe_publisher_metadata_status", table_name="recipe")
    op.drop_column("recipe", "publisher_metadata_error")
    op.drop_column("recipe", "publisher_metadata_refreshed_at")
    op.drop_column("recipe", "publisher_metadata_attempts")
    op.drop_column("recipe", "publisher_metadata_status")
