"""Add immutable recipe method snapshots and user cooking preferences.

Revision ID: 0019_recipe_methods
Revises: 0018_shopping_recipe_links
"""

from __future__ import annotations

import hashlib
import json
import uuid

import sqlalchemy as sa
from alembic import op


revision = "0019_recipe_methods"
down_revision = "0018_shopping_recipe_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("app_user") as batch:
        batch.add_column(
            sa.Column("method_view_preference", sa.String(length=12), nullable=False, server_default="summary")
        )
        batch.add_column(
            sa.Column("measurement_system", sa.String(length=12), nullable=False, server_default="source")
        )
        batch.add_column(
            sa.Column("method_tutorial_version_seen", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("recipe_ingredient") as batch:
        batch.add_column(sa.Column("lineage_id", sa.String(length=36), nullable=True))

    connection = op.get_bind()
    ingredient_rows = connection.execute(sa.text("SELECT id FROM recipe_ingredient")).fetchall()
    for row in ingredient_rows:
        connection.execute(
            sa.text("UPDATE recipe_ingredient SET lineage_id = :lineage_id WHERE id = :id"),
            {"lineage_id": str(uuid.uuid4()), "id": row[0]},
        )

    with op.batch_alter_table("recipe_ingredient") as batch:
        batch.alter_column("lineage_id", existing_type=sa.String(length=36), nullable=False)
        batch.create_index("ix_recipe_ingredient_lineage_id", ["lineage_id"], unique=False)
        batch.create_unique_constraint(
            "uq_recipe_ingredient_version_lineage", ["recipe_version_id", "lineage_id"]
        )

    op.create_table(
        "recipe_method_snapshot",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recipe_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_kind", sa.String(length=30), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_blocks", sa.JSON(), nullable=False),
        sa.Column("source_checksum", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("household_notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipe_version_id"], ["recipe_version.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_version_id"),
    )
    op.create_index(
        "ix_recipe_method_snapshot_recipe_version_id",
        "recipe_method_snapshot",
        ["recipe_version_id"],
        unique=True,
    )
    op.create_index(
        "ix_recipe_method_snapshot_status", "recipe_method_snapshot", ["status"], unique=False
    )

    rows = connection.execute(
        sa.text(
            "SELECT id, custom_instructions FROM recipe_version "
            "WHERE custom_instructions IS NOT NULL AND trim(custom_instructions) <> ''"
        )
    ).fetchall()
    for recipe_version_id, instructions in rows:
        text = str(instructions)
        block = {"id": "block-1", "position": 0, "heading": None, "text": text}
        coverage = {"total_clauses": 1, "represented": 0, "omitted": 0, "unreviewed": 1}
        document = {
            "schema_version": 1,
            "annotations": [],
            "omissions": [],
            "stages": [{"id": "stage-1", "title": "Method", "position": 0}],
            "actions": [],
            "ingredient_bindings": [],
            "edges": [],
        }
        connection.execute(
            sa.text(
                "INSERT INTO recipe_method_snapshot "
                "(id, recipe_version_id, source_kind, source_text, source_blocks, source_checksum, "
                "extractor_version, parser_version, status, confidence, coverage, document, created_at) "
                "VALUES (:id, :recipe_version_id, 'custom', :source_text, :source_blocks, :checksum, "
                "'legacy-custom-instructions', 'method-rules-1', 'needs_review', NULL, :coverage, "
                ":document, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid.uuid4()),
                "recipe_version_id": recipe_version_id,
                "source_text": text,
                "source_blocks": json.dumps([block]),
                "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "coverage": json.dumps(coverage),
                "document": json.dumps(document),
            },
        )


def downgrade() -> None:
    op.drop_index("ix_recipe_method_snapshot_status", table_name="recipe_method_snapshot")
    op.drop_index("ix_recipe_method_snapshot_recipe_version_id", table_name="recipe_method_snapshot")
    op.drop_table("recipe_method_snapshot")
    with op.batch_alter_table("recipe_ingredient") as batch:
        batch.drop_constraint("uq_recipe_ingredient_version_lineage", type_="unique")
        batch.drop_index("ix_recipe_ingredient_lineage_id")
        batch.drop_column("lineage_id")
    with op.batch_alter_table("app_user") as batch:
        batch.drop_column("method_tutorial_version_seen")
        batch.drop_column("measurement_system")
        batch.drop_column("method_view_preference")
