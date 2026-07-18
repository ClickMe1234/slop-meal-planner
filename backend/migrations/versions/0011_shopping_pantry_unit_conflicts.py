"""Persist pantry unit conflicts on generated shopping items.

Revision ID: 0011_shopping_pantry_unit_conflicts
Revises: 0010_pantry_use_soon
"""

import sqlalchemy as sa
from alembic import op


revision = "0011_shopping_pantry_unit_conflicts"
down_revision = "0010_pantry_use_soon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shopping_item",
        sa.Column(
            "pantry_unit_conflicts",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("shopping_item", "pantry_unit_conflicts")
