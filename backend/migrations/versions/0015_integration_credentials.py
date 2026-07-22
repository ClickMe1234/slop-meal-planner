"""Store encrypted household integration credentials.

Revision ID: 0015_integration_credentials
Revises: 0014_saved_food_library
"""

import sqlalchemy as sa
from alembic import op


revision = "0015_integration_credentials"
down_revision = "0014_saved_food_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_credential",
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "provider"),
    )
    op.create_index(
        "ix_integration_credential_household_id",
        "integration_credential",
        ["household_id"],
    )


def downgrade() -> None:
    op.drop_table("integration_credential")
