"""Add calorie boosts and guest servings to meal plans.

Revision ID: 0016_plan_day_adjustments
Revises: 0015_integration_credentials
"""

import sqlalchemy as sa
from alembic import op


revision = "0016_plan_day_adjustments"
down_revision = "0015_integration_credentials"
branch_labels = None
depends_on = None


def _batch_options() -> dict:
    if op.get_bind().dialect.name != "sqlite":
        return {}
    return {"recreate": "always"}


def upgrade() -> None:
    with op.batch_alter_table("meal_plan", **_batch_options()) as batch_op:
        batch_op.add_column(
            sa.Column("calorie_boosts", sa.JSON(), server_default="[]", nullable=False)
        )
        batch_op.add_column(
            sa.Column("guest_days", sa.JSON(), server_default="[]", nullable=False)
        )
    with op.batch_alter_table("meal_occurrence", **_batch_options()) as batch_op:
        batch_op.add_column(
            sa.Column(
                "guest_servings", sa.Numeric(8, 2), server_default="0", nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("meal_occurrence", **_batch_options()) as batch_op:
        batch_op.drop_column("guest_servings")
    with op.batch_alter_table("meal_plan", **_batch_options()) as batch_op:
        batch_op.drop_column("guest_days")
        batch_op.drop_column("calorie_boosts")
