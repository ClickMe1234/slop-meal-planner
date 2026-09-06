"""Serialize inventory mutations and persist retry operation results.

Revision ID: 0027_inventory_operation_safety
Revises: 0026_shopping_recipe_snapshots
"""

import sqlalchemy as sa
from alembic import op


revision = "0027_inventory_operation_safety"
down_revision = "0026_shopping_recipe_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("meal_batch") as batch_op:
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )

    op.create_table(
        "inventory_operation",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("operation_type", sa.String(length=40), nullable=False),
        sa.Column("operation_id", sa.String(length=160), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id",
            "operation_type",
            "operation_id",
            name="uq_inventory_operation_household_type_id",
        ),
    )
    op.create_index(
        "ix_inventory_operation_household_id",
        "inventory_operation",
        ["household_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_operation_household_id", table_name="inventory_operation"
    )
    op.drop_table("inventory_operation")
    with op.batch_alter_table("meal_batch") as batch_op:
        batch_op.drop_column("version")
