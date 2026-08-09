"""Add immutable Flow table projections for recipe methods.

Revision ID: 0020_recipe_method_flow_tables
Revises: 0019_recipe_methods
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op


revision = "0020_recipe_method_flow_tables"
down_revision = "0019_recipe_methods"
branch_labels = None
depends_on = None


def _label(text: str) -> str:
    cleaned = " ".join(text.split()).strip(" .;,")
    return cleaned[:120] or "operation"


def upgrade() -> None:
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
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["app_user.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["recipe_method_snapshot_id"], ["recipe_method_snapshot.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["app_user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_method_snapshot_id"),
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

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, document FROM recipe_method_snapshot "
            "WHERE id NOT IN (SELECT recipe_method_snapshot_id FROM recipe_method_table_snapshot)"
        )
    ).fetchall()
    for snapshot_id, raw_document in rows:
        document = json.loads(raw_document) if isinstance(raw_document, str) else (raw_document or {})
        actions = list(document.get("actions") or [])
        bindings = list(document.get("ingredient_bindings") or [])
        edges = list(document.get("edges") or [])
        action_ids = {str(action.get("id")) for action in actions}
        outgoing = {action_id: set() for action_id in action_ids}
        for edge in edges:
            source = str(edge.get("from_action_id"))
            target = str(edge.get("to_action_id"))
            if source in outgoing and target in action_ids:
                outgoing[source].add(target)
        labels = [
            {
                "action_id": str(action.get("id")),
                "text": _label(str(action.get("text") or "operation")),
                "origin": "automatic",
                "confidence": float(action.get("confidence") or 0),
                "accepted": False,
            }
            for action in actions
            if action.get("id")
        ]
        input_bindings = [
            binding
            for binding in bindings
            if binding.get("role", "input") == "input" and binding.get("id")
        ]
        included_lineages = {
            str(binding.get("ingredient_lineage_id"))
            for binding in input_bindings
            if binding.get("ingredient_lineage_id")
        }
        table_document = {
            "schema_version": 1,
            "labels": labels,
            "row_order": [str(binding["id"]) for binding in input_bindings],
            "column_hints": [],
            "setup_action_ids": [
                str(action["id"])
                for action in actions
                if action.get("id") and not any(binding.get("action_id") == action.get("id") for binding in input_bindings)
            ],
            "terminal_action_ids": [action_id for action_id, targets in outgoing.items() if not targets],
            "omissions": [],
        }
        coverage = {
            "total_actions": len(actions),
            "represented_actions": len(labels),
            "total_included_ingredient_lineages": len(included_lineages),
            "represented_ingredient_lineages": len(included_lineages),
            "ingredient_use_rows": len(input_bindings),
            "explicitly_omitted_ingredients": 0,
            "explicitly_omitted_actions": 0,
            "unplaced_ingredients": 0,
            "disconnected_components": 0,
            "low_confidence_labels": sum(1 for label in labels if label["confidence"] < 0.65),
            "low_confidence_bindings": sum(
                1 for binding in input_bindings if float(binding.get("confidence") or 0) < 0.65
            ),
            "low_confidence_edges": sum(1 for edge in edges if float(edge.get("confidence") or 0) < 0.65),
            "blocking_warnings": 0,
            "non_blocking_warnings": 0,
        }
        connection.execute(
            sa.text(
                "INSERT INTO recipe_method_table_snapshot "
                "(id, recipe_method_snapshot_id, parser_version, status, confidence, coverage, document, created_at) "
                "VALUES (:id, :snapshot_id, 'table-rules-1', 'needs_review', :confidence, :coverage, :document, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid.uuid4()),
                "snapshot_id": snapshot_id,
                "confidence": sum(label["confidence"] for label in labels) / len(labels) if labels else 0,
                "coverage": json.dumps(coverage),
                "document": json.dumps(table_document),
            },
        )


def downgrade() -> None:
    op.drop_index("ix_recipe_method_table_snapshot_status", table_name="recipe_method_table_snapshot")
    op.drop_index(
        "ix_recipe_method_table_snapshot_recipe_method_snapshot_id",
        table_name="recipe_method_table_snapshot",
    )
    op.drop_table("recipe_method_table_snapshot")
