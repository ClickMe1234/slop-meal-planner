"""Remember user-confirmed pantry and shopping ingredient matches.

Revision ID: 0012_pantry_shopping_name_keys
Revises: 0011_shopping_pantry_conflicts
"""

import sqlalchemy as sa
from alembic import op


revision = "0012_pantry_shopping_name_keys"
down_revision = "0011_shopping_pantry_conflicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pantry_lot",
        sa.Column(
            "shopping_name_keys",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("pantry_lot", "shopping_name_keys")
