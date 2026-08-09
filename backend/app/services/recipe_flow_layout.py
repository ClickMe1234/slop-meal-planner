"""Deterministic Flow table layout shared with the frontend contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..schemas import MethodDocument, MethodTableDocument


@dataclass(frozen=True)
class _Cell:
    action_id: str
    column: int
    row_start: int
    row_span: int
    input_binding_ids: tuple[str, ...]
    predecessor_action_ids: tuple[str, ...]
    kind: str


def _action_key(action: Any) -> tuple[int, str]:
    return int(action.position), action.id


def _overlaps(left: _Cell | dict[str, Any], right: dict[str, int]) -> bool:
    left_start = left.row_start if isinstance(left, _Cell) else left["row_start"]
    left_span = left.row_span if isinstance(left, _Cell) else left["row_span"]
    return left_start < right["row_start"] + right["row_span"] and right["row_start"] < left_start + left_span


def layout_flow_table(
    method: MethodDocument | dict[str, Any],
    table: MethodTableDocument | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the same structural layout shape used by ``recipeFlowLayout.ts``."""

    document = method if isinstance(method, MethodDocument) else MethodDocument.model_validate(method)
    table_document = (
        table
        if isinstance(table, MethodTableDocument)
        else MethodTableDocument.model_validate(table)
        if table is not None
        else MethodTableDocument()
    )
    actions = {action.id: action for action in document.actions}
    incoming: dict[str, list[str]] = {action.id: [] for action in document.actions}
    outgoing: dict[str, list[str]] = {action.id: [] for action in document.actions}
    warnings: list[dict[str, Any]] = []
    for edge in document.edges:
        if edge.from_action_id not in actions or edge.to_action_id not in actions:
            warnings.append({
                "code": "dangling_edge",
                "message": "A flow connector points to an operation that no longer exists.",
                "blocking": True,
                "entityId": edge.id,
            })
            continue
        incoming[edge.to_action_id].append(edge.from_action_id)
        outgoing[edge.from_action_id].append(edge.to_action_id)
    indegree = {action_id: len(parents) for action_id, parents in incoming.items()}
    queue = sorted((action for action in document.actions if indegree[action.id] == 0), key=_action_key)
    order: list[str] = []
    while queue:
        action = queue.pop(0)
        order.append(action.id)
        for child_id in sorted(outgoing[action.id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                queue.append(actions[child_id])
                queue.sort(key=_action_key)
    if len(order) != len(document.actions):
        warnings.append({
            "code": "graph_cycle",
            "message": "This flow contains a cycle; connectors are shown in source order until it is repaired.",
            "blocking": True,
        })
        order.extend(
            action.id
            for action in sorted(document.actions, key=_action_key)
            if action.id not in order
        )

    input_bindings = [binding for binding in document.ingredient_bindings if binding.role != "reference"]
    binding_by_id = {binding.id: binding for binding in input_bindings}
    setup_ids = {action_id for action_id in table_document.setup_action_ids if action_id in actions}
    rows: list[dict[str, Any]] = []
    for action_id in order:
        if action_id in setup_ids:
            rows.append({"id": f"setup:{action_id}", "kind": "setup", "actionId": action_id, "label": "Setup"})
    saved_rows = [binding_id for binding_id in table_document.row_order if binding_id in binding_by_id]
    row_ids = saved_rows + [binding.id for binding in input_bindings if binding.id not in saved_rows]
    for binding_id in row_ids:
        binding = binding_by_id[binding_id]
        rows.append({
            "id": f"binding:{binding.id}",
            "kind": "ingredient",
            "bindingId": binding.id,
            "ingredientLineageId": binding.ingredient_lineage_id,
            "label": binding.ingredient_lineage_id,
        })
    if not rows and order:
        rows.append({"id": "setup:default", "kind": "setup", "label": "Flow"})
    row_index = {row["id"]: index for index, row in enumerate(rows)}
    labels = {label.action_id: label for label in table_document.labels}
    for action in document.actions:
        label = labels.get(action.id)
        if label is None:
            warnings.append({"code": "missing_label", "message": "An operation is missing a compact table label.", "blocking": True, "entityId": action.id})
        elif label.confidence < 0.65 and not label.accepted:
            warnings.append({"code": "low_confidence_label", "message": "An operation label is uncertain.", "blocking": True, "entityId": action.id})
    for binding in input_bindings:
        if binding.confidence < 0.65 and not binding.accepted:
            warnings.append({"code": "low_confidence_binding", "message": "An ingredient placement is uncertain.", "blocking": True, "entityId": binding.id})
    for edge in document.edges:
        if edge.confidence < 0.65 and not edge.accepted:
            warnings.append({"code": "low_confidence_edge", "message": "A branch connection is uncertain.", "blocking": True, "entityId": edge.id})

    cells_by_action: dict[str, _Cell] = {}
    logical_columns: dict[str, int] = {}
    occupied: dict[int, list[_Cell]] = {}

    def row_range(action_id: str) -> tuple[int, int]:
        direct_rows = [
            row_index[f"binding:{binding.id}"]
            for binding in input_bindings
            if binding.action_id == action_id and f"binding:{binding.id}" in row_index
        ]
        predecessor_rows: list[int] = []
        for parent_id in incoming[action_id]:
            parent = cells_by_action.get(parent_id)
            if parent is not None:
                predecessor_rows.extend(range(parent.row_start, parent.row_start + parent.row_span))
        values = direct_rows + predecessor_rows
        if not values:
            return row_index.get(f"setup:{action_id}", 0), 1
        start = min(values)
        return start, max(values) - start + 1

    hints = {hint.action_id: hint.preferred_column for hint in table_document.column_hints}
    for action_id in order:
        parents = incoming[action_id]
        earliest = max((logical_columns[parent_id] + 1 for parent_id in parents), default=0)
        column = max(earliest, hints.get(action_id, 0))
        start, span = row_range(action_id)
        while any(_overlaps(cell, {"row_start": start, "row_span": span}) for cell in occupied.get(column, [])):
            column += 1
        cell = _Cell(
            action_id=action_id,
            column=column,
            row_start=start,
            row_span=span,
            input_binding_ids=tuple(binding.id for binding in input_bindings if binding.action_id == action_id),
            predecessor_action_ids=tuple(parents),
            kind="merge" if len(parents) > 1 else "setup" if action_id in setup_ids else "operation",
        )
        cells_by_action[action_id] = cell
        logical_columns[action_id] = column
        occupied.setdefault(column, []).append(cell)

    logical_values = sorted(set(logical_columns.values()))
    column_index = {value: index for index, value in enumerate(logical_values)}
    labels_by_action = {label.action_id: label.text for label in table_document.labels}
    columns: list[dict[str, Any]] = []
    for index, logical in enumerate(logical_values):
        action_id = next(action_id for action_id in order if logical_columns[action_id] == logical)
        action = actions[action_id]
        stage = next((stage for stage in document.stages if stage.id == action.stage_id), None)
        columns.append({
            "actionId": action_id,
            "stageId": action.stage_id,
            "stageTitle": stage.title if stage is not None else "Method",
            "index": index,
            "label": labels_by_action.get(action_id, action.text),
        })
    cells = [
        {
            "actionId": cell.action_id,
            "column": column_index[cell.column],
            "rowStart": cell.row_start,
            "rowSpan": cell.row_span,
            "inputBindingIds": list(cell.input_binding_ids),
            "predecessorActionIds": list(cell.predecessor_action_ids),
            "kind": cell.kind,
        }
        for cell in cells_by_action.values()
    ]
    connectors: list[dict[str, Any]] = []
    for edge in document.edges:
        source = cells_by_action.get(edge.from_action_id)
        target = cells_by_action.get(edge.to_action_id)
        if source is None or target is None:
            continue
        fan_in = len(incoming[edge.to_action_id]) > 1
        fan_out = len(outgoing[edge.from_action_id]) > 1
        connectors.append({
            "edgeId": edge.id,
            "kind": "merge" if fan_in else "fork" if fan_out else edge.kind,
            "fromActionId": edge.from_action_id,
            "toActionId": edge.to_action_id,
            "fromRow": source.row_start,
            "toRow": target.row_start,
            "column": max(0, column_index[target.column] - 1),
        })
    lanes: list[dict[str, Any]] = []
    for column in columns:
        previous = lanes[-1] if lanes else None
        if previous is not None and previous["stageId"] == column["stageId"]:
            previous["endColumn"] = column["index"]
        else:
            lanes.append({
                "stageId": column["stageId"],
                "title": column["stageTitle"],
                "startColumn": column["index"],
                "endColumn": column["index"],
            })
    return {
        "rows": rows,
        "columns": columns,
        "cells": cells,
        "connectors": connectors,
        "lanes": lanes,
        "warnings": warnings,
    }


create_flow_table_layout = layout_flow_table
