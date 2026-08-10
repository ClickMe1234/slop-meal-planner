"""Reconcile the removed Flow table branch with persistent sessions.

Revision ID: 0021_reconcile_flow
Revises: 0020_recipe_method_flow_tables, 0020_persistent_sessions
"""

import sqlalchemy as sa
from alembic import op


revision = "0021_reconcile_flow"
down_revision = ("0020_recipe_method_flow_tables", "0020_persistent_sessions")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_recipe_method_table_snapshot_status",
        table_name="recipe_method_table_snapshot",
    )
    op.drop_index(
        "ix_recipe_method_table_snapshot_recipe_method_snapshot_id",
        table_name="recipe_method_table_snapshot",
    )
    op.drop_table("recipe_method_table_snapshot")


def downgrade() -> None:
    op.create_table(
        "recipe_method_table_snapshot",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recipe_method_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["recipe_method_snapshot_id"], ["recipe_method_snapshot.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recipe_method_table_snapshot_recipe_method_snapshot_id",
        "recipe_method_table_snapshot",
        ["recipe_method_snapshot_id"],
        unique=True,
    )
    op.create_index(
        "ix_recipe_method_table_snapshot_status",
        "recipe_method_table_snapshot",
        ["status"],
        unique=False,
    )
