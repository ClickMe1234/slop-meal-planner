"""Deterministic projection and validation for recipe Flow tables.

The method document remains the semantic source of truth.  This module only
creates the compact, user-editable projection used by the Flow table view.
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..models import RecipeIngredient, RecipeMethodSnapshot, RecipeMethodTableSnapshot, RecipeVersion
from ..schemas import (
    MethodDocument,
    MethodTableCoverage,
    MethodTableDocument,
    MethodTableIngredientUse,
    MethodTableLabel,
    MethodTableViewOut,
    MethodTableWarning,
)
from .measurement_conversion import (
    convert_quantity_to_unit,
    measurement_dimension,
    resolve_measurement_profile,
)
from .recipe_methods import _display_measurement, _display_number, _value


TABLE_PARSER_VERSION = "table-rules-1"
TABLE_SCHEMA_VERSION = 1
TABLE_CONFIDENCE_THRESHOLD = Decimal("0.65")

_ACTION_WORD_RE = re.compile(
    r"\b(add|arrange|assemble|bake|beat|blend|boil|bring|brown|brush|chill|chop|"
    r"combine|cook|cover|cut|drain|fold|fry|grill|heat|knead|layer|leave|melt|mix|"
    r"place|pour|preheat|reduce|remove|rest|roast|roll|season|serve|simmer|slice|"
    r"spoon|sprinkle|stir|strain|tip|toast|transfer|whisk)\b",
    re.IGNORECASE,
)
_LABEL_STOP_RE = re.compile(
    r"\b(?:for|at|until|when|while|in|on|with|using|then|so|and)\b.*$",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|–|—)\s*(?P<high>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)",
    re.IGNORECASE,
)

# Match publisher ranges written with ASCII or Unicode dash characters. The
# explicit escapes keep this rule stable when source files are opened on a
# locale that does not default to UTF-8.
_RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|[\u2013\u2014])\s*(?P<high>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)",
    re.IGNORECASE,
)


def _compact_duration(action: object) -> str | None:
    raw = str(_value(action, "duration_text", "") or "").strip()
    if raw:
        match = _RANGE_RE.search(raw)
        if match:
            unit = match.group("unit").casefold()
            short = "sec" if unit.startswith("sec") else "hr" if unit.startswith(("hour", "hr")) else "min"
            return f"{match.group('low')}-{match.group('high')} {short}"
            return f"{match.group('low')}–{match.group('high')} {short}"
        number = re.search(r"\d+(?:\.\d+)?", raw)
        if number:
            unit = "hr" if re.search(r"hour|hr", raw, re.IGNORECASE) else "min"
            return f"{number.group()} {unit}"
    minutes = _value(action, "duration_minutes")
    if minutes is None:
        return None
    value = Decimal(str(minutes)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if value == value.to_integral():
        return f"{int(value)} min"
    return f"{value.normalize()} min"


def compact_action_label(action: object) -> str:
    """Return a short label while retaining the useful cooking cues."""

    source = " ".join(str(_value(action, "text", "") or "").split()).strip(" .;,")
    match = _ACTION_WORD_RE.search(source)
    verb = match.group(1).casefold() if match else "work"
    object_text = source[match.end() :] if match else source
    object_text = _LABEL_STOP_RE.sub("", object_text).strip(" ,.;:")
    object_text = re.sub(r"^(?:the|a|an)\s+", "", object_text, flags=re.IGNORECASE)
    object_text = re.sub(r"\s+", " ", object_text)
    if len(object_text) > 48:
        object_text = f"{object_text[:45].rstrip()}…"

    parts = [" ".join(item for item in (verb, object_text) if item)]
    lowered = source.casefold()
    if "covered" in lowered or "lid on" in lowered:
        parts.append("covered")
    heat_match = re.search(r"\b(low|medium(?:-low|-high)?|high)\b", lowered)
    if heat_match and heat_match.group(1) not in object_text.casefold():
        parts.append(heat_match.group(1))
    temperature = _value(action, "temperature_value")
    temperature_unit = _value(action, "temperature_unit")
    if temperature is not None:
        temp = Decimal(str(temperature)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        temp_text = str(int(temp)) if temp == temp.to_integral() else format(temp.normalize(), "f")
        parts.append(f"{temp_text}°{str(temperature_unit or 'c').upper()}")
    duration = _compact_duration(action)
    if duration:
        parts.append(duration)
    cue = str(_value(action, "cue", "") or "").strip()
    if cue:
        parts.append(f"until {cue}")
    return " · ".join(part for part in parts if part)[:120]


_compact_action_label = compact_action_label


def compact_action_label(action: object) -> str:
    """Return labels with stable Unicode punctuation on every deployment locale."""

    return (
        _compact_action_label(action)
        .replace("\u00c2\u00b0", "\u00b0")
        .replace("\u00c2\u00b7", "\u00b7")
        .replace("\u00e2\u20ac\u2026", "\u2026")
    )


def _action_map(document: MethodDocument) -> dict[str, Any]:
    return {action.id: action for action in document.actions}


def _input_bindings(document: MethodDocument) -> list[Any]:
    return [binding for binding in document.ingredient_bindings if binding.role == "input"]


def _graph(document: MethodDocument) -> tuple[dict[str, set[str]], dict[str, set[str]], list[MethodTableWarning]]:
    action_ids = {action.id for action in document.actions}
    outgoing: dict[str, set[str]] = {action_id: set() for action_id in action_ids}
    incoming: dict[str, set[str]] = {action_id: set() for action_id in action_ids}
    warnings: list[MethodTableWarning] = []
    for edge in document.edges:
        if edge.from_action_id not in action_ids or edge.to_action_id not in action_ids:
            warnings.append(
                MethodTableWarning(
                    code="dangling_edge",
                    message="This operation link points to an action that no longer exists.",
                    blocking=True,
                    entity_kind="edge",
                    entity_id=edge.id,
                )
            )
            continue
        outgoing[edge.from_action_id].add(edge.to_action_id)
        incoming[edge.to_action_id].add(edge.from_action_id)
    return outgoing, incoming, warnings


def _topological_order(document: MethodDocument) -> tuple[list[str], list[MethodTableWarning]]:
    outgoing, incoming, warnings = _graph(document)
    indegree = {action_id: len(parents) for action_id, parents in incoming.items()}
    action_position = {action.id: (action.position, action.id) for action in document.actions}
    queue = [action_id for action_id, degree in indegree.items() if degree == 0]
    queue.sort(key=lambda action_id: action_position[action_id])
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for target in sorted(outgoing[current], key=lambda action_id: action_position[action_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
                queue.sort(key=lambda action_id: action_position[action_id])
    if len(ordered) != len(document.actions):
        warnings.append(
            MethodTableWarning(
                code="graph_cycle",
                message="The cooking flow contains a cycle. Break the loop before reviewing the table.",
                blocking=True,
                entity_kind="graph",
            )
        )
        remaining = sorted(
            (action.id for action in document.actions if action.id not in ordered),
            key=lambda action_id: action_position[action_id],
        )
        ordered.extend(remaining)
    return ordered, warnings


def _component_count(document: MethodDocument) -> int:
    components = len(_components(document))
    return max(0, components - 1)


def _components(document: MethodDocument) -> list[set[str]]:
    action_ids = {action.id for action in document.actions}
    neighbours: dict[str, set[str]] = {action_id: set() for action_id in action_ids}
    for edge in document.edges:
        if edge.from_action_id in action_ids and edge.to_action_id in action_ids:
            neighbours[edge.from_action_id].add(edge.to_action_id)
            neighbours[edge.to_action_id].add(edge.from_action_id)
    remaining = set(action_ids)
    components: list[set[str]] = []
    while remaining:
        start = remaining.pop()
        component = {start}
        queue = [start]
        while queue:
            current = queue.pop()
            for neighbour in neighbours[current]:
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    queue.append(neighbour)
        components.append(component)
    return components


def build_table_projection(
    document: MethodDocument | dict[str, Any],
    ingredients: Iterable[object],
    existing: MethodTableDocument | dict[str, Any] | None = None,
) -> tuple[MethodTableDocument, MethodTableCoverage, list[MethodTableWarning], Decimal]:
    """Project a method graph into a deterministic Flow table draft."""

    method = document if isinstance(document, MethodDocument) else MethodDocument.model_validate(document)
    ingredient_rows = list(ingredients)
    included_lineages = {
        str(_value(item, "lineage_id", ""))
        for item in ingredient_rows
        if _value(item, "included", True) and _value(item, "lineage_id")
    }
    binding_rows = _input_bindings(method)
    binding_ids = [binding.id for binding in binding_rows]
    action_ids = {action.id for action in method.actions}
    existing_doc = (
        existing
        if isinstance(existing, MethodTableDocument)
        else MethodTableDocument.model_validate(existing)
        if existing
        else None
    )
    automatic_labels = {
        action.id: MethodTableLabel(
            action_id=action.id,
            text=compact_action_label(action),
            origin="automatic",
            confidence=action.confidence,
            accepted=action.confidence >= TABLE_CONFIDENCE_THRESHOLD,
        )
        for action in method.actions
    }
    labels_by_action = {
        label.action_id: label
        for label in (existing_doc.labels if existing_doc else [])
        if label.action_id in action_ids
    }
    labels_by_action.update(
        {action_id: label for action_id, label in automatic_labels.items() if action_id not in labels_by_action}
    )
    valid_saved_rows = [binding_id for binding_id in (existing_doc.row_order if existing_doc else []) if binding_id in binding_ids]
    row_order = valid_saved_rows + [binding_id for binding_id in binding_ids if binding_id not in valid_saved_rows]
    valid_hints = [
        hint
        for hint in (existing_doc.column_hints if existing_doc else [])
        if hint.action_id in action_ids
    ]
    setup_ids = [
        action_id
        for action_id in (existing_doc.setup_action_ids if existing_doc else [])
        if action_id in action_ids
    ]
    setup_ids.extend(
        action.id
        for action in method.actions
        if not any(binding.action_id == action.id for binding in binding_rows) and action.id not in setup_ids
    )
    outgoing, incoming, warnings = _graph(method)
    terminal_ids = [action.id for action in method.actions if not outgoing[action.id]]
    if existing_doc and existing_doc.terminal_action_ids:
        saved_terminals = [action_id for action_id in existing_doc.terminal_action_ids if action_id in action_ids]
        terminal_ids = saved_terminals or terminal_ids
    table = MethodTableDocument(
        schema_version=TABLE_SCHEMA_VERSION,
        labels=list(labels_by_action.values()),
        row_order=row_order,
        column_hints=valid_hints,
        setup_action_ids=setup_ids,
        terminal_action_ids=terminal_ids,
        omissions=[
            omission
            for omission in (existing_doc.omissions if existing_doc else [])
            if omission.entity_kind == "action" and omission.referenced_id in action_ids
            or omission.entity_kind == "ingredient" and omission.referenced_id in included_lineages
        ],
    )

    connected_lineages = {binding.ingredient_lineage_id for binding in binding_rows}
    omitted_ingredients = {
        omission.referenced_id for omission in table.omissions if omission.entity_kind == "ingredient" and omission.accepted
    }
    unplaced = sorted(included_lineages - connected_lineages - omitted_ingredients)
    for lineage_id in unplaced:
        warnings.append(
            MethodTableWarning(
                code="unplaced_ingredient",
                message="This included ingredient has not been placed in the Flow table.",
                blocking=True,
                entity_kind="ingredient",
                entity_id=lineage_id,
            )
        )
    label_ids = {label.action_id for label in table.labels}
    omitted_actions = {
        omission.referenced_id
        for omission in table.omissions
        if omission.entity_kind == "action" and omission.accepted
    }
    for action_id in sorted(action_ids - label_ids - omitted_actions):
        warnings.append(
            MethodTableWarning(
                code="missing_label",
                message="This operation needs a compact table label before review.",
                blocking=True,
                entity_kind="action",
                entity_id=action_id,
            )
        )
    if set(table.row_order) != set(binding_ids) or len(table.row_order) != len(binding_ids):
        warnings.append(
            MethodTableWarning(
                code="row_order_incomplete",
                message="Every material ingredient use must appear exactly once in the table row order.",
                blocking=True,
                entity_kind="table",
            )
        )
    for label in table.labels:
        if label.confidence < TABLE_CONFIDENCE_THRESHOLD and not label.accepted:
            warnings.append(
                MethodTableWarning(
                    code="low_confidence_label",
                    message="This automatic operation label is uncertain; edit or accept it.",
                    blocking=True,
                    entity_kind="action",
                    entity_id=label.action_id,
                )
            )
    for binding in binding_rows:
        if binding.confidence < TABLE_CONFIDENCE_THRESHOLD and not binding.accepted:
            warnings.append(
                MethodTableWarning(
                    code="low_confidence_binding",
                    message="This ingredient placement is uncertain; check the row and action.",
                    blocking=True,
                    entity_kind="binding",
                    entity_id=binding.id,
                )
            )
    for edge in method.edges:
        if edge.confidence < TABLE_CONFIDENCE_THRESHOLD and not edge.accepted:
            warnings.append(
                MethodTableWarning(
                    code="low_confidence_edge",
                    message="This branch connection is uncertain; confirm the flow direction.",
                    blocking=True,
                    entity_kind="edge",
                    entity_id=edge.id,
                )
            )
    _, topology_warnings = _topological_order(method)
    warnings.extend(item for item in topology_warnings if item.code not in {warning.code for warning in warnings})
    selected_terminals = {action_id for action_id in terminal_ids if action_id in action_ids}
    for component in _components(method):
        if not component.intersection(selected_terminals):
            warnings.append(
                MethodTableWarning(
                    code="missing_terminal_output",
                    message="Declare a finished output for every connected flow branch.",
                    blocking=True,
                    entity_kind="graph",
                )
            )

    coverage = MethodTableCoverage(
        total_actions=len(method.actions),
        represented_actions=len(label_ids & action_ids),
        total_included_ingredient_lineages=len(included_lineages),
        represented_ingredient_lineages=len(connected_lineages & included_lineages),
        ingredient_use_rows=len(binding_rows),
        explicitly_omitted_ingredients=sum(1 for item in table.omissions if item.entity_kind == "ingredient"),
        explicitly_omitted_actions=sum(1 for item in table.omissions if item.entity_kind == "action"),
        unplaced_ingredients=len(unplaced),
        disconnected_components=_component_count(method),
        low_confidence_labels=sum(1 for item in table.labels if item.confidence < TABLE_CONFIDENCE_THRESHOLD and not item.accepted),
        low_confidence_bindings=sum(1 for item in binding_rows if item.confidence < TABLE_CONFIDENCE_THRESHOLD and not item.accepted),
        low_confidence_edges=sum(1 for item in method.edges if item.confidence < TABLE_CONFIDENCE_THRESHOLD and not item.accepted),
        blocking_warnings=sum(1 for item in warnings if item.blocking),
        non_blocking_warnings=sum(1 for item in warnings if not item.blocking),
    )
    confidence_values = [label.confidence for label in table.labels]
    confidence_values.extend(binding.confidence for binding in binding_rows)
    confidence_values.extend(edge.confidence for edge in method.edges)
    confidence = (
        sum(confidence_values, Decimal("0")) / len(confidence_values)
        if confidence_values
        else Decimal("0")
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return table, coverage, warnings, confidence


def validate_table_for_review(
    method: MethodDocument | dict[str, Any],
    table: MethodTableDocument | dict[str, Any],
    ingredients: Iterable[object],
) -> tuple[MethodTableCoverage, list[MethodTableWarning]]:
    document = method if isinstance(method, MethodDocument) else MethodDocument.model_validate(method)
    table_document = table if isinstance(table, MethodTableDocument) else MethodTableDocument.model_validate(table)
    ingredient_rows = list(ingredients)
    _, coverage, warnings, _ = build_table_projection(document, ingredient_rows, table_document)

    def add_warning(warning: MethodTableWarning) -> None:
        if not any(
            item.code == warning.code and item.entity_id == warning.entity_id
            for item in warnings
        ):
            warnings.append(warning)

    action_ids = {action.id for action in document.actions}
    input_bindings = [binding for binding in document.ingredient_bindings if binding.role == "input"]
    input_binding_ids = {binding.id for binding in input_bindings}
    row_order = table_document.row_order
    if any(binding_id not in input_binding_ids for binding_id in row_order):
        add_warning(
            MethodTableWarning(
                code="unknown_row_binding",
                message="The table row order contains an ingredient use that is not in the method graph.",
                blocking=True,
                entity_kind="table",
            )
        )
    if len(row_order) != len(input_binding_ids) or set(row_order) != input_binding_ids:
        add_warning(
            MethodTableWarning(
                code="row_order_incomplete",
                message="Every material ingredient use must appear exactly once in the table row order.",
                blocking=True,
                entity_kind="table",
            )
        )

    label_ids = {label.action_id for label in table_document.labels}
    for label in table_document.labels:
        if label.action_id not in action_ids:
            add_warning(
                MethodTableWarning(
                    code="unknown_label_action",
                    message="A compact label points to an operation that no longer exists.",
                    blocking=True,
                    entity_kind="action",
                    entity_id=label.action_id,
                )
            )
    accepted_omitted_actions = {
        omission.referenced_id
        for omission in table_document.omissions
        if omission.entity_kind == "action" and omission.accepted
    }
    for action_id in sorted(action_ids - label_ids - accepted_omitted_actions):
        add_warning(
            MethodTableWarning(
                code="missing_label",
                message="This operation needs a compact table label before review.",
                blocking=True,
                entity_kind="action",
                entity_id=action_id,
            )
        )
    for hint in table_document.column_hints:
        if hint.action_id not in action_ids:
            add_warning(
                MethodTableWarning(
                    code="unknown_column_hint",
                    message="A saved column placement points to an operation that no longer exists.",
                    blocking=True,
                    entity_kind="action",
                    entity_id=hint.action_id,
                )
            )
    for action_id in [*table_document.setup_action_ids, *table_document.terminal_action_ids]:
        if action_id not in action_ids:
            add_warning(
                MethodTableWarning(
                    code="unknown_table_action",
                    message="The table references an operation that no longer exists.",
                    blocking=True,
                    entity_kind="action",
                    entity_id=action_id,
                )
            )
    if document.actions and not table_document.terminal_action_ids:
        add_warning(
            MethodTableWarning(
                code="missing_terminal_output",
                message="Declare at least one finished output for this flow.",
                blocking=True,
                entity_kind="graph",
            )
        )

    fractions: dict[str, Decimal] = defaultdict(Decimal)
    remainders: set[str] = set()
    absolute_totals: dict[str, Decimal] = defaultdict(Decimal)
    absolute_bindings: dict[str, list[Any]] = defaultdict(list)
    ingredient_by_lineage = {
        str(_value(item, "lineage_id")): item
        for item in ingredient_rows
        if _value(item, "lineage_id")
    }
    for binding in document.ingredient_bindings:
        if binding.role != "input":
            continue
        if binding.portion_mode == "fraction" and binding.portion_value is not None:
            fractions[binding.ingredient_lineage_id] += binding.portion_value
        if binding.portion_mode == "remainder":
            if binding.ingredient_lineage_id in remainders:
                warnings.append(
                    MethodTableWarning(
                        code="multiple_remainders",
                        message="An ingredient can have only one remainder allocation.",
                        blocking=True,
                        entity_kind="binding",
                        entity_id=binding.id,
                    )
                )
            remainders.add(binding.ingredient_lineage_id)
        if binding.portion_mode == "absolute" and binding.portion_value is not None:
            absolute_totals[binding.ingredient_lineage_id] += binding.portion_value
            absolute_bindings[binding.ingredient_lineage_id].append(binding)
    for lineage_id, total in fractions.items():
        if total > 1:
            warnings.append(
                MethodTableWarning(
                    code="portion_overallocated",
                    message="Portion fractions exceed the available ingredient quantity.",
                    blocking=True,
                    entity_kind="ingredient",
                    entity_id=lineage_id,
                )
            )
    for lineage_id, total in absolute_totals.items():
        ingredient = ingredient_by_lineage.get(lineage_id)
        base_quantity = _value(ingredient, "quantity") if ingredient is not None else None
        base_unit = _value(ingredient, "unit") if ingredient is not None else None
        absolute_units = {
            binding.portion_unit or base_unit
            for binding in input_bindings
            if binding.ingredient_lineage_id == lineage_id and binding.portion_mode == "absolute"
        }
        if (
            base_quantity is not None
            and len(absolute_units) == 1
            and next(iter(absolute_units)) == base_unit
            and total > Decimal(str(base_quantity))
        ):
            warnings.append(
                MethodTableWarning(
                    code="portion_overallocated",
                    message="Absolute ingredient uses exceed the available recipe quantity.",
                    blocking=True,
                    entity_kind="ingredient",
                    entity_id=lineage_id,
                )
            )
        if base_quantity is None or not base_unit or len(absolute_units) <= 1:
            continue
        dimension = measurement_dimension(str(base_unit))
        if dimension is None:
            continue
        target_unit = "g" if dimension == "mass" else "ml"
        profile = resolve_measurement_profile(
            _value(ingredient, "food_phrase"),
            _value(ingredient, "parsed_food_phrase"),
            _value(ingredient, "original_text"),
        )
        density = profile.density_g_per_ml if profile is not None else None
        base_comparable = convert_quantity_to_unit(
            Decimal(str(base_quantity)), str(base_unit), target_unit, density
        )
        allocated_comparable = Decimal("0")
        for binding in absolute_bindings[lineage_id]:
            converted = convert_quantity_to_unit(
                Decimal(str(binding.portion_value)),
                str(binding.portion_unit or base_unit),
                target_unit,
                density,
            )
            if converted is None:
                break
            allocated_comparable += converted
        else:
            if base_comparable is not None and allocated_comparable > base_comparable:
                warnings.append(
                    MethodTableWarning(
                        code="portion_overallocated",
                        message="Comparable absolute ingredient uses exceed the available recipe quantity.",
                        blocking=True,
                        entity_kind="ingredient",
                        entity_id=lineage_id,
                    )
                )
    if any(item.blocking for item in warnings):
        first = next(item for item in warnings if item.blocking)
        raise ValueError(first.message)
    return coverage, warnings


def validate_table_structure(
    method: MethodDocument | dict[str, Any],
    table: MethodTableDocument | dict[str, Any],
    ingredients: Iterable[object],
) -> None:
    """Reject dangling projection references while allowing incomplete drafts."""

    document = method if isinstance(method, MethodDocument) else MethodDocument.model_validate(method)
    table_document = table if isinstance(table, MethodTableDocument) else MethodTableDocument.model_validate(table)
    ingredient_rows = list(ingredients)
    action_ids = {action.id for action in document.actions}
    input_binding_ids = {
        binding.id
        for binding in document.ingredient_bindings
        if binding.role == "input"
    }
    lineage_ids = {
        str(_value(item, "lineage_id"))
        for item in ingredient_rows
        if _value(item, "lineage_id")
    }
    invalid_rows = [binding_id for binding_id in table_document.row_order if binding_id not in input_binding_ids]
    invalid_labels = [label.action_id for label in table_document.labels if label.action_id not in action_ids]
    invalid_hints = [hint.action_id for hint in table_document.column_hints if hint.action_id not in action_ids]
    invalid_setup = [action_id for action_id in table_document.setup_action_ids if action_id not in action_ids]
    invalid_terminals = [action_id for action_id in table_document.terminal_action_ids if action_id not in action_ids]
    invalid_omissions = [
        omission.referenced_id
        for omission in table_document.omissions
        if (
            omission.entity_kind == "action" and omission.referenced_id not in action_ids
        )
        or (
            omission.entity_kind == "ingredient" and omission.referenced_id not in lineage_ids
        )
    ]
    if invalid_rows:
        raise ValueError("The Flow table row order contains an unknown ingredient use.")
    if invalid_labels:
        raise ValueError("The Flow table contains a label for an unknown operation.")
    if invalid_hints or invalid_setup or invalid_terminals:
        raise ValueError("The Flow table contains a placement for an unknown operation.")
    if invalid_omissions:
        raise ValueError("The Flow table contains an omission for an unknown entity.")


def table_snapshot_values(
    method: MethodDocument | dict[str, Any],
    ingredients: Iterable[object],
    *,
    created_by_user_id: str | None,
    existing: MethodTableDocument | dict[str, Any] | None = None,
    status: str = "needs_review",
) -> dict[str, Any]:
    document, coverage, warnings, confidence = build_table_projection(method, ingredients, existing)
    return {
        "parser_version": TABLE_PARSER_VERSION,
        "status": status,
        "confidence": confidence,
        "coverage": coverage.model_dump(mode="json"),
        "document": document.model_dump(mode="json"),
        "created_by_user_id": created_by_user_id,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
    }


def table_snapshot_for_method(
    snapshot: RecipeMethodSnapshot,
    ingredients: Iterable[object],
    *,
    created_by_user_id: str | None,
    existing: MethodTableDocument | dict[str, Any] | None = None,
    status: str = "needs_review",
) -> RecipeMethodTableSnapshot:
    return RecipeMethodTableSnapshot(
        recipe_method_snapshot_id=snapshot.id,
        **table_snapshot_values(
            snapshot.document,
            ingredients,
            created_by_user_id=created_by_user_id,
            existing=existing,
            status=status,
        ),
    )


def _scaled_use_quantity(
    binding: object,
    ingredient: dict[str, Any],
    bindings: list[Any],
    *,
    scale: Decimal,
) -> tuple[Decimal | None, str | None]:
    base_quantity = ingredient.get("quantity")
    if base_quantity is None:
        return None, _value(binding, "portion_unit") or ingredient.get("unit")
    base = Decimal(str(base_quantity))
    mode = _value(binding, "portion_mode", "unspecified")
    if mode == "fraction":
        return base * Decimal(str(_value(binding, "portion_value", 0))), ingredient.get("unit")
    if mode == "remainder":
        used_fraction = sum(
            (
                Decimal(str(_value(item, "portion_value", 0)))
                for item in bindings
                if _value(item, "ingredient_lineage_id") == _value(binding, "ingredient_lineage_id")
                and _value(item, "portion_mode") == "fraction"
            ),
            Decimal("0"),
        )
        used_absolute = sum(
            (
                Decimal(str(_value(item, "portion_value", 0))) * scale
                for item in bindings
                if _value(item, "ingredient_lineage_id") == _value(binding, "ingredient_lineage_id")
                and _value(item, "portion_mode") == "absolute"
                and (_value(item, "portion_unit") or ingredient.get("unit")) == ingredient.get("unit")
            ),
            Decimal("0"),
        )
        absolute_fraction = used_absolute / base if base else Decimal("0")
        return base * max(Decimal("0"), Decimal("1") - used_fraction - absolute_fraction), ingredient.get("unit")
    if mode == "absolute":
        return Decimal(str(_value(binding, "portion_value", 0))) * scale, _value(binding, "portion_unit") or ingredient.get("unit")
    return base, ingredient.get("unit")


def rendered_table_ingredient_uses(
    db: Session,
    version: RecipeVersion,
    snapshot: RecipeMethodSnapshot,
    table_document: MethodTableDocument,
    scaled_ingredients: list[dict[str, Any]],
    *,
    requested_servings: Decimal | None,
    measurement_system: str,
) -> list[MethodTableIngredientUse]:
    ingredient_by_lineage = {item["lineage_id"]: item for item in scaled_ingredients}
    method = MethodDocument.model_validate(snapshot.document)
    bindings = [binding for binding in method.ingredient_bindings if binding.role == "input"]
    binding_by_id = {binding.id: binding for binding in bindings}
    scale = Decimal("1")
    if requested_servings is not None and version.yield_servings:
        scale = requested_servings / Decimal(version.yield_servings)
    result: list[MethodTableIngredientUse] = []
    for binding_id in table_document.row_order:
        binding = binding_by_id.get(binding_id)
        if binding is None:
            continue
        ingredient = ingredient_by_lineage.get(binding.ingredient_lineage_id)
        if ingredient is None:
            continue
        quantity, unit = _scaled_use_quantity(binding, ingredient, bindings, scale=scale)
        if quantity is not None and unit:
            quantity, unit = _display_measurement(quantity, unit, measurement_system, None)
        quantity_text = _display_number(quantity)
        name = str(ingredient.get("name") or "ingredient")
        display_name = f"{name}, {ingredient['preparation']}" if ingredient.get("preparation") else name
        display = " ".join(item for item in (quantity_text, unit, display_name) if item)
        result.append(
            MethodTableIngredientUse(
                binding_id=binding.id,
                ingredient_lineage_id=binding.ingredient_lineage_id,
                target_action_id=binding.action_id,
                name=name,
                quantity=quantity,
                quantity_text=quantity_text,
                unit=unit,
                portion_mode=binding.portion_mode,
                portion_value=binding.portion_value,
                portion_unit=binding.portion_unit,
                optional=bool(ingredient.get("optional", False)),
                preparation=ingredient.get("preparation"),
                display=display,
            )
        )
    return result


def table_view_for_snapshot(
    db: Session,
    version: RecipeVersion,
    snapshot: RecipeMethodSnapshot,
    table_snapshot: RecipeMethodTableSnapshot | None,
    scaled_ingredients: list[dict[str, Any]],
    *,
    requested_servings: Decimal | None,
    measurement_system: str,
) -> MethodTableViewOut:
    existing = table_snapshot.document if table_snapshot is not None else None
    document, coverage, warnings, confidence = build_table_projection(snapshot.document, version.ingredients, existing)
    uses = rendered_table_ingredient_uses(
        db,
        version,
        snapshot,
        document,
        scaled_ingredients,
        requested_servings=requested_servings,
        measurement_system=measurement_system,
    )
    return MethodTableViewOut(
        status=table_snapshot.status if table_snapshot is not None else "needs_review",
        confidence=table_snapshot.confidence if table_snapshot is not None else confidence,
        coverage=coverage,
        document=document,
        rendered_ingredient_uses=uses,
        warnings=warnings,
    )
