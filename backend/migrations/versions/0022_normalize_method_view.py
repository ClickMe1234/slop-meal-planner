"""Normalize the retired Flow table user preference.

Revision ID: 0022_normalize_method_view
Revises: 0021_reconcile_flow
"""

import sqlalchemy as sa
from alembic import op


revision = "0022_normalize_method_view"
down_revision = "0021_reconcile_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE app_user SET method_view_preference = 'summary' "
            "WHERE method_view_preference = 'table'"
        )
    )


def downgrade() -> None:
    # The previous schema accepts "summary", and the original preference
    # cannot be distinguished from an explicitly selected summary view.
    pass
