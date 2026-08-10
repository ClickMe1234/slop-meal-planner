"""Track whether login sessions should persist and renew.

Revision ID: 0019_persistent_sessions
Revises: 0018_shopping_recipe_links
"""

import sqlalchemy as sa
from alembic import op


revision = "0019_persistent_sessions"
down_revision = "0018_shopping_recipe_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_session") as batch:
        batch.add_column(
            sa.Column(
                "remember_me",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user_session") as batch:
        batch.drop_column("remember_me")
