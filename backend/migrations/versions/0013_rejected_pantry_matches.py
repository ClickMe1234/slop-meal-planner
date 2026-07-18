"""Remember rejected pantry and shopping ingredient matches.

Revision ID: 0013_rejected_pantry_matches
Revises: 0012_pantry_shopping_name_keys
"""

import sqlalchemy as sa
from alembic import op


revision = "0013_rejected_pantry_matches"
down_revision = "0012_pantry_shopping_name_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pantry_lot",
        sa.Column(
            "rejected_shopping_name_keys",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("pantry_lot", "rejected_shopping_name_keys")
