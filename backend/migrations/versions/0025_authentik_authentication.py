"""Add Authentik identity links, mode-tagged sessions and logout replay state.

Revision ID: 0025_authentik_authentication
Revises: 0024_recipe_serving_constraints
"""

import sqlalchemy as sa
from alembic import op


revision = "0025_authentik_authentication"
down_revision = "0024_recipe_serving_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_identity",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("auth_method", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("username_at_link", sa.String(80), nullable=False),
        sa.Column("last_seen_username", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "auth_method",
            "issuer",
            "subject",
            name="uq_external_identity_method_issuer_subject",
        ),
        sa.UniqueConstraint(
            "user_id",
            "auth_method",
            "issuer",
            name="uq_external_identity_user_method_issuer",
        ),
    )
    op.create_index(
        "ix_external_identity_user_id", "external_identity", ["user_id"]
    )

    with op.batch_alter_table("user_session") as batch_op:
        batch_op.add_column(
            sa.Column(
                "auth_method",
                sa.String(32),
                nullable=False,
                server_default="builtin",
            )
        )
        batch_op.add_column(sa.Column("sid", sa.String(512), nullable=True))
        batch_op.add_column(sa.Column("encrypted_id_token", sa.Text(), nullable=True))
        batch_op.create_index("ix_user_session_sid", ["sid"])

    op.create_table(
        "oidc_logout_replay",
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("jti_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "issuer", "jti_hash", name="uq_oidc_logout_replay_issuer_jti"
        ),
    )
    op.create_index(
        "ix_oidc_logout_replay_expires_at",
        "oidc_logout_replay",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oidc_logout_replay_expires_at", table_name="oidc_logout_replay"
    )
    op.drop_table("oidc_logout_replay")
    with op.batch_alter_table("user_session") as batch_op:
        batch_op.drop_index("ix_user_session_sid")
        batch_op.drop_column("encrypted_id_token")
        batch_op.drop_column("sid")
        batch_op.drop_column("auth_method")
    op.drop_index("ix_external_identity_user_id", table_name="external_identity")
    op.drop_table("external_identity")
