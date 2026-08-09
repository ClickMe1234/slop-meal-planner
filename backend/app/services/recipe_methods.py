from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..models import FoodRecord, RecipeIngredient, RecipeMethodSnapshot, RecipeVersion
from ..schemas import MethodDocument, MethodSourceBlock
from .measurement_conversion import (
    convert_quantity_to_unit,
    measurement_dimension,
    resolve_measurement_profile,
)
from .regional_ingredients import convert_ingredient_text


METHOD_PARSER_VERSION = "method-rules-1"
METHOD_SCHEMA_VERSION = 1

_CLAUSE_RE = re.compile(r"[^.!?;\n]+(?:[.!?;]+|$)")
_THEN_RE = re.compile(r"\s+then\s+", re.IGNORECASE)
_ACTION_RE = re.compile(
    r"\b(add|arrange|assemble|bake|beat|blend|boil|bring|brown|brush|chill|chop|"
    r"combine|cook|cover|cut|drain|fold|fry|grill|heat|knead|layer|leave|melt|mix|"
    r"place|pour|preheat|reduce|remove|rest|roast|roll|season|serve|simmer|slice|"
    r"spoon|sprinkle|stir|strain|tip|toast|transfer|whisk)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)(?:\s*[-–—]\s*(\d+(?:\.\d+)?))?\s*"
    r"(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE,
)
_TEMPERATURE_RE = re.compile(r"\b(\d{2,3})\s*(?:°|degrees?\s*)?([cf])\b", re.IGNORECASE)
_CUE_RE = re.compile(r"\buntil\s+([^.;]+)", re.IGNORECASE)
_OMIT_RE = re.compile(r"^\s*(?:tip|note|variation|optional idea)\s*[:—-]", re.IGNORECASE)
_PARALLEL_RE = re.compile(r"^\s*(?:meanwhile|while\s+.+?\s+cooks?)\b", re.IGNORECASE)
_MERGE_RE = re.compile(r"\b(?:add|assemble|combine|fold|layer|mix|pour|stir)\b", re.IGNORECASE)
_EQUIPMENT = (
    "baking tray",
    "food processor",
    "frying pan",
    "saucepan",
    "skillet",
    "oven",
    "grill",
    "bowl",
    "whisk",
    "blender",
    "knife",
    "tin",
    "dish",
    "pan",
)
_STOP_TERMS = {
    "a",
    "an",
    "and",
    "as",
    "for",
    "fresh",
    "ground",
    "large",
    "medium",
    "of",
    "optional",
    "small",
    "the",
    "to",
}


def _value(row: object, name: str, default: Any = None) -> Any:
    return row.get(name, default) if isinstance(row, dict) else getattr(row, name, default)


def source_blocks_from_extracted(instruction_blocks: Iterable[object]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"block-{position + 1}",
            "position": position,
            "heading": _value(block, "heading"),
            "text": str(_value(block, "text", "")).strip(),
        }
        for position, block in enumerate(instruction_blocks)
        if str(_value(block, "text", "")).strip()
    ]


def source_text_from_blocks(blocks: Iterable[dict[str, Any] | MethodSourceBlock]) -> str:
    return "\n\n".join(str(_value(block, "text", "")).strip() for block in blocks).strip()


def _clause_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in _CLAUSE_RE.finditer(text):
        raw_start, raw_end = match.span()
        raw = match.group()
        pieces = list(_THEN_RE.finditer(raw))
        boundaries = [0, *(piece.end() for piece in pieces), len(raw)]
        for index in range(len(boundaries) - 1):
            start = raw_start + boundaries[index]
            end = raw_start + boundaries[index + 1]
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            if end > start:
                spans.append((start, end, text[start:end]))
    return spans


def _ingredient_terms(ingredient: object) -> list[str]:
    candidates: list[str] = []
    for name in ("food_phrase", "parsed_food_phrase"):
        value = str(_value(ingredient, name, "") or "").strip().casefold()
        if value:
            candidates.append(value)
    candidates.extend(str(item).casefold() for item in (_value(ingredient, "parser_name_keys", []) or []))
    original = re.sub(r"^\s*[\d¼½¾⅓⅔⅛⅜⅝⅞/.,\s-]+", "", str(_value(ingredient, "original_text", ""))).casefold()
    original = re.sub(r"\([^)]*\)", " ", original)
    original = re.split(r"[,;]", original, maxsplit=1)[0]
    if original.strip():
        candidates.append(original.strip())
    terms: set[str] = set()
    for candidate in candidates:
        cleaned = " ".join(candidate.split())
        if len(cleaned) >= 3 and cleaned not in _STOP_TERMS:
            terms.add(cleaned)
        words = [word for word in re.findall(r"[a-z][a-z'-]+", cleaned) if word not in _STOP_TERMS]
        if words:
            terms.add(words[-1])
    return sorted(terms, key=len, reverse=True)


def _portion_for_ingredient(
    clause: str,
    ingredient_start: int,
    ingredient_starts: list[int],
) -> tuple[str, Decimal | None]:
    """Attach a portion phrase to the next ingredient it qualifies."""

    lowered = clause.casefold()
    markers: list[tuple[int, int, str, Decimal | None]] = []
    for match in re.finditer(r"\b(?:remaining|remainder|rest of)\b", lowered):
        markers.append((match.start(), match.end(), "remainder", None))
    for word, value in (
        ("two thirds", Decimal("0.666667")),
        ("half", Decimal("0.5")),
        ("quarter", Decimal("0.25")),
        ("third", Decimal("0.333333")),
    ):
        for match in re.finditer(rf"\b{re.escape(word)}\b", lowered):
            markers.append((match.start(), match.end(), "fraction", value))

    for _, marker_end, mode, value in sorted(markers, key=lambda item: item[0]):
        following = [start for start in ingredient_starts if start >= marker_end]
        if following and min(following) == ingredient_start:
            return mode, value
    return "unspecified", None


def _minutes(match: re.Match[str] | None) -> Decimal | None:
    if match is None:
        return None
    low = Decimal(match.group(1))
    high = Decimal(match.group(2)) if match.group(2) else low
    value = (low + high) / 2
    unit = match.group(3).casefold()
    if unit.startswith("hour") or unit.startswith("hr"):
        value *= 60
    elif unit.startswith("sec"):
        value /= 60
    return value


def parse_method_document(
    blocks: Iterable[dict[str, Any] | MethodSourceBlock],
    ingredients: Iterable[object],
) -> tuple[MethodDocument, dict[str, int], Decimal]:
    source_blocks = [
        block if isinstance(block, MethodSourceBlock) else MethodSourceBlock.model_validate(block)
        for block in blocks
    ]
    ingredient_rows = list(ingredients)
    term_index = [(ingredient, _ingredient_terms(ingredient)) for ingredient in ingredient_rows]

    annotations: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    latest_by_stage: dict[str, str] = {}
    stage_by_heading: dict[str, str] = {}
    total = represented = omitted = unreviewed = 0

    def ensure_stage(title: str) -> str:
        key = " ".join(title.casefold().split())
        existing = stage_by_heading.get(key)
        if existing:
            return existing
        stage_id = f"stage-{len(stages) + 1}"
        stages.append({"id": stage_id, "title": title[:160], "position": len(stages)})
        stage_by_heading[key] = stage_id
        return stage_id

    default_stage = ensure_stage("Method")
    confidence_values: list[Decimal] = []
    for block in source_blocks:
        stage_id = ensure_stage(block.heading or "Method")
        for start, end, clause in _clause_spans(block.text):
            total += 1
            if _OMIT_RE.search(clause):
                omitted += 1
                omissions.append(
                    {
                        "id": f"omission-{len(omissions) + 1}",
                        "block_id": block.id,
                        "start": start,
                        "end": end,
                        "reason": "Explanation or optional tip",
                        "accepted": False,
                    }
                )
                continue
            if _PARALLEL_RE.search(clause):
                stage_id = ensure_stage(block.heading or f"Parallel stage {len(stages)}")

            action_match = _ACTION_RE.search(clause)
            action_confidence = Decimal("0.88") if action_match else Decimal("0.48")
            if action_match:
                represented += 1
            else:
                unreviewed += 1
            action_annotation_id = f"annotation-{len(annotations) + 1}"
            annotations.append(
                {
                    "id": action_annotation_id,
                    "block_id": block.id,
                    "start": start,
                    "end": end,
                    "kind": "action",
                    "origin": "automatic",
                    "confidence": action_confidence,
                    "accepted": False,
                }
            )
            duration_match = _DURATION_RE.search(clause)
            temperature_match = _TEMPERATURE_RE.search(clause)
            cue_match = _CUE_RE.search(clause)
            equipment = [item for item in _EQUIPMENT if re.search(rf"\b{re.escape(item)}\b", clause, re.IGNORECASE)]
            for kind, match, normalized in (
                ("time", duration_match, {"minutes": str(_minutes(duration_match))} if duration_match else None),
                (
                    "temperature",
                    temperature_match,
                    {
                        "value": temperature_match.group(1),
                        "unit": temperature_match.group(2).casefold(),
                    }
                    if temperature_match
                    else None,
                ),
                ("cue", cue_match, {"text": cue_match.group(1).strip()} if cue_match else None),
            ):
                if match is None:
                    continue
                annotations.append(
                    {
                        "id": f"annotation-{len(annotations) + 1}",
                        "block_id": block.id,
                        "start": start + match.start(),
                        "end": start + match.end(),
                        "kind": kind,
                        "origin": "automatic",
                        "confidence": Decimal("0.96"),
                        "accepted": False,
                        "normalized_value": normalized,
                    }
                )
            for item in equipment:
                equipment_match = re.search(rf"\b{re.escape(item)}\b", clause, re.IGNORECASE)
                if equipment_match:
                    annotations.append(
                        {
                            "id": f"annotation-{len(annotations) + 1}",
                            "block_id": block.id,
                            "start": start + equipment_match.start(),
                            "end": start + equipment_match.end(),
                            "kind": "equipment",
                            "origin": "automatic",
                            "confidence": Decimal("0.94"),
                            "accepted": False,
                            "normalized_value": {"name": item},
                        }
                    )

            action_id = f"action-{len(actions) + 1}"
            action = {
                "id": action_id,
                "stage_id": stage_id or default_stage,
                "position": sum(1 for item in actions if item["stage_id"] == stage_id),
                "text": clause.strip(" \t\r\n.;"),
                "source_annotation_ids": [action_annotation_id],
                "duration_minutes": _minutes(duration_match),
                "temperature_value": Decimal(temperature_match.group(1)) if temperature_match else None,
                "temperature_unit": temperature_match.group(2).casefold() if temperature_match else None,
                "equipment": equipment,
                "cue": cue_match.group(1).strip() if cue_match else None,
                "confidence": action_confidence,
            }
            actions.append(action)
            previous = latest_by_stage.get(stage_id)
            if previous:
                edges.append(
                    {
                        "id": f"edge-{len(edges) + 1}",
                        "from_action_id": previous,
                        "to_action_id": action_id,
                        "kind": "sequence",
                        "confidence": Decimal("0.9"),
                    }
                )

            lowered = clause.casefold()
            matched_lineages: set[str] = set()
            matched_ingredients: list[tuple[object, list[str], re.Match[str]]] = []
            for ingredient, terms in term_index:
                lineage_id = str(_value(ingredient, "lineage_id", ""))
                if not lineage_id or lineage_id in matched_lineages:
                    continue
                found: re.Match[str] | None = None
                for term in terms:
                    found = re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", lowered)
                    if found:
                        break
                if not found:
                    continue
                matched_lineages.add(lineage_id)
                matched_ingredients.append((ingredient, terms, found))

            ingredient_starts = [found.start() for _, _, found in matched_ingredients]
            for ingredient, terms, found in matched_ingredients:
                lineage_id = str(_value(ingredient, "lineage_id", ""))
                annotation_id = f"annotation-{len(annotations) + 1}"
                annotations.append(
                    {
                        "id": annotation_id,
                        "block_id": block.id,
                        "start": start + found.start(),
                        "end": start + found.end(),
                        "kind": "ingredient",
                        "origin": "automatic",
                        "confidence": Decimal("0.9"),
                        "accepted": False,
                        "ingredient_lineage_id": lineage_id,
                    }
                )
                portion_mode, portion_value = _portion_for_ingredient(
                    clause,
                    found.start(),
                    ingredient_starts,
                )
                bindings.append(
                    {
                        "id": f"binding-{len(bindings) + 1}",
                        "action_id": action_id,
                        "ingredient_lineage_id": lineage_id,
                        "annotation_id": annotation_id,
                        "portion_mode": portion_mode,
                        "portion_value": portion_value,
                        "confidence": Decimal("0.9" if len(terms) else "0.55"),
                        "accepted": False,
                    }
                )

            if _MERGE_RE.search(clause) and len(latest_by_stage) > 1:
                for other_stage, latest_action in list(latest_by_stage.items()):
                    if other_stage == stage_id or latest_action == action_id:
                        continue
                    edges.append(
                        {
                            "id": f"edge-{len(edges) + 1}",
                            "from_action_id": latest_action,
                            "to_action_id": action_id,
                            "kind": "merge",
                            "confidence": Decimal("0.62"),
                        }
                    )
            latest_by_stage[stage_id] = action_id
            confidence_values.append(action_confidence)

    if not stages:
        stages.append({"id": "stage-1", "title": "Method", "position": 0})
    coverage = {
        "total_clauses": total,
        "represented": represented,
        "omitted": omitted,
        "unreviewed": unreviewed,
    }
    confidence = (
        sum(confidence_values, Decimal("0")) / len(confidence_values)
        if confidence_values
        else Decimal("0")
    )
    document = MethodDocument.model_validate(
        {
            "schema_version": METHOD_SCHEMA_VERSION,
            "annotations": annotations,
            "omissions": omissions,
            "stages": stages,
            "actions": actions,
            "ingredient_bindings": bindings,
            "edges": edges,
        }
    )
    return document, coverage, confidence.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def snapshot_values(
    *,
    blocks: list[dict[str, Any]],
    ingredients: Iterable[object],
    source_kind: str,
    extractor_version: str | None,
    created_by_user_id: str | None,
    household_notes: str | None = None,
) -> dict[str, Any]:
    source_text = source_text_from_blocks(blocks)
    document, coverage, confidence = parse_method_document(blocks, ingredients)
    return {
        "source_kind": source_kind,
        "source_text": source_text,
        "source_blocks": blocks,
        "source_checksum": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "extractor_version": extractor_version,
        "parser_version": METHOD_PARSER_VERSION,
        "status": "needs_review",
        "confidence": confidence,
        "coverage": coverage,
        "document": document.model_dump(mode="json"),
        "household_notes": household_notes,
        "created_by_user_id": created_by_user_id,
    }


def clone_method_snapshot(
    previous: RecipeMethodSnapshot,
    *,
    recipe_version_id: str,
    created_by_user_id: str | None,
    force_needs_review: bool = False,
) -> RecipeMethodSnapshot:
    return RecipeMethodSnapshot(
        recipe_version_id=recipe_version_id,
        source_kind=previous.source_kind,
        source_text=previous.source_text,
        source_blocks=list(previous.source_blocks or []),
        source_checksum=previous.source_checksum,
        extractor_version=previous.extractor_version,
        parser_version=previous.parser_version,
        status="needs_review" if force_needs_review else previous.status,
        confidence=previous.confidence,
        coverage=dict(previous.coverage or {}),
        document=dict(previous.document or {}),
        household_notes=previous.household_notes,
        created_by_user_id=created_by_user_id,
        reviewed_by_user_id=None if force_needs_review else previous.reviewed_by_user_id,
        reviewed_at=None if force_needs_review else previous.reviewed_at,
    )


def _display_number(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral():
        return str(int(rounded))
    return format(rounded.normalize(), "f")


def _display_measurement(
    quantity: Decimal | None,
    unit: str | None,
    measurement_system: str,
    density: Decimal | None,
) -> tuple[Decimal | None, str | None]:
    if quantity is None or not unit or measurement_system == "source":
        return quantity, unit
    dimension = measurement_dimension(unit)
    if dimension is None:
        return quantity, unit
    if measurement_system == "metric":
        base_target = "g" if dimension == "mass" else "ml"
        converted = convert_quantity_to_unit(quantity, unit, base_target, density)
        if converted is None:
            return quantity, unit
        if converted >= 1000:
            larger = "kg" if dimension == "mass" else "l"
            return convert_quantity_to_unit(quantity, unit, larger, density), larger
        return converted, base_target
    if dimension == "mass":
        grams = convert_quantity_to_unit(quantity, unit, "g", density)
        target = "lb" if grams is not None and grams >= Decimal("453.59237") else "oz"
    else:
        millilitres = convert_quantity_to_unit(quantity, unit, "ml", density)
        if millilitres is not None and millilitres >= Decimal("60"):
            target = "cup"
        elif millilitres is not None and millilitres >= Decimal("15"):
            target = "tbsp"
        else:
            target = "tsp"
    converted = convert_quantity_to_unit(quantity, unit, target, density)
    return (converted, target) if converted is not None else (quantity, unit)


def scaled_ingredients(
    db: Session,
    version: RecipeVersion,
    *,
    requested_servings: Decimal | None,
    ingredient_locale: str,
    measurement_system: str,
) -> list[dict[str, Any]]:
    scale = Decimal("1")
    if requested_servings is not None and version.yield_servings:
        scale = requested_servings / Decimal(version.yield_servings)
    result: list[dict[str, Any]] = []
    for ingredient in version.ingredients:
        if not ingredient.included:
            continue
        quantity = Decimal(ingredient.quantity) * scale if ingredient.quantity is not None else None
        density = None
        if ingredient.food_record_id:
            food = db.get(FoodRecord, ingredient.food_record_id)
            density = food.density_g_per_ml if food is not None else None
        if density is None:
            profile = resolve_measurement_profile(
                ingredient.food_phrase, ingredient.parsed_food_phrase, ingredient.original_text
            )
            density = profile.density_g_per_ml if profile else None
        display_quantity, display_unit = _display_measurement(
            quantity, ingredient.unit, measurement_system, density
        )
        name = convert_ingredient_text(
            db,
            ingredient.food_phrase or ingredient.parsed_food_phrase or ingredient.original_text,
            ingredient_locale,
        )
        number = _display_number(display_quantity)
        result.append(
            {
                "id": ingredient.id,
                "lineage_id": ingredient.lineage_id,
                "name": name,
                "quantity": float(display_quantity) if display_quantity is not None else None,
                "quantity_text": number,
                "unit": display_unit,
                "display": " ".join(item for item in (number, display_unit, name) if item),
                "optional": ingredient.optional,
                "preparation": ingredient.preparation,
            }
        )
    return result


def rendered_source_blocks(
    db: Session,
    snapshot: RecipeMethodSnapshot,
    ingredients: list[dict[str, Any]],
    ingredient_locale: str,
) -> list[dict[str, Any]]:
    document = MethodDocument.model_validate(snapshot.document)
    display_by_lineage = {item["lineage_id"]: item for item in ingredients}
    binding_by_annotation = {
        binding.annotation_id: binding
        for binding in document.ingredient_bindings
        if binding.annotation_id
    }
    fraction_totals: dict[str, Decimal] = defaultdict(Decimal)
    for binding in document.ingredient_bindings:
        if binding.portion_mode == "fraction" and binding.portion_value is not None:
            fraction_totals[binding.ingredient_lineage_id] += binding.portion_value
    annotations_by_block: dict[str, list[Any]] = defaultdict(list)
    for annotation in document.annotations:
        if annotation.kind == "ingredient":
            annotations_by_block[annotation.block_id].append(annotation)
    rendered: list[dict[str, Any]] = []
    for raw_block in snapshot.source_blocks or []:
        block = MethodSourceBlock.model_validate(raw_block)
        cursor = 0
        segments: list[dict[str, Any]] = []
        for annotation in sorted(annotations_by_block.get(block.id, []), key=lambda item: (item.start, item.end)):
            if annotation.start < cursor or annotation.end > len(block.text):
                continue
            if annotation.start > cursor:
                segments.append({"kind": "text", "text": block.text[cursor:annotation.start]})
            original = block.text[annotation.start:annotation.end]
            localized = convert_ingredient_text(db, original, ingredient_locale) or original
            ingredient = display_by_lineage.get(annotation.ingredient_lineage_id or "")
            binding = binding_by_annotation.get(annotation.id)
            quantity_label = ingredient.get("display") if ingredient else None
            if binding and ingredient and binding.portion_mode == "fraction" and binding.portion_value is not None:
                quantity = Decimal(str(ingredient.get("quantity") or 0)) * binding.portion_value
                quantity_label = " ".join(
                    item
                    for item in (_display_number(quantity), ingredient.get("unit"), ingredient.get("name"))
                    if item
                )
            elif binding and ingredient and binding.portion_mode == "remainder":
                remainder = max(
                    Decimal("0"),
                    Decimal("1") - fraction_totals[binding.ingredient_lineage_id],
                )
                quantity = Decimal(str(ingredient.get("quantity") or 0)) * remainder
                quantity_label = " ".join(
                    item
                    for item in (_display_number(quantity), ingredient.get("unit"), ingredient.get("name"))
                    if item
                )
            segments.append(
                {
                    "kind": "ingredient",
                    "text": localized,
                    "annotation_id": annotation.id,
                    "ingredient_lineage_id": annotation.ingredient_lineage_id,
                    "quantity_label": quantity_label,
                }
            )
            cursor = annotation.end
        if cursor < len(block.text):
            segments.append({"kind": "text", "text": block.text[cursor:]})
        rendered.append(
            {
                "id": block.id,
                "position": block.position,
                "heading": block.heading,
                "text": block.text,
                "segments": segments,
            }
        )
    return rendered


def validate_method_for_review(document: MethodDocument, coverage: dict[str, Any]) -> None:
    if int(coverage.get("unreviewed", 0)) > 0:
        raise ValueError("Every source clause must be represented or explicitly omitted")
    if any(annotation.confidence < Decimal("0.65") and not annotation.accepted for annotation in document.annotations):
        raise ValueError("Low-confidence annotations must be corrected or accepted")
    if any(binding.confidence < Decimal("0.65") and not binding.accepted for binding in document.ingredient_bindings):
        raise ValueError("Low-confidence ingredient bindings must be corrected or accepted")


def current_method_snapshot(version: RecipeVersion) -> RecipeMethodSnapshot | None:
    return version.method_snapshot
